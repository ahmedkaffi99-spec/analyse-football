"""Alertes Telegram du pipeline quotidien (06/11/2026) : plus d'échec silencieux. Constat de l'audit : 11 jours sur 18 sans coupon, sans un seul
message ; un envoi partiel (2 coupons sur 3) restait inconnu de l'utilisateur.

Règles (jamais plus d'une alerte d'échec par jour, jamais bloquantes) :
- run manuel (hors cron) qui abandonne ou plante : alerte tout de suite ;
- cron : une erreur est signalée tout de suite ; un abandon (collecte vide, aucun coupon défendable) seulement au DERNIER passage de la
  fenêtre (13h27 UTC), car les passages précédents réessaient seuls ;
- cron au dernier passage alors qu'aucun coupon n'est parti aujourd'hui et que le pipeline a été sauté (run encore « en cours ») : alerte ;
- envoi partiel : alerte à chaque fois (le run ne se relance pas seul).
Le marqueur « [ALERTE_ENVOYEE] » est écrit dans runs.detail du run en échec (colonne existante, aucun changement de schéma) ; un fichier
témoin évite le doublon avec l'étape d'alerte du workflow."""
import json
import os
from datetime import datetime, time, timezone
from pathlib import Path

from sqlalchemy import select

from app.models import Run

MARQUEUR = "[ALERTE_ENVOYEE]"
DERNIERE_PASSE_UTC = (13, 27)   # dernier passage du cron du pipeline (heure, minute UTC) — voir pipeline-quotidien.yml
FICHIER_TEMOIN = Path(os.getenv("ALERTE_FICHIER_TEMOIN") or "data/alerte_envoyee.flag")


def lire_journal(run):
    """Journal JSON de l'agent stocké dans runs.detail (« JOURNAL_AGENT {...} »), ou {}."""
    detail = run.detail or ""
    if not detail.startswith("JOURNAL_AGENT "):
        return {}
    try:
        return json.loads(detail[len("JOURNAL_AGENT "):])
    except ValueError:
        return {}


def est_dernier_passage(maintenant):
    return (maintenant.hour, maintenant.minute) >= DERNIERE_PASSE_UTC


def decider(statut, cron, maintenant, deja_alerte, envoi_partiel=None):
    """-> (faut-il alerter, cause)."""
    if envoi_partiel:
        return True, "partiel"
    if statut not in ("abandonne", "erreur", "interrompu") or deja_alerte:
        return False, None
    if not cron:
        return True, statut
    if statut in ("erreur", "interrompu"):
        return True, statut
    return est_dernier_passage(maintenant), statut


def alerte_deja_envoyee(db, maintenant):
    debut = datetime.combine(maintenant.date(), time.min, tzinfo=timezone.utc)
    return db.scalar(select(Run.id).where(Run.lance_le >= debut, Run.detail.like(f"%{MARQUEUR}%")).limit(1)) is not None


def aucun_envoi_aujourdhui(db, maintenant):
    debut = datetime.combine(maintenant.date(), time.min, tzinfo=timezone.utc)
    return db.scalar(select(Run.id).where(Run.source == "api", Run.lance_le >= debut,
                                          Run.envoye_telegram.is_(True)).limit(1)) is None


def _nettoyer(texte, limite=300):
    return " ".join(str(texte or "").replace("_", " ").replace("*", " ").replace("`", " ").split())[:limite]


def _detail_sans_couts(run):
    return (run.detail or "").split(" | COUTS_AGENT", 1)[0]


def message(cause, run):
    if cause == "partiel":
        envoi = lire_journal(run).get("envoi_partiel", "?")
        return (f"⚠️ Envoi Telegram partiel (run {run.id}) : {envoi} message(s) envoyé(s). Le run n'est pas relancé automatiquement pour "
                "éviter des doublons ; vérifiez les coupons reçus.")
    if cause == "erreur" and run.envoye_telegram:
        return (f"⚠️ Pipeline du jour : run {run.id} en erreur APRÈS l'envoi des coupons (enregistrement incomplet en base). Les coupons "
                f"sont bien partis et ne seront pas renvoyés. Détail : {_nettoyer(_detail_sans_couts(run))}")
    if cause == "erreur":
        return f"❌ Pipeline du jour : run {run.id} en erreur, aucun coupon envoyé. Détail : {_nettoyer(_detail_sans_couts(run))}"
    if cause == "interrompu":
        return (f"❌ Pipeline du jour : run {run.id} interrompu (délai ou annulation du job), aucun coupon envoyé. "
                f"Détail : {_nettoyer(_detail_sans_couts(run))}")
    if cause == "relances":
        return ("⚠️ Pipeline du jour : aucun coupon envoyé et les relances payantes sont suspendues (plusieurs échecs avec dépense aujourd'hui). "
                "Aucune nouvelle dépense automatique ; vérifiez GitHub Actions et relancez à la main si besoin.")
    if cause == "bloque":
        return ("⚠️ Pipeline du jour : aucun coupon envoyé à la fin de la fenêtre (un run est resté bloqué ou en cours). "
                "Vérifiez GitHub Actions.")
    return f"⚠️ Pipeline du jour : aucun coupon envoyé (run {run.id} abandonné). Raison : {_nettoyer(_detail_sans_couts(run))}"


def _poser_temoin():
    try:
        FICHIER_TEMOIN.parent.mkdir(parents=True, exist_ok=True)
        FICHIER_TEMOIN.write_text("alerte envoyée", encoding="utf-8")
    except OSError:
        pass


def envoyer_alerte_si_besoin(db, run_id, notifier, cron, maintenant=None):
    """Appelée à la fin de `app.taches run` quand Telegram est actif. Renvoie la cause alertée ou None. Ne lève jamais."""
    maintenant = maintenant or datetime.now(timezone.utc)
    try:
        run = db.get(Run, run_id)
        if run is None:
            return None
        partiel = lire_journal(run).get("envoi_partiel")
        alerter, cause = decider(run.statut, cron, maintenant, alerte_deja_envoyee(db, maintenant), partiel)
        if not alerter:
            return None
        ok = bool(notifier(message(cause, run)))
        if ok:
            _poser_temoin()
            if cause != "partiel":   # le journal JSON d'un run envoyé ne doit pas être altéré
                run.detail = f"{run.detail or ''} {MARQUEUR}".strip()
                db.commit()
        return cause if ok else None
    except Exception as e:
        print(f"⚠️ Alerte Telegram impossible : {str(e)[:150]}")
        return None


def envoyer_alerte_passage_saute(db, notifier, maintenant=None, cause="bloque"):
    """Cron sauté par la garde au dernier passage alors qu'aucun coupon n'est parti aujourd'hui (run « en cours » bloqué)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    try:
        if not est_dernier_passage(maintenant) or alerte_deja_envoyee(db, maintenant) or not aucun_envoi_aujourdhui(db, maintenant):
            return None
        ok = bool(notifier(message(cause, None)))
        if ok:
            _poser_temoin()
            derniere = db.scalar(select(Run).where(Run.source == "api", Run.lance_le >= datetime.combine(
                maintenant.date(), time.min, tzinfo=timezone.utc)).order_by(Run.id.desc()))
            if derniere is not None:
                derniere.detail = f"{derniere.detail or ''} {MARQUEUR}".strip()
                db.commit()
        return cause if ok else None
    except Exception as e:
        print(f"⚠️ Alerte Telegram impossible : {str(e)[:150]}")
        return None


