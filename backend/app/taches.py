"""Tâches planifiées, lancées par GitHub Actions (ou à la main) — sans serveur :

    python -m app.taches run [--telegram] [--moteur central|agent|deterministe] [--sans-redaction] \
[--si-aucun-ticket-aujourdhui] [--profils-json JSON] [--ignorer-diversite-croisee]
    python -m app.taches verifier [--telegram]
    python -m app.taches live [--telegram] [--run-id N]
    python -m app.taches envoyer [--run-id N] [--forcer]
    python -m app.taches tester-api
    python -m app.taches backfill --ligue N --saisons 2023,2024 [--sans-stats] [--limite-appels-stats N]

Code de sortie 1 si le run finit en erreur : le workflow GitHub apparaît alors en rouge."""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, time, timezone

from sqlalchemy import select, text

from app.database import SessionLocal, init_db
from app.models import Coupon, MemoireAgent, Run
from app.services import pipeline
from app.services.bilan import envoyer_bilans
from app.garde import autre_run_en_cours, relances_payantes_epuisees, ticket_deja_produit_aujourdhui
from app.services.runs import cloturer_runs_interrompus, executer_run
from app.services import alertes, analyse_coupons, github_actions, plan_verification
from app.services.verification import etat_live_jambes, verification_due, verifier_coupons_en_attente


def tache_run(args):
    with SessionLocal() as db:
        if args.si_aucun_ticket_aujourdhui and ticket_deja_produit_aujourdhui(db):
            print("ℹ️ Ticket du jour déjà produit (ou run en cours) — pas de relance.")
            if args.telegram:   # dernier passage de la fenêtre sans aucun coupon envoyé (run bloqué) : on prévient
                try:
                    _, ae, _ = pipeline.modules()
                    alertes.envoyer_alerte_passage_saute(db, ae.notifier_telegram)
                except Exception as e:
                    print(f"⚠️ Alerte Telegram impossible : {str(e)[:150]}")
            return 0
        if args.si_aucun_ticket_aujourdhui and relances_payantes_epuisees(db):
            # Phase 4 : plusieurs échecs AVEC dépense aujourd'hui -> plus de relance payante automatique (alerte au dernier passage)
            print("⛔ Relances payantes épuisées aujourd'hui (échecs avec dépense) — aucune nouvelle dépense automatique.")
            if args.telegram:
                try:
                    _, ae, _ = pipeline.modules()
                    alertes.envoyer_alerte_passage_saute(db, ae.notifier_telegram, cause="relances")
                except Exception as e:
                    print(f"⚠️ Alerte Telegram impossible : {str(e)[:150]}")
            return 0
        run = Run(source="api", statut="en_cours")
        db.add(run)
        db.commit()
        run_id = run.id
        # Sur GitHub Actions, le groupe de concurrence du workflow sérialise déjà tous les runs
        # (queue: max). Ne pas laisser une ancienne ligne DB « en_cours » bloquer les lancements
        # manuels suivants : le garde-fou DB reste actif hors GitHub (Termux/API).
        if os.getenv("GITHUB_RUN_ID"):
            concurrent = None
        else:
            concurrent = autre_run_en_cours(db, run_id)
        if concurrent is not None:
            run.statut, run.detail = "abandonne", f"Exécution simultanée : le run {concurrent} est déjà en cours — aucune dépense."
            run.termine_le = datetime.now(timezone.utc)
            db.commit()
            print(f"⛔ {run.detail}")
            return 0
    _initialiser_fichier_couts(run_id)

    profils_personnalises = None
    profils_json = getattr(args, "profils_json", "") or ""
    if profils_json.strip():
        profils_personnalises = json.loads(profils_json)
    ignorer_diversite_croisee = getattr(args, "ignorer_diversite_croisee", False)

    suffixe = f" — {len(profils_personnalises)} profil(s) personnalisé(s)" if profils_personnalises else ""
    print(f"🚀 Run {run_id} — Telegram : {'oui' if args.telegram else 'non'} — moteur : {args.moteur}{suffixe}")
    executer_run(run_id, envoyer_telegram=args.telegram, rediger=not args.sans_redaction,
                 depuis_run=getattr(args, "depuis_run", None), moteur=args.moteur,
                 profils_personnalises=profils_personnalises, ignorer_diversite_croisee=ignorer_diversite_croisee)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        print(f"🏁 Run {run_id} : {run.statut}" + (f" — {run.detail}" if run.detail else ""))
        for c in run.coupons:
            print(f"   {c.nom} : {len(c.jambes)} jambe(s), cote {c.cote_totale}")
        envoye = bool(run.envoye_telegram)
        statut = run.statut
    if envoye and args.telegram and statut == "termine":
        try:  # le plan ne doit jamais faire échouer un run dont les coupons sont déjà partis
            tache_planifier(argparse.Namespace(run_id=run_id, coupons="", telegram=True, sans_ia=False))
        except Exception as e:
            print(f"⚠️ Planification de la vérification impossible : {e}")
    if args.telegram:   # plus d'échec silencieux : abandon, erreur ou envoi partiel sont signalés (jamais bloquant)
        try:
            _, ae, _ = pipeline.modules()
            with SessionLocal() as db:
                alertes.envoyer_alerte_si_besoin(db, run_id, ae.notifier_telegram, cron=bool(args.si_aucun_ticket_aujourdhui))
                alertes.envoyer_alerte_budget(db, run_id, ae.notifier_telegram)
                alertes.envoyer_alerte_seuil_budget(db, run_id, ae.notifier_telegram)
        except Exception as e:
            print(f"⚠️ Alerte Telegram impossible : {str(e)[:150]}")
    return 1 if statut == "erreur" else 0


