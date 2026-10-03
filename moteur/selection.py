"""Filtres, score, corrélation et coupon.

Chaque candidat garde la trace de POURQUOI il est retenu ou rejeté (raisons), pour l'audit.

Score : par défaut la probabilité calibrée, puis l'edge en départage. Aucun poids "inventé"
(proba + edge + historique...) : un score pondéré n'est utilisable qu'après validation hors
échantillon (backtest.tester_seuils compare les variantes).

Corrélation :
- matchs différents : indépendants (hypothèse documentée, la seule dépendance réaliste —
  même équipe — est impossible le même jour) ;
- même match, deux marchés de buts : corrélation EXACTE calculée sur la matrice de scores
  (coefficient phi des deux événements « gagné ») ;
- même match, familles différentes (buts × corners...) : dépendance inconnue => refusée.
"""

import math
from dataclasses import dataclass, field

from moteur.modeles import lois, marches
from moteur.modeles.registre import MODELE_DU_MARCHE


@dataclass
class Candidat:
    match_id: int
    libelle: str
    date: object
    competition: str
    modele: int
    marche: str
    ligne: float | None
    selection: str
    proba_brute: float
    proba: float                 # calibrée si possible
    calibre: bool
    n_calibration: int
    binaire: bool
    cote: float | None
    edge: float | None
    parametres: dict
    raisons_rejet: list = field(default_factory=list)

    @property
    def score(self):
        return (self.proba, self.edge or 0.0)


def filtrer(candidats, cfg):
    retenus = []
    for c in candidats:
        r = []
        if cfg.marches_autorises and c.marche not in cfg.marches_autorises:
            r.append("marché non autorisé")
        if c.marche in cfg.marches_exclus:
            r.append("marché exclu")
        if not c.binaire:
            r.append("marché non binaire (remboursement possible)")
        if c.cote is None:
            r.append("pas de cote")
        elif not cfg.cote_min <= c.cote <= cfg.cote_max:
            r.append(f"cote {c.cote} hors [{cfg.cote_min}, {cfg.cote_max}]")
        if cfg.exiger_calibration and not c.calibre:
            r.append(f"calibration insuffisante ({c.n_calibration} < {cfg.calibration_min_n})")
        if c.proba < cfg.proba_min:
            r.append(f"probabilité {c.proba:.1%} < {cfg.proba_min:.0%}")
        if c.edge is not None and c.edge < cfg.edge_min:
            r.append(f"edge {c.edge:+.1%} < {cfg.edge_min:+.0%}")
        if c.edge is not None and c.edge > cfg.edge_max:
            r.append(f"edge {c.edge:+.1%} > {cfg.edge_max:.0%} (suspect)")
        c.raisons_rejet = r
        if not r:
            retenus.append(c)
    return retenus


def _famille(marche):
    num = MODELE_DU_MARCHE[marche]
    return "buts" if num <= 7 else marche.rsplit("_", 1)[0]


def correlation(a, b):
    """phi entre deux candidats d'un même match ; 1.0 si inconnue (prudence)."""
    if a.match_id != b.match_id:
        return 0.0
    if _famille(a.marche) != "buts" or _famille(b.marche) != "buts":
        return 1.0
    p = a.parametres
    matrice = lois.matrice_scores(p["lambda_home"], p["lambda_away"], p.get("rho", 0.0))
    pa = pb = pab = 0.0
    for h, rangee in enumerate(matrice):
        for x, prob in enumerate(rangee):
            ga = marches.issue_buts(a.marche, a.ligne, a.selection, h, x) == "gagne"
            gb = marches.issue_buts(b.marche, b.ligne, b.selection, h, x) == "gagne"
            pa += prob * ga
            pb += prob * gb
            pab += prob * (ga and gb)
    denom = math.sqrt(pa * (1 - pa) * pb * (1 - pb))
    return (pab - pa * pb) / denom if denom > 1e-12 else 1.0


def composer_coupon(candidats, cfg):
    """Jambes triées par score, une à une, en respectant max_par_match et la corrélation.
    Moins de cfg.coupon_min jambes valables : AUCUN coupon (jamais de remplissage)."""
    jambes, par_match = [], {}
    for c in sorted(candidats, key=lambda c: c.score, reverse=True):
        if len(jambes) >= cfg.coupon_max:
            break
        if par_match.get(c.match_id, 0) >= cfg.max_par_match:
            continue
        if any(o.match_id == c.match_id and (o.marche == c.marche and o.ligne == c.ligne
                                             or abs(correlation(o, c)) > cfg.correlation_max) for o in jambes):
            continue
        jambes.append(c)
        par_match[c.match_id] = par_match.get(c.match_id, 0) + 1
    if len(jambes) < cfg.coupon_min:
        return {"genere": False, "jambes": [],
                "raison": f"Pas assez de sélections fiables : {len(jambes)} < {cfg.coupon_min}. Coupon non généré.",
                "candidats_valables": len(jambes)}
    cote = math.prod(j.cote for j in jambes)
    proba = math.prod(j.proba for j in jambes)  # indépendance entre matchs ; 1 jambe/match par défaut
    return {"genere": True, "jambes": jambes, "cote_totale": round(cote, 2), "proba_combinee": proba,
            "esperance": proba * cote - 1, "raison": None, "candidats_valables": len(jambes)}
