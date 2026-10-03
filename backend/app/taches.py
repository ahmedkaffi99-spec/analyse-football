"""Tâches planifiées, lancées par GitHub Actions (ou à la main) — sans serveur :

    python -m app.taches run [--telegram] [--moteur agent|deterministe] [--sans-redaction] \
[--si-aucun-ticket-aujourdhui] [--profils-json JSON] [--ignorer-diversite-croisee]
    python -m app.taches verifier [--telegram]
    python -m app.taches live [--telegram] [--run-id N]
    python -m app.taches envoyer [--run-id N] [--forcer]
    python -m app.taches tester-api

Code de sortie 1 si le run finit en erreur : le workflow GitHub apparaît alors en rouge."""

import argparse
import json
import os
import sys
from datetime import datetime, time, timezone

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Run
from app.services import pipeline
from app.services.bilan import envoyer_bilans
from app.services.runs import cloturer_runs_interrompus, executer_run
from app.services.verification import etat_live_jambes, verifier_coupons_en_attente


def ticket_deja_produit_aujourdhui(db):
    """Les passages planifiés (plusieurs, GitHub pouvant en sauter) ne lancent le pipeline que
    si aucun coupon n'est encore parti sur Telegram aujourd'hui et qu'aucun run n'est en cours.
    Un run manuel sans envoi Telegram ne bloque pas le passage du jour."""
    debut_du_jour = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return db.scalar(select(Run).where(
        Run.source == "api", Run.lance_le >= debut_du_jour,
        (Run.statut == "en_cours") | ((Run.statut == "termine") & Run.envoye_telegram.is_(True)))) is not None


def tache_run(args):
    with SessionLocal() as db:
        if args.si_aucun_ticket_aujourdhui and ticket_deja_produit_aujourdhui(db):
            print("ℹ️ Ticket du jour déjà produit (ou run en cours) — pas de relance.")
            return 0
        run = Run(source="api", statut="en_cours")
        db.add(run)
        db.commit()
        run_id = run.id

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
        return 1 if run.statut == "erreur" else 0


def tache_verifier(args):
    with SessionLocal() as db:
        compte = verifier_coupons_en_attente(db)
        print(f"🔎 Jambes jugées : {dict(compte) or 'aucune (rien en attente ou matchs pas terminés)'}")
        if args.telegram:
            _, ae, _ = pipeline.modules()
            print(f"📤 Bilan(s) Telegram envoyé(s) : {envoyer_bilans(db, ae.notifier_telegram)}")
    return 0


VERDICT_EMOJI = {"gagne": "✅", "perdu": "❌", "push": "➖", "non_verifiable": "❔"}


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
        textes = [c.texte for c in run.coupons if c.texte]
        if not textes:
            print(f"❌ Run {run.id} ({run.statut}) : aucun coupon rédigé à envoyer.")
            return 1
        _, ae, _ = pipeline.modules()
        run.envoye_telegram = bool(ae.agent5_envoyer_coupons(textes))
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
    p_run.add_argument("--moteur", choices=["agent", "deterministe"], default="deterministe",
                       help="deterministe = officiel par défaut (03/10/2026, \"diminue le travail de "
                            "l'IA, seulement en rédaction\") : Python choisit seul les paris "
                            "(UTILISER_STRATEGE_IA=false, composition Monte Carlo), l'IA ne fait plus "
                            "que rédiger le texte final ; agent = agent pilote DeepSeek autonome "
                            "(choisit aussi les paris lui-même), officiel du 30/09 au 03/10/2026")
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
    p_live = sous.add_parser("live", help="suivi en direct (API-Football) des jambes en attente, informatif")
    p_live.add_argument("--telegram", action="store_true", help="envoie le rapport en direct sur Telegram")
    p_live.add_argument("--run-id", type=int, help="limite au run (défaut : tous les runs en attente)")
    p_envoi = sous.add_parser("envoyer", help="envoie sur Telegram les coupons déjà calculés d'un run")
    p_envoi.add_argument("--run-id", type=int, help="numéro du run (défaut : dernier run terminé)")
    p_envoi.add_argument("--forcer", action="store_true", help="renvoie même si déjà envoyé")
    sous.add_parser("tester-api", help="vérifie l'Edge Function api en ligne (jeton du Vault)")
    sous.add_parser("modeles-gratuits", help="liste les modèles gratuits d'OpenRouter (identifiants exacts)")
    sous.add_parser("tester-ia", help="teste les clés Groq, Gemini et OpenRouter avec une vraie réponse")
    args = parser.parse_args(argv)

    if args.tache == "modeles-gratuits":  # n'a pas besoin de la base
        return tache_modeles_gratuits(args)
    if args.tache == "tester-ia":
        return tache_tester_ia(args)
    init_db()
    with SessionLocal() as db:
        cloturer_runs_interrompus(db)
    taches = {"run": tache_run, "verifier": tache_verifier, "live": tache_live, "envoyer": tache_envoyer,
              "tester-api": tache_tester_api}
    return taches[args.tache](args)


if __name__ == "__main__":
    sys.exit(main())