def _initialiser_fichier_couts(run_id):
    """Pose le numéro du run dans COUTS_FICHIER (si configuré) : l'agent y ajoute ses coûts après chaque appel, et `finaliser` relit le tout si le job est tué."""
    try:
        pipeline.modules()
        import budget_ia
        if budget_ia.fichier_couts():
            budget_ia.ecrire_couts({"run_id": run_id, "pilote": {}, "vote": []})
    except Exception as e:
        print(f"⚠️ Fichier de coûts non initialisé : {str(e)[:120]}")


def tache_finaliser(args):
    """Étape du workflow exécutée TOUJOURS après le pipeline (`if: always()`) : si le job a été tué (délai, annulation) le run reste « en_cours » et
    ses coûts sont perdus. Cette tâche le clôture en « interrompu » avec la dépense écrite au fil de l'eau (COUTS_FICHIER). Idempotente : ne touche
    jamais un run déjà terminé, n'envoie rien, n'appelle aucune API. Code de sortie 0 dans tous les cas (elle ne doit jamais masquer le vrai résultat)."""
    from app.services.budget import couts_depuis_fichier, texte_couts_pour_detail
    try:
        pipeline.modules()
        import budget_ia
        donnees = budget_ia.lire_couts()
        if not donnees or not donnees.get("run_id"):
            print("ℹ️ Finalisation : aucun fichier de coûts — rien à faire.")
            return 0
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "postgresql":   # jamais bloquée par un verrou d'une session zombie : abandon après quelques secondes
                db.execute(text("SET LOCAL lock_timeout = '10s'"))
                db.execute(text("SET LOCAL statement_timeout = '30s'"))
            run = db.get(Run, int(donnees["run_id"]))
            if run is None or run.statut != "en_cours":
                print(f"ℹ️ Finalisation : run {donnees['run_id']} déjà terminé ({getattr(run, 'statut', 'introuvable')}) — rien à faire.")
                return 0
            run.statut = "interrompu"
            run.detail = ("Interrompu : le job s'est arrêté avant la fin du pipeline (délai dépassé ou annulation)."
                          + texte_couts_pour_detail(couts_depuis_fichier(donnees)))[:4000]
            run.termine_le = datetime.now(timezone.utc)
            db.commit()
            print(f"🧹 Finalisation : run {run.id} clôturé en « interrompu » (dépense conservée dans le détail).")
    except Exception as e:   # jamais bloquant
        print(f"⚠️ Finalisation impossible : {str(e)[:150]}")
    return 0


def tache_verifier(args):
    with SessionLocal() as db:
        compte = verifier_coupons_en_attente(db)
        print(f"🔎 Jambes jugées : {dict(compte) or 'aucune (rien en attente ou matchs pas terminés)'}")
        if args.telegram:
            _, ae, _ = pipeline.modules()
            # Heure limite du plan dépassée : rapport final envoyé même si un match manque (partiel).
            echus = plan_verification.echeances_depassees(db)
            runs_forces = {pv.run_id for pv in echus}
            envoyes = envoyer_bilans(db, ae.notifier_telegram, forcer_runs=runs_forces)
            print(f"📤 Bilan(s) Telegram envoyé(s) : {envoyes}")
            try:  # étude des erreurs des jours jugés -> mémoire de l'agent ; jamais bloquant
                from app.services import apprentissage
                etudies = apprentissage.etudier_recents(db)
                if etudies:
                    print(f"🧠 Mémoire : études enregistrées pour {[j.isoformat() for j in etudies]}")
            except Exception as e:
                print(f"ℹ️ Étude des erreurs impossible : {str(e)[:120]}")
            for pv in plan_verification_a_cloturer(db):
                pv.rapport_final_envoye = True
            db.commit()
            if getattr(args, "si_du", False) and not plan_verification.plans_ouverts(db):
                # Rapport final envoyé pour tous les coupons planifiés : plus aucun passage jusqu'au prochain run.
                github_actions.activer_workflow(actif=False)
    return 0


def tache_budget(args):
    """Dépenses IA mesurées (lecture seule) : par jour, par modèle, gagnants du vote, budget restant aujourd'hui."""
    from app.services import budget
    with SessionLocal() as db:
        r = budget.resume(db, jours=args.jours)
        plafond = r["plafond_jour_usd"]
        print(f"💰 Plafond journalier : {'aucun' if plafond is None else f'{plafond:.2f} $'} · dépensé aujourd'hui : {r['depense_aujourdhui_usd']:.2f} $"
              + ("" if plafond is None else f" · restant : {max(0.0, plafond - r['depense_aujourdhui_usd']):.2f} $"))
        for jour, total in r["par_jour"].items():
            print(f"   {jour} : {total:.2f} $")
        for modele, v in r["par_modele"].items():
            print(f"   {modele} : {v['cout_usd']:.2f} $ · {v['tokens_entree']} → {v['tokens_sortie']} tokens · {v['appels']} appel(s) · "
                  f"{v['coupons_retenus']} coupon(s) retenu(s)")
    return 0


