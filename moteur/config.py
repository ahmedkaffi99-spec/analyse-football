"""Seuils et paramètres configurables (variables d'environnement MOTEUR_*), jamais codés en
dur dans la logique. Les valeurs par défaut sont des points de départ prudents : les seuils
définitifs doivent être choisis par le backtest sur une période de validation, puis vérifiés
hors échantillon (voir backtest.tester_seuils)."""

import os
from dataclasses import dataclass, fields


def _env(nom, defaut, type_):
    valeur = os.getenv(f"MOTEUR_{nom.upper()}")
    if valeur in (None, ""):
        return defaut
    if type_ is tuple:
        return tuple(v.strip() for v in valeur.split(",") if v.strip())
    if type_ is bool:
        return valeur.lower() in ("1", "true", "oui", "yes")
    return type_(valeur)


@dataclass(frozen=True)
class Config:
    # Features
    fenetre_forme: int = 10           # matchs pour les moyennes de forme
    shrinkage_buts: float = 5.0       # matchs "fictifs" à la moyenne de la ligue (petits échantillons)
    shrinkage_comptage: float = 5.0
    min_matchs_equipe: int = 5        # en dessous : pas de prédiction (qualité de données)
    min_matchs_stats: int = 5         # pour corners/cartons/tirs (couverture des statistiques)
    # Modèle de buts
    rho_dixon_coles: float = 0.0      # 0 = Poisson indépendant ; à estimer par backtest
    buts_max: int = 10
    # Sélection
    proba_min: float = 0.70
    edge_min: float = 0.0
    edge_max: float = 0.25            # au-delà : suspect (erreur de donnée) plutôt que value
    cote_min: float = 1.15
    cote_max: float = 2.00
    calibration_min_n: int = 100      # prédictions hors échantillon pour faire confiance à la calibration
    exiger_calibration: bool = True
    marches_autorises: tuple = ()     # vide = tous
    marches_exclus: tuple = ()
    # Coupon
    coupon_min: int = 12
    coupon_max: int = 15
    max_par_match: int = 1
    correlation_max: float = 0.30     # |phi| maximal entre deux jambes d'un même match si max_par_match > 1
    # Mises / risque (backtest)
    mise: float = 1.0

    @classmethod
    def depuis_env(cls, **surcharges):
        valeurs = {}
        for f in fields(cls):
            type_ = tuple if isinstance(f.default, tuple) else type(f.default)
            valeurs[f.name] = _env(f.name, f.default, type_)
        valeurs.update(surcharges)
        return cls(**valeurs)
