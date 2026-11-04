import math

import backtest_poids_marche as bp


def test_melange_extremes_et_somme():
    pm, pd = {"1": 0.5, "X": 0.3, "2": 0.2}, {"1": 0.2, "X": 0.3, "2": 0.5}
    assert bp.melanger(pm, pd, 0.0) == pm
    assert bp.melanger(pm, pd, 1.0) == pd
    assert math.isclose(sum(bp.melanger(pm, pd, 0.35).values()), 1.0)


def test_scores_brier_et_logloss():
    brier, ll = bp.scores({"Over": 0.7, "Under": 0.3}, "Over")
    assert math.isclose(brier, 0.3 ** 2 + 0.3 ** 2)
    assert math.isclose(ll, -math.log(0.7))


def test_resume_ecart_a_la_production():
    par_poids = {w: [(0.50, 0.7), (0.60, 0.8), (0.40, 0.6)] for w in bp.POIDS_MODELE}
    par_poids[0.0] = [(0.45, 0.7), (0.58, 0.8), (0.38, 0.6)]     # marché seul un peu meilleur
    lignes = {l[0]: l for l in bp.resume(par_poids)}
    assert lignes[bp.POIDS_PRODUCTION][4] == 0.0
    assert lignes[0.0][4] < 0