def tache_apprendre(args):
    """Étudie les jours déjà jugés (erreurs, jambes tueuses, fiabilité des probabilités) et alimente la mémoire de l'agent.
    --exporter FICHIER : copie la mémoire dans un fichier JSON (lecture seule, refuse d'écraser un fichier existant).
    --apercu : calcule les nouvelles études des jours demandés (coupons ENVOYÉS seulement) et les affiche à côté des anciennes,
    SANS rien écrire ni supprimer (aucune validation requise : c'est le mode de contrôle avant `--refaire`)."""
    from app.services import apprentissage
    with SessionLocal() as db:
        if getattr(args, "exporter", None):
            chemin = Path(args.exporter)
            if chemin.exists():
                print(f"❌ {chemin} existe déjà : sauvegarde non écrasée.")
                return 1
            lignes = apprentissage.exporter_memoire(db)
            chemin.write_text(json.dumps(lignes, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"💾 {len(lignes)} étude(s) sauvegardée(s) dans {chemin} (base inchangée).")
            return 0
        if getattr(args, "apercu", False):
            if not args.jour:
                print("❌ --apercu demande --jour AAAA-MM-JJ[,AAAA-MM-JJ...]")
                return 1
            for jour in (j.strip() for j in args.jour.split(",") if j.strip()):
                jour_date = datetime.fromisoformat(jour).date()
                ancienne = db.scalars(select(MemoireAgent).where(MemoireAgent.jour == jour_date, MemoireAgent.type == "etude")).first()
                nouvelle = apprentissage.etudier_jour(db, jour_date, avec_ia=not args.sans_ia, refaire=True, ecrire=False)
                print(f"\n===== {jour} =====\n--- ANCIENNE ÉTUDE ---\n{ancienne.contenu if ancienne else '(aucune)'}\n"
                      f"--- NOUVELLE ÉTUDE (coupons envoyés seulement) ---\n{nouvelle or '(aucun coupon envoyé entièrement jugé : rien à étudier)'}")
            print("\nℹ️ Aperçu seulement : aucune écriture en base.")
            return 0
        if args.jour:
            texte = apprentissage.etudier_jour(db, datetime.fromisoformat(args.jour).date(), avec_ia=not args.sans_ia, refaire=args.refaire)
            print(texte or f"ℹ️ Rien à étudier pour {args.jour} (déjà étudié, ou coupons pas tous jugés).")
        else:
            jours = apprentissage.etudier_recents(db, jours=args.jours, avec_ia=not args.sans_ia, refaire=args.refaire)
            print(f"🧠 Études enregistrées : {[j.isoformat() for j in jours] or 'aucune'}")
        print("\n--- Mémoire transmise à l'agent ---\n" + (apprentissage.memoire_pour_prompt(db) or "(vide)"))
    return 0


def plan_verification_a_cloturer(db):
    """Plans dont tous les coupons ont leur bilan envoyé : plus rien à planifier."""
    from app.models import Coupon, PlanVerification
    clos = []
    for pv in db.scalars(select(PlanVerification).where(PlanVerification.rapport_final_envoye.is_(False))):
        coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == pv.run_id)))
        run = db.get(Run, pv.run_id)
        if run is not None and not run.envoye_telegram:   # run jamais envoyé : aucun bilan ne viendra, le plan ne reste pas ouvert
            clos.append(pv)
        elif coupons and all(c.bilan_envoye or not c.jambes for c in coupons):
            clos.append(pv)
    return clos


def _analyser_coupons_envoyes(plan, notifier, avec_ia):
    """Après le plan : analyse des coupons (idées de sélection, lecture des cotes, risques), envoyée sur Telegram."""
    try:
        with SessionLocal() as db:
            coupons = list(db.scalars(select(Coupon).where(Coupon.id.in_(plan.get("coupon_ids", [])))))
            message = analyse_coupons.message_analyse(coupons, avec_ia=avec_ia) if coupons else None
        if message:
            notifier(message)
            print(message)  # visible dans le journal du run
    except Exception as e:  # l'analyse ne doit jamais bloquer le plan déjà envoyé
        print(f"⚠️ Analyse des coupons impossible : {str(e)[:160]}")


def tache_planifier(args):
    """Agent de planification : analyse les matchs des coupons envoyés, planifie les vérifications et annonce le plan."""
    _, ae, _ = pipeline.modules()
    ids = [int(x) for x in (args.coupons or "").split(",") if x.strip().isdigit()]
    with SessionLocal() as db:
        run_id = args.run_id
        if not ids and run_id is None:
            run_id = db.scalar(select(Run.id).where(Run.statut == "termine").order_by(Run.id.desc()).limit(1))
        plan = plan_verification.planifier(db, run_id=run_id, coupon_ids=ids or None,
                                           notifier=ae.notifier_telegram if args.telegram else None,
                                           avec_ia=not args.sans_ia)
    if plan is None:
        print("ℹ️ Aucun coupon avec des jambes : rien à planifier.")
        return 0
    if args.telegram:
        github_actions.activer_workflow(actif=True)  # les vérifications ne tournent que pendant la vie des coupons
        if not getattr(args, "sans_analyse", False):
            _analyser_coupons_envoyes(plan, ae.notifier_telegram, not args.sans_ia)
    jour = datetime.fromisoformat(plan["vagues"][0]["coup_envoi_premier"]).astimezone(plan_verification.DJIBOUTI).date().isoformat() \
        if plan["vagues"] else "—"
    print(plan_verification.message_plan(plan, jour))
    return 0


