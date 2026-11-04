import math
import random
from datetime import datetime, timedelta

import phase2_modeles as pm


def test_lois_sommes_et_moyennes():
    assert math.isclose(sum(pm.pmf_poisson(1.5, 40)), 1.0, rel_tol=1e-9)
    p = pm.pmf_binomiale_negative(1.5, 20, 60)
    assert math.isclose(sum(p), 1.0, rel_tol=1e-6)
    assert math.isclose(sum(k * v for k, v in enumerate(p)), 1.5, rel_tol=1e-4)
    # variance > moyenne (sur-dispersion) alors que Poisson : variance = moyenne
    var = sum(v * (k - 1.5) ** 2 for k, v in enumerate(p))
    assert var > 1.5 * 1.05


def test_marches_coherents():
    m = pm.matrice(pm.pmf_poisson(1.6), pm.pmf_poisson(1.1))
    p = pm.probas_1x2(m)
    assert math.isclose(sum(p.values()), 1.0)
    assert p["1"] > p["2"]
    assert 0 < pm.proba_over(m, 2.5) < 1
    assert math.isclose(pm.proba_over(m, 2.5) + sum(m[i][j] for i in range(len(m)) for j in range(len(m))
                                                  if i + j < 2.5), 1.0)


def test_dixon_coles_ajuste_les_petits_scores():
    base = pm.matrice(pm.pmf_poisson(1.2), pm.pmf_poisson(1.0))
    dc = pm.matrice_dixon_coles(1.2, 1.0, -0.12)    # rho < 0 : plus de 0-0 et de 1-1, moins de 1-0 / 0-1
    assert dc[0][0] > base[0][0] and dc[1][1] > base[1][1]
    assert dc[1][0] < base[1][0] and dc[0][1] < base[0][1]
    assert math.isclose(sum(sum(l) for l in dc), 1.0)


def test_ajustement_retrouve_les_forces_sur_donnees_synthetiques():
    random.seed(7)
    forces_vraies = {1: 1.8, 2: 1.2, 3: 0.8, 4: 1.0}
    debut = datetime(2024, 1, 1)
    matchs = []
    for jour in range(400):
        d, e = random.sample(list(forces_vraies), 2)
        lam = forces_vraies[d] * 1.0 * 1.25
        mu = forces_vraies[e] * 1.0
        tirer = lambda mu_: next(k for k, c in enumerate(_cumul(pm.pmf_poisson(mu_, 15))) if random.random() <= c)
        matchs.append((debut + timedelta(days=jour // 2), d, e, tirer(lam), tirer(mu)))
    f = pm.ajuster(matchs, debut + timedelta(days=300), xi=0.0)
    ordre = sorted(f.attaque, key=f.attaque.get, reverse=True)
    assert ordre[0] == 1 and ordre[-1] == 3          # équipe 1 la plus forte, équipe 3 la plus faible
    assert 1.0 < f.gamma < 1.6                        # avantage du terrain ~1,25


def _cumul(pmf):
    c, out = 0.0, []
    for p in pmf:
        c += p
        out.append(c)
    return out


def test_sans_marge_et_melange():
    p = pm.sans_marge({"1": 2.0, "X": 3.4, "2": 4.0})
    assert math.isclose(sum(p.values()), 1.0)
    assert pm.sans_marge({"1": 2.0, "X": None}) is None
    q = {"1": 0.2, "X": 0.3, "2": 0.5}
    assert pm.melanger(p, q, 0.0) == p and pm.melanger(p, q, 1.0) == q


def test_metriques_et_clv():
    assert math.isclose(pm.brier({"a": 0.7, "b": 0.3}, "a"), 0.18)
    assert math.isclose(pm.log_loss({"a": 0.5, "b": 0.5}, "a"), math.log(2))
    lignes, ece = pm.table_calibration([(0.1, 0), (0.1, 0), (0.9, 1), (0.9, 1)], 10)
    assert len(lignes) == 2 and ece < 0.11
    assert pm.clv_pct(2.2, 0.5) > 0 > pm.clv_pct(1.9, 0.5)
