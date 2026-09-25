"""Tâches planifiées, lancées par GitHub Actions (ou à la main) — sans serveur :

    python -m app.taches run [--telegram] [--sans-redaction] [--si-aucun-ticket-aujourdhui]
    python -m app.taches verifier [--telegram]

Code de sortie 1 si le run finit en erreur : le workflow GitHub apparaît alors en rouge."""

import argparse
import sys
from datetime import datetime, time, timezone

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Run
from app.services import pipeline
from app.services.bilan import envoyer_bilans
from app.services.runs import executer_run
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
    args = parser.parse_args(argv)

    init_db()
    return tache_run(args) if args.tache == "run" else tache_verifier(args)


if __name__ == "__main__":
    sys.exit(main())