VERDICT_EMOJI = {"gagne": "✅", "perdu": "❌", "push": "➖", "demi_gagne": "🟢½", "demi_perdu": "🔴½", "non_verifiable": "❔"}


def _formater_rapport_live(etats):
    if not etats:
        return "ℹ️ Aucun pari en attente sur un match actuellement en direct (API-Football)."
    lignes = ["📡 *Suivi en direct* (si le match se terminait MAINTENANT — pas un résultat final) :"]
    for e in etats:
        minute = f"{e['minute']}'" if e["minute"] is not None else e["statut"]
        emoji = VERDICT_EMOJI.get(e["verdict_si_ca_finissait_maintenant"], "❔")
        lignes.append(
            f"\n{e['coupon']}\n⚽ {e['match']} — {e['score_actuel']} ({minute})\n"
            f"   🎯 {e['marche']} : {e['selection']} @ {e['cote']}\n"
            f"   {emoji} {e['verdict_si_ca_finissait_maintenant']}"
        )
    return "\n".join(lignes)


def tache_live(args):
    with SessionLocal() as db:
        etats = etat_live_jambes(db, run_id=args.run_id)
    rapport = _formater_rapport_live(etats)
    print(rapport)
    if args.telegram and etats:
        _, ae, _ = pipeline.modules()
        ae.notifier_telegram(rapport)
    return 0


def tache_envoyer(args):
    """Envoie sur Telegram les coupons DÉJÀ calculés et rédigés d'un run (sans relancer la
    collecte ni l'IA) — ex. après un essai lancé sans Telegram. Par défaut : le dernier run
    terminé. Jamais deux fois le même run, sauf --forcer."""
    with SessionLocal() as db:
        requete = select(Run).where(Run.statut == "termine").order_by(Run.id.desc())
        if args.run_id is not None:
            requete = select(Run).where(Run.id == args.run_id)
        run = db.scalar(requete)
        if not run:
            print("❌ Aucun run terminé à envoyer.")
            return 1
        if run.envoye_telegram and not args.forcer:
            print(f"ℹ️ Run {run.id} déjà envoyé sur Telegram — rien à faire (--forcer pour renvoyer).")
            return 0
        retenus = {int(x) for x in str(getattr(args, "coupons", "") or "").replace(" ", "").split(",") if x}
        textes = [c.texte for c in run.coupons if c.texte and (not retenus or c.id in retenus)]
        if not textes:
            print(f"❌ Run {run.id} ({run.statut}) : aucun coupon rédigé à envoyer.")
            return 1
        _, ae, _ = pipeline.modules()
        run.envoye_telegram = bool(ae.agent5_envoyer_coupons(textes))
        db.commit()
        print(f"{'✅' if run.envoye_telegram else '❌'} Run {run.id} : {len(textes)} coupon(s) "
              f"{'envoyé(s)' if run.envoye_telegram else 'non envoyé(s) — voir erreur Telegram ci-dessus'}")
        return 0 if run.envoye_telegram else 1


def tache_backfill(args):
    """Télécharge et enregistre (table hist_matchs) les matchs d'une ligue sur une ou plusieurs
    saisons, depuis API-Football — alimente moteur/backtest.py sans toucher au pipeline quotidien."""
    from app.services.historique import backfill_ligue_saison

    saisons = [int(s.strip()) for s in args.saisons.split(",") if s.strip()]
    total = {"matchs": 0, "termines": 0, "avec_stats": 0}
    with SessionLocal() as db:
        for saison in saisons:
            print(f"📥 Backfill ligue {args.ligue}, saison {saison}...")
            resultat = backfill_ligue_saison(db, args.ligue, saison, avec_stats=not args.sans_stats,
                                             limite_appels_stats=args.limite_appels_stats)
            for cle in total:
                total[cle] += resultat[cle]
    print(f"🏁 Backfill terminé : {total['matchs']} match(s) enregistré(s) au total "
          f"({total['termines']} terminé(s), {total['avec_stats']} avec statistiques).")
    return 0


