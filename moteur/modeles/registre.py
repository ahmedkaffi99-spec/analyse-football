"""Les 11 modèles spécialisés.

Modèles 1 à 7 (buts) : UNE estimation des buts attendus par équipe (force d'attaque × faiblesse
défensive adverse, relatives à la moyenne de la compétition, rétrécies vers 1 sur petit
échantillon) -> matrice de scores Poisson/Dixon-Coles -> chaque marché en est dérivé. Chaque
modèle garde sa propre version et sa propre calibration : un même calcul de base n'implique pas
la même fiabilité selon le marché (constaté sur les paris réels : Double Chance bien calibrée,
BTTS non).

Modèles 8 à 11 (corners, cartons, tirs/tirs cadrés, fautes) : loi binomiale négative par équipe
(surdispersion mesurée sur la compétition, à date). Aucune prédiction si la couverture des
statistiques est insuffisante (min_matchs_stats) : jamais de chiffre inventé.

Modèle 11 (fautes) ajouté le 16/10/2026 (demande explicite : "pourquoi tu exclus les marchés
corners/tirs/cartons etc — ajoute chaque marché à un modèle") — moteur_central_run.py exclut
depuis le 15/10/2026 les candidats bet_agent (Poisson, structurellement inadapté à ces marchés
surdispersés) sur TOUS les marchés tirs/corners/cartons/fautes/hors-jeux, mais "fautes" n'avait
jusqu'ici aucun modèle moteur de remplacement : il disparaissait purement et simplement des
coupons, sans substitut. Les fautes ("fouls") sont déjà collectées dans hist_matchs depuis le
backfill du 13/10/2026 (confirmé : 1249/1249 matchs récents avec cette statistique) — ce modèle
réutilise exactement le même calcul générique (comptage_attendu) que corners/cartons/tirs,
aucune logique nouvelle. "Hors-jeux" reste exclu SANS modèle de remplacement : cette statistique
n'est tout simplement pas collectée dans hist_matchs (0/1249 matchs, confirmé par requête
réelle) — ajouter un modèle inventerait une donnée absente, jamais fait ici."""

from moteur.modeles import marches
from moteur.modeles.catalogue import (BUTS_DOM_DEFAUT, BUTS_EXT_DEFAUT, LIGNES_DEFAUT, MIN_MATCHS_LIGUE, MODELE_DU_MARCHE,  # noqa: F401
                                      MODELES, SELECTIONS, VERSION_MODELES)
from moteur.modeles.specialistes import SPECIALISTES, ContexteMatch, Prediction, buts_attendus, comptage_attendu  # noqa: F401

FAMILLES_COMPTAGE = ("corners", "cartons", "tirs", "tirs_cadres", "fautes")


def predire_match(features, cfg, lignes=None, familles_comptage=FAMILLES_COMPTAGE):
    """Toutes les prédictions des 11 spécialistes pour un match. lignes : {marche: [lignes]} (les
    lignes réellement proposées par les cotes) — par défaut LIGNES_DEFAUT. Un spécialiste sans
    données suffisantes ne produit rien (jamais un chiffre inventé)."""
    lignes = {**LIGNES_DEFAUT, **(lignes or {})}
    ctx = ContexteMatch(features, cfg)
    resultats = []
    for specialiste in SPECIALISTES:
        if hasattr(specialiste, "familles"):
            actives = tuple(f for f in specialiste.familles if f in familles_comptage)
            if not actives:
                continue
            resultats.extend(specialiste.predire(ctx, lignes, actives))
        else:
            resultats.extend(specialiste.predire(ctx, lignes))
    return resultats


def issue_reelle(match, marche, ligne, selection):
    """Résultat réel d'une sélection, à partir du score/des statistiques FINALES (backtest et
    vérification). None si la statistique n'existe pas pour ce match."""
    if marche in MODELE_DU_MARCHE and MODELE_DU_MARCHE[marche] <= 7:
        if match.get("home_score") is None:
            return None
        return marches.issue_buts(marche, ligne, selection, match["home_score"], match["away_score"])
    famille, portee = marche.rsplit("_", 1)
    stat = marches.STATS_PAR_FAMILLE[famille]
    stats = match.get("stats") or {}
    vh, va = (stats.get("home") or {}).get(stat), (stats.get("away") or {}).get(stat)
    if vh is None or va is None:
        return None
    valeur = {"total": vh + va, "equipe1": vh, "equipe2": va}[portee]
    return marches.issue_total(valeur, ligne, selection)
