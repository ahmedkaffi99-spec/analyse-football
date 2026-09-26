"""Tâches planifiées, lancées par GitHub Actions (ou à la main) — sans serveur :

    python -m app.taches run [--telegram] [--sans-redaction] [--si-aucun-ticket-aujourdhui]
    python -m app.taches verifier [--telegram]
    python -m app.taches envoyer [--run-id N] [--forcer]
    python -m app.taches tester-api

Code de sortie 1 si le run finit en erreur : le workflow GitHub apparaît alors en rouge."""

import argparse
import sys
from datetime import datetime, time, timezone

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Run
from app.services import pipeline
from app.services.bilan import envoyer_bilans
from app.services.runs import cloturer_runs_interrompus, executer_run
from app.services.verification import verifier_coupons_en_attente


def ticket_deja_produit_aujourdhui(db):
    """Même rôle que relancer_si_echec.py : le 2e passage ne relance le pipeline que si le
    premier n'a produit aucun ticket aujourd'hui (erreur réseau, abandon...)."""
    debut_du_jour = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return db.scalar(select(Run).where(Run.source == "api", Run.lance_le >= debut_du_jour,
                                       Run.statut.in_(("termine", "en_cours")))) is not None


def tache_run(args):
    with SessionLocal() as db:
        if args.si_aucun_ticket_aujourdhui and ticket_deja_produit_aujourdhui(db):
            print("ℹ️ Ticket du jour déjà produit (ou run en cours) — pas de relance.")
            return 0
        run = Run(source="api", statut="en_cours")
        db.add(run)
        db.commit()
        run_id = run.id

    print(f"🚀 Run {run_id} — Telegram : {'oui' if args.telegram else 'non'}")
    executer_run(run_id, envoyer_telegram=args.telegram, rediger=not args.sans_redaction)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        print(f"🏁 Run {run_id} : {run.statut}" + (f" — {run.detail}" if run.detail else ""))
        for c in run.coupons:
            print(f"   {c.nom} : {len(c.jambes)} jambe(s), cote {c.cote_totale}")
        return 1 if run.statut == "erreur" else 0


def tache_verifier(args):
    with SessionLocal() as db:
        compte = verifier_coupons_en_attente(db)
        print(f"🔎 Jambes jugées : {dict(compte) or 'aucune (rien en attente ou matchs pas terminés)'}")
        if args.telegram:
            _, ae, _ = pipeline.modules()
            print(f"📤 Bilan(s) Telegram envoyé(s) : {envoyer_bilans(db, ae.notifier_telegram)}")
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
        textes = [c.texte for c in run.coupons if c.texte]
        if not textes:
            print(f"❌ Run {run.id} ({run.statut}) : aucun coupon rédigé à envoyer.")
            return 1
        _, ae, _ = pipeline.modules()
        run.envoye_telegram = bool(ae.agent5_envoyer_trois_coupons(textes))
        db.commit()
        print(f"{'✅' if run.envoye_telegram else '❌'} Run {run.id} : {len(textes)} coupon(s) "
              f"{'envoyé(s)' if run.envoye_telegram else 'non envoyé(s) — voir erreur Telegram ci-dessus'}")
        return 0 if run.envoye_telegram else 1


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


def tache_modeles_gratuits(args, requetes=None):
    """Liste les modèles GRATUITS d'OpenRouter (identifiant exact, contexte, prise en charge des
    outils et du JSON) — pour choisir OPENROUTER_MODELES sans deviner les identifiants."""
    import requests

    requetes = requetes or requests
    r = requetes.get("https://openrouter.ai/api/v1/models", timeout=30)
    r.raise_for_status()
    modeles = []
    for m in r.json().get("data", []):
        tarif = m.get("pricing") or {}
        gratuit = str(m.get("id", "")).endswith(":free") or (
            str(tarif.get("prompt")) in ("0", "0.0") and str(tarif.get("completion")) in ("0", "0.0"))
        sortie = (m.get("architecture") or {}).get("output_modalities") or ["text"]
        if gratuit and "text" in sortie:
            parametres = m.get("supported_parameters") or []
            modeles.append((m["id"], m.get("name", ""), m.get("context_length") or 0,
                            "tools" in parametres, "response_format" in parametres or "structured_outputs" in parametres))
    modeles.sort(key=lambda x: -x[2])
    print(f"{len(modeles)} modèle(s) texte gratuit(s) sur OpenRouter :")
    for identifiant, nom, contexte, outils, json_ok in modeles:
        print(f"MODELE | {identifiant} | {nom} | contexte {contexte} | outils {'oui' if outils else 'non'} "
              f"| json {'oui' if json_ok else 'non'}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tâches planifiées bet_agent")
    sous = parser.add_subparsers(dest="tache", required=True)
    p_run = sous.add_parser("run", help="collecte + 3 coupons + rédaction IA, enregistrés en base")
    p_run.add_argument("--telegram", action="store_true", help="envoie les coupons sur Telegram")
    p_run.add_argument("--sans-redaction", action="store_true", help="n'appelle pas le LLM")
    p_run.add_argument("--si-aucun-ticket-aujourdhui", action="store_true",
                       help="ne fait rien si un run a déjà abouti aujourd'hui (passage de secours)")
    p_verif = sous.add_parser("verifier", help="juge les jambes dont le match est terminé")
    p_verif.add_argument("--telegram", action="store_true", help="envoie le bilan quand tout est jugé")
    p_envoi = sous.add_parser("envoyer", help="envoie sur Telegram les coupons déjà calculés d'un run")
    p_envoi.add_argument("--run-id", type=int, help="numéro du run (défaut : dernier run terminé)")
    p_envoi.add_argument("--forcer", action="store_true", help="renvoie même si déjà envoyé")
    sous.add_parser("tester-api", help="vérifie l'Edge Function api en ligne (jeton du Vault)")
    sous.add_parser("modeles-gratuits", help="liste les modèles gratuits d'OpenRouter (identifiants exacts)")
    args = parser.parse_args(argv)

    if args.tache == "modeles-gratuits":  # n'a pas besoin de la base
        return tache_modeles_gratuits(args)
    init_db()
    with SessionLocal() as db:
        cloturer_runs_interrompus(db)
    taches = {"run": tache_run, "verifier": tache_verifier, "envoyer": tache_envoyer,
              "tester-api": tache_tester_api}
    return taches[args.tache](args)


if __name__ == "__main__":
    sys.exit(main())
