"""Score central d'un candidat : combine UNIQUEMENT les indicateurs réellement disponibles
(demande explicite : "Aucun indicateur ne doit être utilisé s'il n'a pas suffisamment de
données") — un indicateur manquant est omis plutôt que remplacé par une valeur inventée.

Pas de poids appris/optimisé : trop peu de données réelles aujourd'hui pour les valider hors
échantillon (voir moteur/selection.py, même principe) — chaque indicateur disponible compte
pour une part égale, normalisé dans [0, 1]. "Diversité" et "corrélation" ne sont PAS des
composantes du score : ce sont des contraintes structurelles de la sélection (voir selection.py),
jamais un chiffre mélangé au score d'un candidat pris isolément."""

from dataclasses import dataclass, field


@dataclass
class CandidatCentral:
    match: str
    marche: str
    selection: str
    cote: float
    moteur_responsable: str                      # "bet_agent" | "moteur"
    proba_pct: float
    competition: str | None = None
    proba_calibree_pct: float | None = None
    edge_pct: float | None = None
    historique_marche: dict | None = None         # metriques.calculer_metriques() du moteur responsable
    fixture_id_oddspapi: str | None = None
    raisons: list = field(default_factory=list)

    @property
    def cote_juste(self):
        p = (self.proba_calibree_pct or self.proba_pct) / 100
        return round(1 / p, 3) if p else None


def score_central(candidat):
    """(score, détail) — score dans [0, 1], moyenne des indicateurs disponibles. détail liste
    chaque indicateur utilisé ou explicitement marqué indisponible, pour l'audit (jamais une
    boîte noire)."""
    composantes, detail = [], []

    proba = (candidat.proba_calibree_pct or candidat.proba_pct) / 100
    composantes.append(proba)
    detail.append(("probabilite_calibree" if candidat.proba_calibree_pct else "probabilite", round(proba, 4)))

    if candidat.edge_pct is not None:
        composantes.append(min(max(candidat.edge_pct / 20, 0.0), 1.0))  # edge 0-20 % -> 0-1
        detail.append(("edge_pct", candidat.edge_pct))
    else:
        detail.append(("edge_pct", "indisponible"))

    hist = candidat.historique_marche
    if hist and hist.get("disponible"):
        if hist.get("win_rate") is not None:
            composantes.append(hist["win_rate"])
            detail.append(("historique_win_rate", hist["win_rate"]))
        if hist.get("roi") is not None:
            composantes.append(min(max(0.5 + hist["roi"], 0.0), 1.0))  # ROI -50%..+50 % -> 0..1
            detail.append(("historique_roi", hist["roi"]))
        if hist.get("brier") is not None:
            composantes.append(1 - min(hist["brier"], 1.0))  # Brier faible = bonne calibration
            detail.append(("historique_qualite_brier", hist["brier"]))
        detail.append(("historique_n", hist["n"]))
    else:
        detail.append(("historique_marche", "indisponible (échantillon insuffisant)"))

    if not composantes:
        return 0.0, detail
    return round(sum(composantes) / len(composantes), 4), detail
