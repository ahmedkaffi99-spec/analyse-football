"""Statistiques de fin de match (corners, cartons jaunes, fautes, tirs, tirs cadrés) depuis la base `fd_matchs` (Football-Data, 5 championnats) :
repli de vérification quand les statistiques API-Football sont indisponibles (abonnement terminé). Rapprochement par date (±1 jour) et noms
d'équipes (score ≥ 80/100 des DEUX côtés, même orientation domicile/extérieur) ; aucune valeur inventée : None si le match n'est pas (encore) en base."""
from datetime import timedelta

from sqlalchemy import select

from app.models_historique import FdMatch
from app.services import pipeline

COLONNES = {"Corner Kicks": ("HC", "AC"), "Yellow Cards": ("HY", "AY"), "Fouls": ("HF", "AF"),
            "Total Shots": ("HS", "AS"), "Shots on Goal": ("HST", "AST")}
SEUIL = 80


def valeurs(db, domicile, exterieur, coup_envoi, type_stat):
    """(valeur domicile, valeur extérieur) ou None."""
    cols = COLONNES.get(type_stat)
    if not cols or coup_envoi is None:
        return None
    pipeline.modules()                       # met bet_agent dans sys.path
    from noms_equipes import score_noms
    jour = coup_envoi.date()
    meilleur, meilleur_score = None, 0
    q = select(FdMatch).where(FdMatch.date_match >= jour - timedelta(days=1), FdMatch.date_match <= jour + timedelta(days=1))
    for m in db.execute(q).scalars():
        s = min(score_noms(domicile, m.domicile), score_noms(exterieur, m.exterieur))
        if s >= SEUIL and s > meilleur_score and m.stats and cols[0] in m.stats and cols[1] in m.stats:
            meilleur, meilleur_score = m, s
    return None if meilleur is None else (meilleur.stats[cols[0]], meilleur.stats[cols[1]])
