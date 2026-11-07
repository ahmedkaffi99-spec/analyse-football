"""Budget de dépenses IA par jour (Phase 3, 06/11/2026). Aucune table nouvelle : les coûts de chaque run sont dans son journal
(runs.detail, « JOURNAL_AGENT {...} » avec la clé `couts`, ou « COUTS_AGENT {...} » à la fin du détail d'un run abandonné).
Le plafond vient de BUDGET_JOUR_USD (vide ou « aucun » = pas de plafond ; 0 = aucune dépense IA payante). La journée est le jour UTC,
comme la garde « un ticket par jour »."""
import json
import os
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.models import Run

MARQUEUR_COUTS = "COUTS_AGENT "


def _importer_budget_ia():
    from app.services import pipeline
    pipeline.modules()   # ajoute bet_agent au chemin d'import
    import budget_ia
    return budget_ia


def budget_jour_usd():
    """AUCUN plafond journalier (supprimé le 07/11/2026, demande du propriétaire : c'est lui qui décide de la dépense). BUDGET_JOUR_USD est ignorée. Les coûts restent
    mesurés et enregistrés dans le détail des runs, sans alerte ni blocage."""
    return None


def couts_du_run(run):
    """Bilan des coûts enregistré dans le détail d'un run, ou None."""
    detail = run.detail or ""
    try:
        if detail.startswith("JOURNAL_AGENT "):
            return (json.loads(detail[len("JOURNAL_AGENT "):]).get("couts"))
        if MARQUEUR_COUTS in detail:
            return json.loads(detail.split(MARQUEUR_COUTS, 1)[1].split(" [", 1)[0])
    except ValueError:
        return None
    return None


def texte_couts_pour_detail(couts):
    """Texte à ajouter au détail d'un run abandonné pour ne perdre aucune dépense ; vide si rien à noter."""
    if not couts or not (couts.get("total_usd") or couts.get("alerte")):
        return ""
    return " | " + MARQUEUR_COUTS + json.dumps(couts, ensure_ascii=False, separators=(",", ":"))


def couts_depuis_fichier(donnees):
    """Bilan de coûts minimal à partir de l'état écrit au fil de l'eau par l'agent (COUTS_FICHIER) : {pilote, vote, total_usd}. None si rien.
    Sert quand le run plante ou est tué avant d'avoir construit son journal : la dépense n'est jamais perdue (Phase 4)."""
    if not donnees or not (donnees.get("pilote") or donnees.get("vote")):
        return None
    pilote = donnees.get("pilote") or {}
    vote = donnees.get("vote") or []
    total = round(float(pilote.get("cout_usd") or 0.0) + sum(float(v.get("cout_usd") or 0.0) for v in vote), 4)
    return {"pilote": pilote, "vote": vote, "total_usd": total, "source": "fichier_couts"}


def _debut_du_jour(jour):
    return datetime.combine(jour, time.min, tzinfo=timezone.utc)


def depense_du_jour(db, maintenant=None):
    """Somme des coûts mesurés (en $) des runs lancés aujourd'hui (UTC)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    debut = _debut_du_jour(maintenant.date())
    total = 0.0
    for run in db.scalars(select(Run).where(Run.lance_le >= debut, Run.lance_le < debut + timedelta(days=1))):
        couts = couts_du_run(run)
        if couts:
            total += float(couts.get("total_usd") or 0.0)
    return round(total, 4)


def resume(db, jours=7, maintenant=None):
    """Dépenses des `jours` derniers jours : par jour, par modèle (coût et tokens) et gagnants du vote."""
    maintenant = maintenant or datetime.now(timezone.utc)
    debut = _debut_du_jour(maintenant.date() - timedelta(days=jours - 1))
    par_jour = defaultdict(float)
    par_modele = defaultdict(lambda: {"cout_usd": 0.0, "tokens_entree": 0, "tokens_sortie": 0, "appels": 0, "coupons_retenus": 0})
    for run in db.scalars(select(Run).where(Run.lance_le >= debut)):
        couts = couts_du_run(run)
        if not couts:
            continue
        par_jour[run.lance_le.date().isoformat()] += float(couts.get("total_usd") or 0.0)
        for m in couts.get("vote") or []:
            c = par_modele[m.get("modele") or "?"]
            c["cout_usd"] += float(m.get("cout_usd") or 0.0)
            c["tokens_entree"] += int(m.get("tokens_entree") or 0)
            c["tokens_sortie"] += int(m.get("tokens_sortie") or 0)
            c["appels"] += int(m.get("appels") or 0)
            c["coupons_retenus"] += int(m.get("coupons_retenus") or 0)
    return {"par_jour": {j: round(v, 4) for j, v in sorted(par_jour.items())},
            "par_modele": {m: {**v, "cout_usd": round(v["cout_usd"], 4)} for m, v in sorted(par_modele.items())},
            "depense_aujourdhui_usd": depense_du_jour(db, maintenant)}
