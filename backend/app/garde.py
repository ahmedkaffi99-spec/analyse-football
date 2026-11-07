"""Garde du pipeline quotidien — module LÉGER (SQLAlchemy + modèles seulement), importable sans les dépendances IA (Phase 3, 06/11/2026).

Sert à deux endroits, avec LA MÊME logique :
- `python -m app.taches run --si-aucun-ticket-aujourdhui` (garde historique, toujours active : protection contre les doubles envois) ;
- `python backend/app/garde.py` : première étape du workflow, avant d'installer les dépendances lourdes du job `run`. Quand un coupon est déjà
  parti aujourd'hui, le job `run` entier (checkout, Python, pip, pipeline) est sauté : les ~20 passages inutiles du cron ne coûtent plus rien.
Sécurité : en cas de doute (base injoignable, erreur), la garde dit « passer = oui » et le job `run` refait sa propre vérification."""
import os
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))   # lancé comme script : `app` doit être importable

from sqlalchemy import select  # noqa: E402

from app import config  # noqa: E402
from app.models import Match, Run  # noqa: E402


def cloturer_runs_interrompus(db, maintenant=None):
    """Un run resté "en_cours" plus de HEURES_MAX_RUN heures a été tué (délai du job GitHub,
    coupure réseau...) : il est clôturé en erreur, sinon il bloquerait pour toujours les
    nouveaux runs (409) et le passage de secours ("ticket déjà en cours")."""
    maintenant = maintenant or datetime.now(timezone.utc)
    limite = maintenant - timedelta(hours=config.HEURES_MAX_RUN)
    clotures = 0
    for run in db.scalars(select(Run).where(Run.statut == "en_cours")):
        lance_le = run.lance_le if run.lance_le.tzinfo else run.lance_le.replace(tzinfo=timezone.utc)
        if lance_le < limite:
            run.statut = "erreur"
            run.detail = f"Interrompu : toujours en cours après {config.HEURES_MAX_RUN:g} h (job arrêté ou coupure)."
            run.termine_le = maintenant
            clotures += 1
    if clotures:
        db.commit()
        print(f"🧹 {clotures} run(s) interrompu(s) clôturé(s) en erreur.")
    return clotures


def ticket_deja_produit_aujourdhui(db):
    """Les passages planifiés (plusieurs, GitHub pouvant en sauter) ne lancent le pipeline que
    si aucun coupon n'est encore parti sur Telegram aujourd'hui (run terminé, en erreur ou abandonné après l'envoi) et qu'aucun run n'est en cours.
    Un run manuel sans envoi Telegram ne bloque pas le passage du jour."""
    aujourd_hui = datetime.now(timezone.utc).date()
    debut_du_jour = datetime.combine(aujourd_hui, time.min, tzinfo=timezone.utc)
    if db.scalar(select(Run).where(
            Run.source == "api", Run.lance_le >= debut_du_jour,
            # envoyé = envoyé, QUEL QUE SOIT le statut final (06/11/2026) : un run en « erreur » ou « abandonné » après l'envoi
            # (persistance plantée, envoi partiel) ne doit jamais déclencher un second envoi au passage suivant.
            (Run.statut == "en_cours") | Run.envoye_telegram.is_(True))) is not None:
        return True
    # Coupons préparés ET envoyés la veille pour les matchs d'AUJOURD'HUI (ex. utilisateur en voyage) : le jour est couvert,
    # pas de second envoi. Seuls comptent les runs terminés et envoyés dont des matchs ont leur coup d'envoi aujourd'hui.
    debut_veille = datetime.combine(aujourd_hui, time.min, tzinfo=timezone.utc) - timedelta(days=2)
    fin_du_jour = debut_du_jour + timedelta(days=1)
    return db.scalar(
        select(Run.id).join(Match, Match.run_id == Run.id).where(
            Run.source == "api", Run.envoye_telegram.is_(True),
            Run.lance_le >= debut_veille, Run.lance_le < debut_du_jour,
            Match.coup_envoi >= debut_du_jour, Match.coup_envoi < fin_du_jour).limit(1)) is not None


def decision_passage(db, maintenant=None):
    """Décision du passage planifié -> (lancer le job `run`, raison). Le job `run` n'est sauté que si TOUT est réglé aujourd'hui :
    un coupon est parti (ou couvre la journée) ET ce n'est pas le cas « dernier passage de la fenêtre, run encore en cours, rien envoyé »
    (le job `run` doit alors s'exécuter pour envoyer l'alerte « run bloqué »)."""
    from app.services import alertes
    maintenant = maintenant or datetime.now(timezone.utc)
    cloturer_runs_interrompus(db, maintenant)   # sinon un run tué resterait « en cours » et bloquerait la journée
    if not ticket_deja_produit_aujourdhui(db):
        return True, "aucun coupon aujourd'hui : le pipeline doit tourner"
    if alertes.est_dernier_passage(maintenant) and alertes.aucun_envoi_aujourdhui(db, maintenant):
        return True, "dernier passage sans coupon envoyé (run bloqué ?) : le job doit signaler le problème"
    return False, "coupons du jour déjà envoyés (ou jour couvert) : aucun travail"


def main():
    sortie = os.environ.get("GITHUB_OUTPUT")
    lancer, raison = True, "garde indisponible : par prudence le job `run` décidera"
    try:
        from app.database import SessionLocal
        with SessionLocal() as db:
            lancer, raison = decision_passage(db)
    except Exception as e:   # jamais bloquant : le job `run` a sa propre garde
        raison = f"garde indisponible ({type(e).__name__}) : par prudence le job `run` décidera"
    print(("▶️ " if lancer else "⏭️ ") + raison)
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"passer={'true' if lancer else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