def tache_tester_api(args, requetes=None):
    """Vérifie l'Edge Function "api" en ligne, route par route, avec le jeton du Vault, et
    contrôle qu'un appel sans jeton est bien refusé (401). Code de sortie 1 si un contrôle échoue."""
    import requests
    from sqlalchemy import text

    from app import config

    requetes = requetes or requests
    with SessionLocal() as db:
        jeton = db.execute(text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'api_token'")).scalar()
    base = f"{config.SUPABASE_FONCTIONS_URL}/api"
    controles = [
        ("sans jeton → refusé", "/sante", {}, 401),
        ("mauvais jeton → refusé", "/sante", {"X-API-Key": "faux"}, 401),
        ("santé", "/sante", {"X-API-Key": jeton}, 200),
        ("runs", "/runs?limite=5", {"X-API-Key": jeton}, 200),
        ("coupons", "/coupons?limite=5", {"X-API-Key": jeton}, 200),
        ("matchs", "/matchs?limite=5", {"X-API-Key": jeton}, 200),
        ("statistiques", "/statistiques", {"X-API-Key": jeton}, 200),
        ("archives", "/archives", {"X-API-Key": jeton}, 200),
        ("route inconnue", "/inconnue", {"X-API-Key": jeton}, 404),
    ]
    echecs = 0
    for nom, route, entetes, attendu in controles:
        r = requetes.get(base + route, headers=entetes, timeout=30)
        ok = r.status_code == attendu
        echecs += not ok
        print(f"{'✅' if ok else '❌'} {nom:<24} GET {route:<22} → HTTP {r.status_code} (attendu {attendu})"
              + ("" if ok else f" : {r.text[:150]}"))
    print("🏁 API en ligne : tout est conforme." if not echecs else f"🏁 {echecs} contrôle(s) en échec.")
    return 1 if echecs else 0


def verifier_cle_openrouter(requetes):
    """Vérifie le secret OPENROUTER_API_KEY auprès d'OpenRouter (sans jamais l'afficher)."""
    cle = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not cle:
        print("CLE | absente (secret OPENROUTER_API_KEY non transmis)")
        return False
    try:
        r = requetes.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {cle}"}, timeout=30)
        donnees = r.json()
    except Exception as e:
        print(f"CLE | vérification impossible ({type(e).__name__})")
        return False
    if r.status_code != 200:
        message = (donnees.get("error") or {}).get("message", "") if isinstance(donnees, dict) else ""
        print(f"CLE | REFUSÉE (HTTP {r.status_code} : {str(message)[:120]}) — clé supprimée, désactivée "
              "ou mal copiée : recréer une clé sur openrouter.ai/keys et mettre à jour le secret")
        return False
    infos = donnees.get("data") or {}
    print(f"CLE | valide | offre gratuite : {'oui' if infos.get('is_free_tier') else 'non'} "
          f"| limite : {infos.get('limit')} | utilisé : {infos.get('usage')}")
    return True


GROQ_MODELES_PREFERES = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b")
# gemini-2.5-flash est fermé aux nouveaux comptes (HTTP 404, 2026-09-26) : les plus récents d'abord.
GEMINI_MODELES_PREFERES = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                           "gemini-flash-latest")
PROMPT_TEST_IA = 'Réponds UNIQUEMENT avec ce JSON : {"ok": true}'


def _chrono(fonction):
    import time as horloge

    debut = horloge.monotonic()
    resultat = fonction()
    return resultat, horloge.monotonic() - debut


def tester_deepseek(requetes):
    """Clé DeepSeek : une vraie réponse avec deepseek-flash, réflexion désactivée."""
    cle = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not cle:
        print("DEEPSEEK | clé absente (secret DEEPSEEK_API_KEY non transmis)")
        return False
    modele = (os.getenv("DEEPSEEK_MODELES") or "deepseek-flash").split(",")[0].strip() or "deepseek-flash"
    try:
        reponse, duree = _chrono(lambda: requetes.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}, timeout=60,
            json={"model": modele, "messages": [{"role": "user", "content": PROMPT_TEST_IA}], "max_tokens": 400,
                  "thinking": {"type": "disabled"}}))
        if reponse.status_code != 200:
            message = str((reponse.json().get("error") or {}).get("message", ""))[:120]
            etat = "REFUSÉE" if reponse.status_code == 401 else "ÉCHEC"
            print(f"DEEPSEEK | test {modele} : {etat} HTTP {reponse.status_code} {message}")
            return False
        texte = reponse.json()["choices"][0]["message"]["content"].strip()
        print(f"DEEPSEEK | test {modele} : OK en {duree:.1f} s → {texte[:60]!r}")
        return True
    except Exception as e:
        print(f"DEEPSEEK | test impossible ({type(e).__name__})")
        return False


def tester_groq(requetes):
    """Clé Groq : liste des modèles puis une vraie réponse (clé jamais affichée)."""
    cle = os.getenv("GROQ_API_KEY", "").strip()
    if not cle:
        print("GROQ | clé absente (secret GROQ_API_KEY non transmis)")
        return False
    entetes = {"Authorization": f"Bearer {cle}"}
    try:
        r = requetes.get("https://api.groq.com/openai/v1/models", headers=entetes, timeout=30)
        if r.status_code != 200:
            print(f"GROQ | REFUSÉE (HTTP {r.status_code} : {str(r.json().get('error', {}).get('message', ''))[:120]})")
            return False
        disponibles = sorted(m["id"] for m in r.json().get("data", []))
        print(f"GROQ | clé valide | {len(disponibles)} modèle(s) : {', '.join(disponibles)}")
        modele = next((m for m in GROQ_MODELES_PREFERES if m in disponibles), disponibles[0] if disponibles else None)
        if not modele:
            return False
        reponse, duree = _chrono(lambda: requetes.post(
            "https://api.groq.com/openai/v1/chat/completions", headers=entetes, timeout=60,
            json={"model": modele, "messages": [{"role": "user", "content": PROMPT_TEST_IA}], "max_tokens": 400,
                  "reasoning_effort": "low"}))
        if reponse.status_code != 200:
            print(f"GROQ | test {modele} : ÉCHEC HTTP {reponse.status_code} "
                  f"{str(reponse.json().get('error', {}).get('message', ''))[:120]}")
            return False
        texte = reponse.json()["choices"][0]["message"]["content"].strip()
        print(f"GROQ | test {modele} : OK en {duree:.1f} s → {texte[:60]!r}")
        return True
    except Exception as e:
        print(f"GROQ | test impossible ({type(e).__name__})")
        return False


