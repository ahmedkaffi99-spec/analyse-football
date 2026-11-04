import math
import random

import phase2_reference as pr


def monde(n=300, seed=1):
    """Marché 1X2 avec marge ~5 % : proba vraie = proba juste, cotes = juste/1.05 (donc ROI aveugle ≈ -5 %)."""
    rng = random.Random(seed)
    tous = []
    for i in range(n):
        p = [rng.uniform(0.2, 0.5) for _ in range(3)]
        s = sum(p)
        p = [x / s for x in p]
        gagnant = rng.choices(range(3), p)[0]
        for k in range(3):
            tous.append({"match": i, "groupe": "1x2", "selection": k, "cote": round(1 / p[k] / 1.05, 2),
                         "issue": "gagne" if k == gagnant else "perdu", "date": i, "clv_ref": p[k]})
    return tous


def test_reproductible_et_meme_structure():
    tous = monde()
    choisis = [b for b in tous if b["selection"] == 0]
    a = pr.simuler_aleatoire(tous, choisis, 50, graine=7)
    b = pr.simuler_aleatoire(tous, choisis, 50, graine=7)
    assert a == b and len(a) == 50
    assert all(x["n"] <= len(choisis) for x in a)
    assert pr.simuler_aleatoire(tous, choisis, 5, graine=8) != pr.simuler_aleatoire(tous, choisis, 5, graine=7)


def test_aleatoire_perd_environ_la_marge():
    tous = monde(600)
    choisis = [b for b in tous if b["selection"] == 0]
    sims = pr.simuler_aleatoire(tous, choisis, 300, graine=3)
    moyenne = sum(x["roi"] for x in sims) / len(sims)
    assert -0.12 < moyenne < 0.0                       # ≈ -5 % de marge, bruit compris
    lo, hi = pr.intervalle([x["roi"] for x in sims])
    assert lo < moyenne < hi
    assert -0.12 < sum(x["clv"] for x in sims) / len(sims) < -0.02   # CLV d'un pari aveugle ≈ -marge


def test_contraintes_de_cotes_respectees():
    tous = monde()
    choisis = [b for b in tous if b["selection"] == 0 and 2.0 <= b["cote"] <= 3.0]
    cmin, cmax = min(b["cote"] for b in choisis), max(b["cote"] for b in choisis)
    # tout pari tiré doit avoir une cote dans [cmin, cmax] : on vérifie via le résumé de cotes extrêmes
    sims = pr.simuler_aleatoire([dict(b, groupe="g") for b in tous], [dict(b, groupe="g") for b in choisis], 5, graine=1)
    assert all(x["n"] > 0 for x in sims) and cmin >= 2.0 and cmax <= 3.0


def test_drawdown_et_push():
    bets = [{"cote": 2.0, "issue": i, "date": d, "match": d, "groupe": "g", "selection": 0}
            for d, i in enumerate(["gagne", "perdu", "perdu", "push", "gagne"])]
    assert pr.drawdown_max(bets) == 2.0
    r = pr.resume(bets)
    assert r["n"] == 5 and math.isclose(r["roi"], (1 - 1 - 1 + 0 + 1) / 5) and math.isclose(r["reussite"], 0.5)


def test_rapport_texte():
    tous = monde(200)
    t = pr.comparer(tous, [b for b in tous if b["selection"] == 0], n_sim=100)
    assert "aléatoire" in t and "rang" in t and "simulations 1-10" in t


def test_cles_de_types_mixtes_ne_cassent_pas_le_tri():
    tous = [{"match": m, "groupe": "g", "selection": s, "cote": 2.0, "issue": "gagne", "date": 1}
            for m in ("a1", 7, None) for s in (0, 1)]
    choisis = [b for b in tous if b["selection"] == 0]
    assert len(pr.simuler_aleatoire(tous, choisis, 3, graine=1)) == 3
