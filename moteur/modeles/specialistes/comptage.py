"""Modèles de comptage (8 à 11) : corners, cartons jaunes, tirs / tirs cadrés, fautes.

Loi par équipe (Poisson, ou binomiale négative si la surdispersion est mesurée), convolution pour
le total. Aucune prédiction si la couverture des statistiques est insuffisante (min_matchs_stats).
"""

from moteur.modeles import lois, marches
from moteur.modeles.catalogue import MODELE_DU_MARCHE, MODELES
from moteur.modeles.specialistes.base import ModeleMarche, Prediction


def comptage_attendu(features, famille, cfg):
    """((dist_home, dist_away), parametres) ou None si couverture des stats insuffisante."""
    stat = marches.STATS_PAR_FAMILLE[famille]
    home, away, ligue = features["home"], features["away"], features["ligue"]
    moy = ligue.get(f"{stat}_par_equipe")
    var = ligue.get(f"{stat}_variance_par_equipe")
    if (moy is None or home["n_matchs_stats"] < cfg.min_matchs_stats or away["n_matchs_stats"] < cfg.min_matchs_stats
            or home[f"{stat}_pour_moy"] is None or away[f"{stat}_pour_moy"] is None):
        return None
    k, n_h, n_a = getattr(cfg, f"shrinkage_comptage_{famille}"), home["n_matchs_stats"], away["n_matchs_stats"]

    def retreci(valeur, n):
        return (valeur * n + k * moy) / (n + k)

    mu_h = (retreci(home[f"{stat}_pour_moy"], n_h) + retreci(away[f"{stat}_contre_moy"], n_a)) / 2
    mu_a = (retreci(away[f"{stat}_pour_moy"], n_a) + retreci(home[f"{stat}_contre_moy"], n_h)) / 2
    if famille == "cartons" and features.get("arbitre_n", 0) >= 5 and features.get("arbitre_cartons_moy"):
        facteur = (features["arbitre_cartons_moy"] / (2 * moy)) ** 0.5  # effet arbitre, volontairement amorti
        mu_h, mu_a = mu_h * facteur, mu_a * facteur
    mesuree = getattr(cfg, f"dispersion_{famille}", 0.0)
    dispersion = mesuree if mesuree else ((var / moy) if var and moy else 1.0)
    dist_h = lois.distribution(mu_h, mu_h * dispersion if dispersion > 1 else None)
    dist_a = lois.distribution(mu_a, mu_a * dispersion if dispersion > 1 else None)
    return (dist_h, dist_a), {"mu_home": round(mu_h, 3), "mu_away": round(mu_a, 3), "dispersion": round(dispersion, 3)}


class ModeleDeComptage(ModeleMarche):
    familles: tuple = ()

    def __init__(self):
        self.nom = MODELES[self.numero][0]
        self.marches = tuple(MODELES[self.numero][1])

    def predire(self, ctx, lignes, familles=None):
        resultats = []
        for famille in (familles or self.familles):
            compte = ctx.memo(("comptage", famille), lambda f=famille: comptage_attendu(ctx.features, f, ctx.cfg))
            if not compte:
                continue
            (dist_h, dist_a), params = compte
            for portee in ("total", "equipe1", "equipe2"):
                marche = f"{famille}_{portee}"
                for ligne in lignes.get(marche, []):
                    for selection in ("over", "under"):
                        issues = marches.distribution_comptage(dist_h, dist_a, portee, ligne, selection)
                        resultats.append(Prediction(MODELE_DU_MARCHE[marche], self.nom, marche, ligne, selection,
                                                    issues, params))
        return resultats


class Corners(ModeleDeComptage):
    """Modèle 8 — corners (binomiale négative, dispersion mesurée 1.16)."""
    numero, familles = 8, ("corners",)
    donnees_requises = ("corners pour/contre par équipe (fenêtre)", "moyenne de la ligue")


class Cartons(ModeleDeComptage):
    """Modèle 9 — cartons jaunes (Poisson, dispersion mesurée 1.0 ; effet arbitre amorti, n >= 5)."""
    numero, familles = 9, ("cartons",)
    donnees_requises = ("cartons jaunes pour/contre", "arbitre (cartons moyens, n >= 5)")


class Tirs(ModeleDeComptage):
    """Modèle 10 — tirs et tirs cadrés (binomiale négative, dispersion mesurée 1.35 / 1.12)."""
    numero, familles = 10, ("tirs", "tirs_cadres")
    donnees_requises = ("tirs et tirs cadrés pour/contre", "moyenne de la ligue")


class Fautes(ModeleDeComptage):
    """Modèle 11 — fautes (binomiale négative, dispersion mesurée 1.22)."""
    numero, familles = 11, ("fautes",)
    donnees_requises = ("fautes pour/contre", "moyenne de la ligue")
