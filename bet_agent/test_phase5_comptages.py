import math
import random
from datetime import date, timedelta

import phase5_comptages as p5


def jeu(n=1500, seed=5):
    rng = random.Random(seed)
    equipes = {f"T{i}": 4.0 + 0.7 * i for i in range(10)}      # corners attendus par équipe (force croissante)
    d0, out = date(2020, 8, 1), []
    for i in range(n):
        h, a = rng.sample(list(equipes), 2)
        poisson = lambda mu: next(k for k in range(60) if rng.random() < 1 - math.exp(-mu) * sum(mu ** j / math.factorial(j) for j in range(k + 1)) + 1e-12 or k == 59)
        out.append((d0 + timedelta(days=i // 4), "E0", h, a, {"HC": poisson(equipes[h]), "AC": poisson(equipes[a] * 0.9)}))
    return out


def test_convolution_et_over():
    c = p5.convolution([0.5, 0.5], [0.5, 0.5])
    assert math.isclose(sum(c), 1.0) and math.isclose(c[1], 0.5)
    assert math.isclose(p5.proba_over_total(c, 0.5), 0.75)


def test_walk_forward_probabilites_valides_et_pas_de_fuite():
    m = jeu()
    evts = p5.walk_forward(m, "corners", m[0][0] + timedelta(days=200))
    assert evts and all(0 < e["p_nb"] < 1 and 0 < e["p_poisson"] < 1 and 0 < e["p_naif"] < 1 for e in evts)
    debut = m[0][0] + timedelta(days=200)
    futur_modifie = [(d, lg, h, a, {"HC": 99, "AC": 99}) if d > debut + timedelta(days=3) else (d, lg, h, a, s) for d, lg, h, a, s in m]
    e1 = [e for e in p5.walk_forward(m, "corners", debut)][:8]
    e2 = [e for e in p5.walk_forward(futur_modifie, "corners", debut)][:8]
    assert [round(x["p_nb"], 9) for x in e1] == [round(x["p_nb"], 9) for x in e2]     # les premiers tests ne voient pas le futur


def test_le_modele_par_equipe_bat_la_reference_naive_quand_les_equipes_different():
    m = jeu(2500)
    evts = p5.walk_forward(m, "corners", m[0][0] + timedelta(days=300))
    txt = "\n".join(p5.rapport_stat(evts))
    assert "Poisson par équipe" in txt and "dispersion moyenne" in txt
    brn = sum(p5.brier_bin(e["p_naif"], e["issue"]) for e in evts)
    brp = sum(p5.brier_bin(e["p_poisson"], e["issue"]) for e in evts)
    assert brp < brn
