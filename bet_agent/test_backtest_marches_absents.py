"""Backtest des marchés absents : exécution sur un championnat synthétique à forces connues."""

import pytest

import backtest_marches_absents as bt
from moteur.tests.simulation import championnat


@pytest.fixture(scope="module")
def collecteur():
    matchs, _ = championnat(n_equipes=14, saisons=(2023, 2024, 2025))
    return bt.executer({1: matchs})


def test_tous_les_marches_absents_sont_evalues(collecteur):
    noms = set(collecteur.points)
    for attendu in ("BTTS (oui/non)", "Pair/Impair des buts", "Win To Nil équipe 1", "Clean sheet équipe 2",
                    "Score exact (score le plus probable)", "Handicap buts, ligne -1.5",
                    "Handicap corners, ligne +0.5", "Handicap fautes, ligne -1.5", "Handicap tirs, ligne +2.5",
                    "Total corners équipe 1 (over/under)", "Total tirs_cadres équipe 2 (over/under)"):
        assert attendu in noms, attendu


def test_les_probabilites_restent_dans_0_5_1(collecteur):
    for marche, pts in collecteur.points.items():
        if marche.startswith("Score exact"):
            continue  # p du score le plus probable (~10 %) : se lit en taux de réussite global
        assert pts and all(0.5 <= p <= 1.0 + 1e-9 and y in (0, 1) for p, y in pts), marche


def test_score_exact_taux_annonce_proche_du_taux_reel(collecteur):
    r = bt.resumer([(p, y) for p, y in collecteur.points["Score exact (score le plus probable)"]])
    assert r["n"] > 300 and abs(r["annonce"] - r["reel"]) < 0.05


def test_btts_calibre_sur_donnees_poisson_simulees(collecteur):
    # les données simulées SONT Poisson : le BTTS du modèle doit être proche de la fréquence réelle
    r = bt.resumer(collecteur.points["BTTS (oui/non)"])
    assert r["n"] > 300 and abs(r["annonce"] - r["reel"]) < 0.06


def test_remboursement_ecarte_du_calcul_de_frequence():
    col = bt.Collecteur()
    issues = {"gagne": 0.5, "demi_gagne": 0.0, "rembourse": 0.2, "demi_perdu": 0.0, "perdu": 0.3}
    col.issues("x", issues, "rembourse")
    assert col.points["x"] == []
    col.issues("x", issues, "gagne")
    p, y = col.points["x"][0]
    assert y == 1 and abs(p - 0.5 / 0.8) < 1e-9     # p_gain / (1 - p_remboursement)


def test_cote_probable_choisi_quand_p_sous_un_demi():
    col = bt.Collecteur()
    col.binaire("m", 0.3, True)       # événement improbable arrivé -> le côté probable (non) a perdu
    assert col.points["m"] == [(0.7, 0)]


def test_verdict_et_resume():
    pts = [(0.75, 1)] * 150 + [(0.75, 0)] * 50           # annoncé 75 %, réel 75 % -> calibré
    r = bt.resumer(pts)
    assert r["verdict"] == "CALIBRÉ" and abs(r["ecart_hautes_pts"]) < 1e-6
    r = bt.resumer([(0.8, 1)] * 100 + [(0.8, 0)] * 100)  # annoncé 80 %, réel 50 %
    assert r["verdict"].startswith("SUR-ESTIMÉ")
    assert bt.resumer([(0.8, 1)] * 10)["verdict"].startswith("n insuffisant")


# ------------------------------------------------------------------ hors-jeux (échantillon API simulé)
def _fixtures_hors_jeux(n_equipes=10, tours=8, graine=3):
    import random
    rng = random.Random(graine)
    fixtures, fid = [], 1
    for tour in range(tours):
        for h in range(n_equipes):
            for a in range(n_equipes):
                if h == a or (h + a + tour) % 3:
                    continue
                oh, oa = rng.randint(0, 5), rng.randint(0, 5)
                fx = {"fixture": {"id": fid, "date": f"2025-{1 + tour:02d}-{1 + (fid % 27):02d}T18:00:00+00:00"},
                      "league": {"id": 1, "season": 2025}, "goals": {"home": rng.randint(0, 3), "away": rng.randint(0, 3)},
                      "teams": {"home": {"id": h}, "away": {"id": a}}}
                fixtures.append((fx, [{"type": "Offsides", "value": oh}], [{"type": "Offsides", "value": oa}]))
                fid += 1
    return fixtures


def test_backtest_hors_jeux_sur_echantillon_simule():
    import backtest_hors_jeux as hj
    matchs = hj.construire_matchs(_fixtures_hors_jeux())
    assert len(matchs) > 100 and all("offsides" in m["stats"]["home"] for m in matchs)
    col, diag = hj.evaluer(matchs)
    assert diag["n"] > 50 and 3.5 < diag["mu_moyen"] < 6.0
    assert "Total hors-jeux (over/under)" in col.points and "Handicap hors-jeux, ligne +0.5" in col.points


def test_match_sans_hors_jeux_suivis_ignore():
    import backtest_hors_jeux as hj
    fx = {"fixture": {"id": 1, "date": "2025-01-01T18:00:00+00:00"}, "league": {"id": 1}, "goals": {"home": 1, "away": 0},
          "teams": {"home": {"id": 1}, "away": {"id": 2}}}
    assert hj.construire_matchs([(fx, [{"type": "Offsides", "value": None}], [{"type": "Offsides", "value": 2}])]) == []


def test_grille_facteurs_restaure_les_facteurs_et_rapporte_chaque_echelle():
    import analyser_et_envoyer as ae
    matchs, _ = championnat(n_equipes=10, saisons=(2023, 2024))
    avant = dict(ae.FACTEUR_DOMICILE)
    res = bt.grille_facteurs({1: matchs}, echelles=(0.0, 1.0))
    assert ae.FACTEUR_DOMICILE == avant
    assert set(res) == {0.0, 1.0} and all("corners" in r for r in res.values())
    assert all(0 < brier < 0.5 for r in res.values() for brier, _ in r.values())
