"""Modèles de buts (1 à 7) : une estimation des buts attendus par équipe -> matrice de scores
-> un marché par spécialiste. Chaque spécialiste garde sa propre version et sa propre calibration
(Double Chance est bien calibrée, BTTS non, handicap sur-estimé : un même calcul de base n'implique
pas la même fiabilité selon le marché)."""

from moteur.modeles import lois, marches
from moteur.modeles.catalogue import (BUTS_DOM_DEFAUT, BUTS_EXT_DEFAUT, MIN_MATCHS_LIGUE, MODELES, SELECTIONS)
from moteur.modeles.specialistes.base import ModeleMarche, Prediction


def _retreci(valeurs, prior, k):
    valeurs = [v for v in valeurs if v is not None]
    return (sum(valeurs) + k * prior) / (len(valeurs) + k)


def buts_attendus(features, cfg):
    """(lambda_home, lambda_away, parametres) ou None si l'historique d'une équipe est trop court."""
    home, away, ligue = features["home"], features["away"], features["ligue"]
    if home["n_matchs"] < cfg.min_matchs_equipe or away["n_matchs"] < cfg.min_matchs_equipe:
        return None
    fiable = ligue["n_matchs"] >= MIN_MATCHS_LIGUE and ligue["buts_dom"] and ligue["buts_ext"]
    dom = ligue["buts_dom"] if fiable else BUTS_DOM_DEFAUT
    ext = ligue["buts_ext"] if fiable else BUTS_EXT_DEFAUT
    moy = (dom + ext) / 2
    k = cfg.shrinkage_buts
    att_h = _retreci(home["fenetre_buts_pour"], moy, k) / moy
    def_h = _retreci(home["fenetre_buts_contre"], moy, k) / moy
    att_a = _retreci(away["fenetre_buts_pour"], moy, k) / moy
    def_a = _retreci(away["fenetre_buts_contre"], moy, k) / moy
    lh, la = dom * att_h * def_a, ext * att_a * def_h
    return lh, la, {"lambda_home": round(lh, 3), "lambda_away": round(la, 3), "ligue_fiable": bool(fiable),
                    "buts_dom_ligue": round(dom, 3), "buts_ext_ligue": round(ext, 3)}


def matrice_du_match(ctx):
    """(matrice de scores, paramètres) mémorisés pour le match, ou None."""
    def calcul():
        buts = buts_attendus(ctx.features, ctx.cfg)
        if not buts:
            return None
        lh, la, params = buts
        params = {**params, "rho": ctx.cfg.rho_dixon_coles}
        return lois.matrice_scores(lh, la, ctx.cfg.rho_dixon_coles, ctx.cfg.buts_max), params
    return ctx.memo("matrice_buts", calcul)


class ModeleDeButs(ModeleMarche):
    donnees_requises = ("buts_pour/contre (fenêtre de forme)", "moyennes de la ligue (dom/ext)")

    def __init__(self, numero):
        self.numero = numero
        self.nom, self.marches = MODELES[numero][0], tuple(MODELES[numero][1])

    def predire(self, ctx, lignes):
        base = matrice_du_match(ctx)
        if not base:
            return []
        matrice, params = base
        resultats = []
        for marche in self.marches:
            for ligne in self.lignes_du_marche(lignes, marche):
                for selection in SELECTIONS.get(marche, ["over", "under"]):
                    issues = marches.distribution_buts(matrice, marche, ligne, selection)
                    resultats.append(Prediction(self.numero, self.nom, marche, ligne, selection, issues, params))
        return resultats


class Resultat(ModeleDeButs):
    """Modèle 1 — 1X2."""
    def __init__(self):
        super().__init__(1)


class DoubleChance(ModeleDeButs):
    """Modèle 2 — 1X / X2 / 12. Mesure : P(1X) sur-estimée de 4 à 5 pts quand l'équipe à domicile est
    l'outsider ; sa calibration est donc propre (jamais celle du 1X2)."""
    def __init__(self):
        super().__init__(2)


class Handicap(ModeleDeButs):
    """Modèle 3 — Draw No Bet et handicaps asiatiques (5 issues, remboursement exact)."""
    def __init__(self):
        super().__init__(3)


class ButsTotal(ModeleDeButs):
    """Modèle 4 — total de buts du match."""
    def __init__(self):
        super().__init__(4)


class ButsEquipe1(ModeleDeButs):
    """Modèle 5 — buts de l'équipe à domicile."""
    def __init__(self):
        super().__init__(5)


class ButsEquipe2(ModeleDeButs):
    """Modèle 6 — buts de l'équipe à l'extérieur."""
    def __init__(self):
        super().__init__(6)


class Btts(ModeleDeButs):
    """Modèle 7 — les deux équipes marquent."""
    def __init__(self):
        super().__init__(7)