def tester_gemini(requetes):
    """Clé Gemini (en-tête x-goog-api-key, jamais dans l'URL ni affichée)."""
    cle = os.getenv("GEMINI_API_KEY", "").strip()
    if not cle:
        print("GEMINI | clé absente (secret GEMINI_API_KEY non transmis)")
        return False
    entetes = {"x-goog-api-key": cle}
    base = "https://generativelanguage.googleapis.com/v1beta"
    try:
        r = requetes.get(f"{base}/models", headers=entetes, params={"pageSize": 200}, timeout=30)
        if r.status_code != 200:
            print(f"GEMINI | REFUSÉE (HTTP {r.status_code} : {str(r.json().get('error', {}).get('message', ''))[:120]})")
            return False
        texte_ok = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                    if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        print(f"GEMINI | clé valide | {len(texte_ok)} modèle(s) : {', '.join(texte_ok)}")
        modele = next((m for m in GEMINI_MODELES_PREFERES if m in texte_ok), texte_ok[0] if texte_ok else None)
        if not modele:
            return False
        reponse, duree = _chrono(lambda: requetes.post(
            f"{base}/models/{modele}:generateContent", headers=entetes, timeout=60,
            json={"contents": [{"parts": [{"text": PROMPT_TEST_IA}]}]}))
        if reponse.status_code != 200:
            print(f"GEMINI | test {modele} : ÉCHEC HTTP {reponse.status_code} "
                  f"{str(reponse.json().get('error', {}).get('message', ''))[:120]}")
            return False
        texte = reponse.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"GEMINI | test {modele} : OK en {duree:.1f} s → {texte[:60]!r}")
        return True
    except Exception as e:
        print(f"GEMINI | test impossible ({type(e).__name__})")
        return False


# Dernier recours payant (demande explicite du 26/09/2026, testé sur le solde OpenRouter
# existant) : très bon marché, gère outils + JSON (confirmé par le workflow « Modèles
# gratuits », identifiant vérifié sur la page du modèle).
OPENROUTER_MODELE_PAYANT_SECOURS = "deepseek/deepseek-v4.1-flash"


def tester_openrouter_payant(requetes, modele=OPENROUTER_MODELE_PAYANT_SECOURS):
    """Vraie requête payante (dépense réelle, minime) pour confirmer qu'un modèle OpenRouter
    précis répond bien, avant de l'ajouter comme dernier recours dans OPENROUTER_MODELES."""
    cle = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not cle:
        print("OPENROUTER PAYANT | clé absente (secret OPENROUTER_API_KEY non transmis)")
        return False
    reponse, duree = _chrono(lambda: requetes.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}, timeout=60,
        json={"model": modele, "messages": [{"role": "user", "content": PROMPT_TEST_IA}], "max_tokens": 50,
              "response_format": {"type": "json_object"}}))
    if reponse.status_code != 200:
        print(f"OPENROUTER PAYANT | test {modele} : ÉCHEC HTTP {reponse.status_code} "
              f"{str(reponse.json().get('error', {}).get('message', ''))[:150]}")
        return False
    texte = reponse.json()["choices"][0]["message"]["content"].strip()
    print(f"OPENROUTER PAYANT | test {modele} : OK en {duree:.1f} s → {texte[:60]!r}")
    return True


def tache_tester_ia(args, requetes=None):
    """Teste les clés IA disponibles (Groq, Gemini, OpenRouter) avec une vraie réponse, puis le
    modèle payant de dernier recours (dépense réelle minime sur le solde OpenRouter)."""
    import requests

    requetes = requetes or requests
    resultats = {"deepseek": tester_deepseek(requetes), "groq": tester_groq(requetes),
                 "gemini": tester_gemini(requetes),
                 "openrouter": verifier_cle_openrouter(requetes),
                 "openrouter_payant": tester_openrouter_payant(requetes)}
    print("BILAN | " + " | ".join(f"{nom} {'OK' if ok else 'KO'}" for nom, ok in resultats.items()))
    return 0


