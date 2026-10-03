"""Les 10 modèles spécialisés.

Modèles 1 à 7 (buts) : UNE estimation des buts attendus par équipe (force d'attaque × faiblesse
défensive adverse, relatives à la moyenne de la compétition, rétrécies vers 1 sur petit
échantillon) -> matrice de scores Poisson/Dixon-Coles -> chaque marché en est dérivé. Chaque
modèle garde sa propre version et sa propre calibration : un même calcul de base n'implique pas
la même fiabilité selon le marché (constaté sur les paris réels : Double Chance bien calibrée,
BTTS non).

Modèles 8 à 10 (corners, cartons, tirs/tirs cadrés) : loi binomiale négative par équipe
(surdispersion mesurée sur la compétition, à date). Aucune prédiction si la couverture des
statistiques est insuffisante (min_matchs_stats) : jamais de chiffre inventé.
"""

from dataclasses import dataclass

from moteur.modeles import lois, marches

VERSION_MODELES = "1.0.0"
BUTS_DOM_DEFAUT, BUTS_EXT_DEFAUT = 1.45, 1.15  # compétition sans historique suffisant (< 30 matchs)
MIN_MATCHS_LIGUE = 30

LIGNES_DEFAUT = {
    "handicap": [-2.5, -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5],
    "buts_total": [0.5, 1.5, 2.5, 3.5, 4.5],
    "buts_equipe1": [0.5, 1.5, 2.5],
    "buts_equipe2": [0.5, 1.5, 2.5],
    "corners_total": [7.5, 8.5, 9.5, 10.5, 11.5, 12.5],
    "corners_equipe1": [3.5, 4.5, 5.5, 6.5],
    "corners_equipe2": [2.5, 3.5, 4.5, 5.5],
    "cartons_total": [2.5, 3.5, 4.5, 5.5],
    "cartons_equipe1": [0.5, 1.5, 2.5],
    "cartons_equipe2": [0.5, 1.5, 2.5],
    "tirs_total": [20.5, 22.5, 24.5, 26.5],
    "tirs_equipe1": [9.5, 11.5, 13.5],
    "tirs_equipe2": [7.5, 9.5, 11.5],
    "tirs_cadres_total": [6.5, 7.5, 8.5, 9.5],
    "tirs_cadres_equipe1": [2.5, 3.5, 4.5],
    "tirs_cadres_equipe2": [2.5, 3.5, 4.5],
}

MODELES = {
    1: ("resultat", ["resultat"]),
    2: ("double_chance", ["double_chance"]),
    3: ("handicap", ["dnb", "handicap"]),
    4: ("buts_total", ["buts_total"]),
    5: ("buts_equipe1", ["buts_equipe1"]),
    6: ("buts_equipe2", ["buts_equipe2"]),
    7: ("btts", ["btts"]),
    8: ("corners", ["corners_total", "corners_equipe1", "corners_equipe2"]),
    9: ("cartons", ["cartons_total", "cartons_equipe1", "cartons_equipe2"]),
    10: ("tirs", ["tirs_total", "tirs_equipe1", "tirs_equipe2",
                  "tirs_cadres_total", "tirs_cadres_equipe1", "tirs_cadres_equipe2"]),
}
MODELE_DU_MARCHE = {m: num for num, (_, liste) in MODELES.items() for m in liste}
SELECTIONS = {"resultat": ["1", "X", "2"], "double_chance": ["1X", "X2", "12"], "dnb": ["1", "2"],
              "handicap": ["1", "2"], "btts": ["oui", "non"]}


@dataclass
class Prediction:
    modele: int
    nom_modele: str
    marche: str
    ligne: float | None
    selection: str
    issues: dict
    parametres: dict

    @property
    def probabilite(self):
        """Probabilité de gain plein. Sur un marché non binaire (remboursement/quart possible),
        voir aussi issues et esperance()."""
        return self.issues["gagne"]

    @property
    def binaire(self):
        return marches.est_binaire(self.issues)

    def esperance(self, cote):
        return marches.esperance(self.issues, cote)


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


def comptage_attendu(features, famille, cfg):
    """((dist_home, dist_away), parametres) ou None si couverture des stats insuffisante."""
    stat = marches.STATS_PAR_FAMILLE[famille]
    home, away, ligue = features["home"], features["away"], features["ligue"]
    moy = ligue.get(f"{stat}_par_equipe")
    var = ligue.get(f"{stat}_variance_par_equipe")
    if (moy is None or home["n_matchs_stats"] < cfg.min_matchs_stats or away["n_matchs_stats"] < cfg.min_matchs_stats
            or home[f"{stat}_pour_moy"] is None or away[f"{stat}_pour_moy"] is None):
        return None
    k, n_h, n_a = cfg.shrinkage_comptage, home["n_matchs_stats"], away["n_matchs_stats"]

    def retreci(valeur, n):
        return (valeur * n + k * moy) / (n + k)

    mu_h = (retreci(home[f"{stat}_pour_moy"], n_h) + retreci(away[f"{stat}_contre_moy"], n_a)) / 2
    mu_a = (retreci(away[f"{stat}_pour_moy"], n_a) + retreci(home[f"{stat}_contre_moy"], n_h)) / 2
    if famille == "cartons" and features.get("arbitre_n", 0) >= 5 and features.get("arbitre_cartons_moy"):
        facteur = (features["arbitre_cartons_moy"] / (2 * moy)) ** 0.5  # effet arbitre, volontairement amorti
        mu_h, mu_a = mu_h * facteur, mu_a * facteur
    dispersion = (var / moy) if var and moy else 1.0
    dist_h = lois.distribution(mu_h, mu_h * dispersion if dispersion > 1 else None)
    dist_a = lois.distribution(mu_a, mu_a * dispersion if dispersion > 1 else None)
    return (dist_h, dist_a), {"mu_home": round(mu_h, 3), "mu_away": round(mu_a, 3), "dispersion": round(dispersion, 3)}


def predire_match(features, cfg, lignes=None, familles_comptage=("corners", "cartons", "tirs", "tirs_cadres")):
    """Toutes les prédictions des 10 modèles pour un match. lignes : {marche: [lignes]} (les
    lignes réellement proposées par les cotes) — par défaut LIGNES_DEFAUT."""
    lignes = {**LIGNES_DEFAUT, **(lignes or {})}
    resultats = []
    buts = buts_attendus(features, cfg)
    if buts:
        lh, la, params = buts
        params = {**params, "rho": cfg.rho_dixon_coles}
        matrice = lois.matrice_scores(lh, la, cfg.rho_dixon_coles, cfg.buts_max)
        for num in range(1, 8):
            nom, liste = MODELES[num]
            for marche in liste:
                for ligne in (lignes.get(marche) or [None]):
                    for selection in SELECTIONS.get(marche, ["over", "under"]):
                        issues = marches.distribution_buts(matrice, marche, ligne, selection)
                        resultats.append(Prediction(num, nom, marche, ligne, selection, issues, params))
    for famille in familles_comptage:
        compte = comptage_attendu(features, famille, cfg)
        if not compte:
            continue
        (dist_h, dist_a), params = compte
        num = MODELE_DU_MARCHE[f"{famille}_total"]
        for portee in ("total", "equipe1", "equipe2"):
            marche = f"{famille}_{portee}"
            for ligne in lignes.get(marche, []):
                for selection in ("over", "under"):
                    issues = marches.distribution_comptage(dist_h, dist_a, portee, ligne, selection)
                    resultats.append(Prediction(num, MODELES[num][0], marche, ligne, selection, issues, params))
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
