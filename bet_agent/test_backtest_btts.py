"""Backtest BTTS : exécution sur un championnat simulé, régression logistique et absence de fuite."""

import math

import pytest

import backtest_btts as bb
from moteur.tests.simulation import championnat


@pytest.fixture(scope="module")
def echantillons():
    matchs, _ = championnat(n_equipes=16, saisons=(2022, 2023, 2024, 2025))
    return bb.construire_echantillons({1: matchs})


def test_echantillons_tries_et_bien_formes(echantillons):
    assert len(echantillons) > 500
    assert all(a["t"] <= b["t"] for a, b in zip(echantillons, echantillons[1:]))
    assert all(set(e["f"]) == set(bb.NOMS_FEATURES_ETENDUES) and e["y"] in (0, 1) for e in echantillons)
    assert all(0 <= e["f"]["btts_dom"] <= 1 and 0 < e["p_pois"] < 1 for e in echantillons)


def test_toutes_les_variantes_sont_evaluees_sur_les_memes_matchs(echantillons):
    sorties = bb.predictions_walk_forward(echantillons)
    assert len(sorties) == 9
    tailles = {len(v) for v in sorties.values()}
    assert len(tailles) == 1 and tailles.pop() > 200
    for pts in sorties.values():
        assert all(0.0 <= p <= 1.0 and y in (0, 1) for p, y in pts)


def test_poisson_calibre_sur_donnees_poisson_et_logistique_ne_degrade_pas(echantillons):
    # les données simulées SONT Poisson indépendant : le Poisson est le bon modèle, la logistique ne doit pas
    # faire sensiblement pire (pas de sur-apprentissage grossier) et le taux de ligue est le plancher
    sorties = bb.predictions_walk_forward(echantillons)
    b = {k: bb.metriques(v)["brier"] for k, v in sorties.items()}
    assert b["V1 Poisson (production)"] < b["V0 taux de ligue"]
    assert b["V5 régression logistique"] < b["V1 Poisson (production)"] + 0.01
    assert b["V6 logistique étendue (lieu, tirs cadrés, Elo, ligue)"] < b["V0 taux de ligue"] + 0.01


def test_regression_logistique_retrouve_une_relation_connue():
    import random
    rng = random.Random(7)
    X = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(1500)]
    y = [1 if rng.random() < 1 / (1 + math.exp(-(1.5 * x[0] - 0.5 * x[1]))) else 0 for x in X]
    m = bb.entrainer_logistique(X, y, l2=0.1, iterations=200)
    assert bb.predire_logistique(m, [2.0, 0.0]) > 0.85 and bb.predire_logistique(m, [-2.0, 0.0]) < 0.15


def test_metriques_et_cote_probable():
    m = bb.metriques([(0.8, 1)] * 8 + [(0.8, 0)] * 2 + [(0.3, 0)] * 10)
    assert m["n"] == 20
    n, reel, annonce = m["seuils"][0.70]
    assert n == 20 and abs(reel - 0.9) < 1e-9 and abs(annonce - 0.75) < 1e-9     # (0.8 x10 et 0.7 x10)
