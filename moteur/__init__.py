"""Moteur d'analyse statistique football : données historiques -> features chronologiques ->
10 modèles -> probabilités -> calibration -> cotes/edge -> filtres -> corrélation -> coupon ->
backtest -> rapport.

Code pur (aucun appel réseau, aucune base) : la collecte et la persistance vivent dans le
backend (backend/app/services/historique.py), qui fournit au moteur des listes de dicts.
Aucune prédiction n'est une garantie : ce sont des probabilités, mesurées par backtest.
"""

VERSION_MOTEUR = "1.0.0"