def tache_modeles_gratuits(args, requetes=None):
    """Liste les modèles GRATUITS d'OpenRouter, puis les 10 moins chers PAYANTS avec tarif au
    million de tokens (identifiant exact, contexte, outils, JSON) — pour choisir OPENROUTER_MODELES
    ou un modèle payant de dernier recours sans deviner les identifiants ni les prix."""
    import requests

    requetes = requetes or requests
    verifier_cle_openrouter(requetes)
    r = requetes.get("https://openrouter.ai/api/v1/models", timeout=30)
    r.raise_for_status()
    gratuits, payants = [], []
    for m in r.json().get("data", []):
        tarif = m.get("pricing") or {}
        prompt_prix, completion_prix = tarif.get("prompt"), tarif.get("completion")
        sortie = (m.get("architecture") or {}).get("output_modalities") or ["text"]
        if "text" not in sortie:
            continue
        parametres = m.get("supported_parameters") or []
        outils = "tools" in parametres
        json_ok = "response_format" in parametres or "structured_outputs" in parametres
        # Gratuit par le suffixe ":free" MÊME sans champ pricing exploitable (constaté : certains
        # modèles gratuits n'ont pas de "pricing" du tout, pas seulement "0").
        gratuit = str(m.get("id", "")).endswith(":free") or (str(prompt_prix) in ("0", "0.0")
                                                             and str(completion_prix) in ("0", "0.0"))
        if gratuit:
            gratuits.append((m["id"], m.get("name", ""), m.get("context_length") or 0, outils, json_ok))
            continue
        try:
            prix_million = (float(prompt_prix) + float(completion_prix)) * 1_000_000 / 2
        except (TypeError, ValueError):
            continue  # pas de tarif chiffrable — ignoré (ni gratuit ni comparable en prix)
        if prix_million <= 0:
            continue  # routeurs à tarif variable (ex. openrouter/auto : prix négatif "spécial"), pas un vrai prix
        payants.append((prix_million, m["id"], m.get("name", ""), m.get("context_length") or 0, outils, json_ok))
    gratuits.sort(key=lambda x: -x[2])
    print(f"{len(gratuits)} modèle(s) texte gratuit(s) sur OpenRouter :")
    for identifiant, nom, contexte, outils, json_ok in gratuits:
        print(f"MODELE | {identifiant} | {nom} | contexte {contexte} | outils {'oui' if outils else 'non'} "
              f"| json {'oui' if json_ok else 'non'}")
    payants.sort()
    print(f"\n{len(payants)} modèle(s) texte payant(s) à tarif fixe — 10 moins chers (dollars / million de "
          "tokens, moyenne prompt+réponse) :")
    for prix_million, identifiant, nom, contexte, outils, json_ok in payants[:10]:
        print(f"PAYANT | {identifiant} | {nom} | ${prix_million:.4f}/M tokens | contexte {contexte} | "
              f"outils {'oui' if outils else 'non'} | json {'oui' if json_ok else 'non'}")
    deepseek = [p for p in payants if "deepseek" in p[1].lower()]
    if deepseek:
        print(f"\n{len(deepseek)} modèle(s) DeepSeek (tous, triés par prix) :")
        for prix_million, identifiant, nom, contexte, outils, json_ok in deepseek:
            print(f"DEEPSEEK | {identifiant} | {nom} | ${prix_million:.4f}/M tokens | contexte {contexte} | "
                  f"outils {'oui' if outils else 'non'} | json {'oui' if json_ok else 'non'}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tâches planifiées bet_agent")
    sous = parser.add_subparsers(dest="tache", required=True)
    p_run = sous.add_parser("run", help="collecte + coupon(s) + rédaction IA, enregistrés en base")
    p_run.add_argument("--telegram", action="store_true", help="envoie les coupons sur Telegram")
    p_run.add_argument("--sans-redaction", action="store_true", help="n'appelle pas le LLM")
    p_run.add_argument("--si-aucun-ticket-aujourdhui", action="store_true",
                       help="ne fait rien si un run a déjà abouti aujourd'hui (passage de secours)")
    p_run.add_argument("--depuis-run", type=int,
                       help="reprend la collecte archivée de ce run du jour : analyse et IA seulement "
                            "(moteur deterministe uniquement)")
    p_run.add_argument("--moteur", choices=["central", "agent", "deterministe"], default="agent",
                       help="agent = OFFICIEL PAR DÉFAUT depuis le 20/10/2026 (demande explicite : "
                            "l'IA choisit librement les paris, 3 coupons (prudent, équilibré, risque, sans cote imposée), agents spécialistes par "
                            "famille de marchés — voir bet_agent/agents_familles.py) ; "
                            "central = officiel du 11/10 au 20/10/2026 (11/10/2026, moteur le plus récemment "
                            "construit — moteur_central/) : arbitrage par marché bet_agent/moteur "
                            "puis sélection probabilité maximale ; AUCUN repli automatique si ce "
                            "moteur échoue (erreur explicite, run en \"erreur\") ; deterministe = "
                            "officiel du 03/10 au 11/10/2026 (\"diminue le travail de l'IA, seulement "
                            "en rédaction\") : Python choisit seul les paris (UTILISER_STRATEGE_IA="
                            "false, composition Monte Carlo), l'IA ne fait plus que rédiger le texte "
                            "final ; agent = agent pilote DeepSeek autonome (choisit aussi les paris "
                            "lui-même), officiel du 30/09 au 03/10/2026")
    p_run.add_argument("--profils-json", type=str, default="",
                       help="JSON d'une liste de profils personnalisés (run PONCTUEL, 01/10/2026) qui "
                            "remplace ae.PROFILS_COUPON pour CE run uniquement ; vide = comportement par "
                            "défaut (3 profils sûr/équilibré/audacieux) inchangé. Moteur agent uniquement.")
    p_run.add_argument("--ignorer-diversite-croisee", action="store_true",
                       help="désactive la diversité de CATÉGORIE entre profils du même run (traite chaque "
                            "profil comme le premier) ; le refus du pari EXACTEMENT identique reste actif "
                            "dans tous les cas. Moteur agent uniquement.")
    p_verif = sous.add_parser("verifier", help="juge les jambes dont le match est terminé")
    p_verif.add_argument("--telegram", action="store_true", help="envoie le bilan quand tout est jugé")
    p_verif.add_argument("--si-du", action="store_true",
                         help="ne vérifie que si un match est arrivé à l'heure de sa vérification (coup d'envoi + 90 min)")
    p_plan = sous.add_parser("planifier-verification",
                             help="agent IA : planifie l'heure exacte des vérifications et du rapport final")
    p_plan.add_argument("--run-id", type=int, help="run (défaut : dernier run terminé)")
    p_plan.add_argument("--coupons", type=str, default="", help="numéros de coupons séparés par des virgules")
    p_plan.add_argument("--telegram", action="store_true", help="annonce le plan sur Telegram")
    p_plan.add_argument("--sans-ia", action="store_true", help="plan déterministe, sans appel IA")
    p_plan.add_argument("--sans-analyse", action="store_true", help="n'envoie pas l'analyse des coupons après le plan")
    p_live = sous.add_parser("live", help="suivi en direct (API-Football) des jambes en attente, informatif")
    p_live.add_argument("--telegram", action="store_true", help="envoie le rapport en direct sur Telegram")
    p_live.add_argument("--run-id", type=int, help="limite au run (défaut : tous les runs en attente)")
    p_envoi = sous.add_parser("envoyer", help="envoie sur Telegram les coupons déjà calculés d'un run")
    p_envoi.add_argument("--run-id", type=int, help="numéro du run (défaut : dernier run terminé)")
    p_envoi.add_argument("--forcer", action="store_true", help="renvoie même si déjà envoyé")
    p_appr = sous.add_parser("apprendre", help="étudie les erreurs des jours jugés et alimente la mémoire de l'agent")
    p_appr.add_argument("--jour", help="AAAA-MM-JJ : étudie ce jour seulement")
    p_appr.add_argument("--jours", type=int, default=14, help="sinon : étudie les N derniers jours jugés (défaut 14)")
    p_appr.add_argument("--sans-ia", action="store_true", help="leçons déterministes uniquement")
    p_appr.add_argument("--refaire", action="store_true", help="recalcule et remplace les études déjà enregistrées")
    p_appr.add_argument("--apercu", action="store_true", help="avec --jour (liste séparée par des virgules) : affiche ancienne et nouvelle étude, sans rien écrire")
    p_appr.add_argument("--exporter", metavar="FICHIER", help="sauvegarde la mémoire dans ce fichier JSON (lecture seule)")
    p_budget = sous.add_parser("budget", help="dépenses IA mesurées (par jour, par modèle) et budget restant, lecture seule")
    p_budget.add_argument("--jours", type=int, default=7, help="nombre de jours affichés (défaut 7)")
    sous.add_parser("finaliser", help="clôture en « interrompu » un run resté en cours après l'arrêt du job (conserve les coûts, rien n'est envoyé)")
    sous.add_parser("tester-api", help="vérifie l'Edge Function api en ligne (jeton du Vault)")
    sous.add_parser("modeles-gratuits", help="liste les modèles gratuits d'OpenRouter (identifiants exacts)")
    sous.add_parser("tester-ia", help="teste les clés Groq, Gemini et OpenRouter avec une vraie réponse")
    p_backfill = sous.add_parser("backfill", help="télécharge l'historique d'une ligue (API-Football) pour le moteur")
    p_backfill.add_argument("--ligue", type=int, required=True, help="identifiant de ligue API-Football")
    p_backfill.add_argument("--saisons", type=str, required=True, help="saisons séparées par des virgules, ex. 2022,2023,2024")
    p_backfill.add_argument("--sans-stats", action="store_true", help="n'enregistre pas les statistiques détaillées (score seulement)")
    p_backfill.add_argument("--limite-appels-stats", type=int, default=None,
                            help="plafond du nombre de matchs dont on va chercher les statistiques, par saison "
                                 "(budget de quota) ; défaut : sans limite")
    args = parser.parse_args(argv)

    if args.tache == "modeles-gratuits":  # n'a pas besoin de la base
        return tache_modeles_gratuits(args)
    if args.tache == "tester-ia":
        return tache_tester_ia(args)
    if args.tache == "verifier" and args.si_du:
        # Avant init_db : un passage « rien à faire » ne doit ni modifier le schéma ni appeler l'API.
        with SessionLocal() as db:
            due, raison = verification_due(db)
        print(f"{'⏱️ Vérification due' if due else '💤 Rien à vérifier'} — {raison}")
        if not due:
            return 0
    if args.tache != "finaliser":
        # La finalisation ne touche JAMAIS au schéma : après un job annulé, une session zombie peut garder un verrou et un `ALTER TABLE` ferait attendre
        # l'étape jusqu'au délai de la base (07/11/2026 : run 272 resté « en_cours »). Elle doit aussi voir le run encore « en_cours » pour conserver ses coûts.
        init_db()
        with SessionLocal() as db:
            cloturer_runs_interrompus(db)
    taches = {"run": tache_run, "verifier": tache_verifier, "planifier-verification": tache_planifier, "live": tache_live, "envoyer": tache_envoyer,
              "tester-api": tache_tester_api, "backfill": tache_backfill, "apprendre": tache_apprendre, "budget": tache_budget, "finaliser": tache_finaliser}
    return taches[args.tache](args)


if __name__ == "__main__":
    sys.exit(main())
