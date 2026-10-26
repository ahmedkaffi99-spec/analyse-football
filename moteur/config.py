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
    shrinkage_buts: float = 30.0      # matchs "fictifs" à la moyenne de la ligue (petits échantillons) —
    # valeur validée par backtest réel walk-forward (16/10/2026, Premier League, marché buts_total/
    # buts_equipe1/2 sur les matchs Newcastle/Aston Villa) : Brier décroissant de k=3 (0.2165) à
    # k=30 (0.2085, meilleur), remontant à k=50 (0.2088) — 5.0 (ancienne valeur, jamais backtestée)
    # sous-pondérait largement la moyenne de ligue par rapport à la forme récente.
    # Un seul shrinkage_comptage partagé par les 5 familles jusqu'au 17/10/2026 — backtest réel
    # walk-forward (La Liga, Real Betis/Barcelona) a montré que 4 familles sur 5 préfèrent un k
    # BIEN PLUS BAS que 5 (moins de poids sur la moyenne de ligue, plus sur la forme récente),
    # sauf les cartons (dépendent davantage de l'arbitre/de la rivalité, déjà gérés par un
    # facteur arbitre à part — voir comptage_attendu) qui préfèrent un k plus haut. Un seul
    # champ partagé ne pouvait être bon pour aucune des 5 — remplacé par un champ par famille.
    shrinkage_comptage_corners: float = 3.0       # Brier 0.2353 à k=3 (vs 0.2382 à k=30)
    shrinkage_comptage_cartons: float = 10.0      # Brier 0.2267 à k=10 (vs 0.2278 à k=3)
    shrinkage_comptage_tirs: float = 3.0          # Brier 0.218 à k=3 (vs 0.2292 à k=30)
    shrinkage_comptage_tirs_cadres: float = 3.0   # Brier 0.224 à k=3 (vs 0.2336 à k=30)
    shrinkage_comptage_fautes: float = 3.0        # Brier 0.2075 à k=3 (vs 0.2142 à k=30)
    # Dispersion CONDITIONNELLE des comptages (variance résiduelle / mu autour du mu prédit), mesurée le
    # 21/10/2026 sur 6 996 matchs (walk-forward, 5 championnats) : corners 1.16, tirs 1.35, tirs cadrés
    # 1.12, fautes 1.22, cartons 1.01. 0 = ancien comportement (rapport variance/moyenne PAR ÉQUIPE de la
    # ligue, qui mêle l'hétérogénéité entre équipes à la vraie variance de tirage).
    dispersion_corners: float = 1.16
    dispersion_cartons: float = 1.0
    dispersion_tirs: float = 1.35
    dispersion_tirs_cadres: float = 1.12
    dispersion_fautes: float = 1.22
    min_matchs_equipe: int = 5        # en dessous : pas de prédiction (qualité de données)
    min_matchs_stats: int = 5         # pour corners/cartons/tirs (couverture des statistiques)
    # Modèle de buts
    rho_dixon_coles: float = 0.0      # 0 = Poisson indépendant ; à estimer par backtest
    buts_max: int = 10
    # Sélection
    proba_min: float = 0.0             # plancher supprimé (16/10/2026, demande explicite) —
    # 0.70 ignorait tout candidat valable à edge positif mais proba < 70% (voir moteur/
    # selection.py:filtrer) ; sans ce plancher, edge_min/edge_max restent les seuls filtres
    # de rentabilité, proba_min ne sert plus qu'à exclure une proba strictement négative
    # (jamais possible en pratique, 0.0 est donc un no-op assumé).
    edge_min: float = 0.0
    edge_max: float = 0.20            # au-delà : suspect (erreur de donnée) plutôt que value —
    # abaissé de 0.25 à 0.20 (16/10/2026, demande explicite)
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
