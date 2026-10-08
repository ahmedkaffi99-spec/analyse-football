"""Tests du moteur (hors ligne) : python -m pytest moteur"""

import copy
import math
from datetime import timedelta

import pytest

from moteur import calibration as calib
from moteur import cotes
from moteur.backtest import executer, generer_lignes
from moteur.config import Config
from moteur.features import Historique, construire_features, en_datetime
from moteur.modeles import lois, marches
from moteur.modeles.registre import MODELES, predire_match, issue_reelle
from moteur.selection import Candidat, composer_coupon, correlation, filtrer
from moteur.tests.simulation import championnat

CFG = Config()


# ---------------------------------------------------------------- lois
def test_poisson_et_binomiale_negative_somment_a_1():
    assert sum(lois.distribution(2.3)) == pytest.approx(1.0)
    d = lois.distribution(9.5, 15.0)
    moyenne = sum(k * p for k, p in enumerate(d))
    variance = sum((k - moyenne) ** 2 * p for k, p in enumerate(d))
    assert moyenne == pytest.approx(9.5, abs=0.01) and variance == pytest.approx(15.0, rel=0.02)


def test_matrice_dixon_coles():
    m0 = lois.matrice_scores(1.4, 1.1, 0.0)
    m1 = lois.matrice_scores(1.4, 1.1, -0.1)
    assert sum(map(sum, m0)) == pytest.approx(1.0) and sum(map(sum, m1)) == pytest.approx(1.0)
    assert m1[0][0] > m0[0][0] and m1[1][1] > m0[1][1]  # rho<0 : plus de scores faibles nuls


# ---------------------------------------------------------------- marchés
@pytest.mark.parametrize("marge,ligne,attendu", [
    (1, -0.5, "gagne"), (0, -0.5, "perdu"), (1, -1.0, "rembourse"), (2, -1.0, "gagne"),
    (1, -0.75, "demi_gagne"), (1, -1.25, "demi_perdu"), (0, 0.25, "demi_gagne"), (0, -0.25, "demi_perdu"),
])
def test_lignes_de_handicap(marge, ligne, attendu):
    assert marches.issue_ligne(marge, ligne) == attendu


def test_totaux_lignes_entieres_et_quart():
    assert marches.issue_total(3, 3.0, "over") == "rembourse"
    assert marches.issue_total(3, 2.75, "over") == "demi_gagne"
    assert marches.issue_total(2, 2.25, "under") == "demi_gagne"
    assert marches.issue_total(3, 2.5, "under") == "perdu"


def test_issues_somment_a_1_et_over_under_complementaires():
    m = lois.matrice_scores(1.6, 1.0)
    over = marches.distribution_buts(m, "buts_total", 2.5, "over")
    under = marches.distribution_buts(m, "buts_total", 2.5, "under")
    assert sum(over.values()) == pytest.approx(1.0)
    assert over["gagne"] + under["gagne"] == pytest.approx(1.0)
    r = {s: marches.distribution_buts(m, "resultat", None, s)["gagne"] for s in "1X2"}
    assert sum(r.values()) == pytest.approx(1.0)
    assert marches.distribution_buts(m, "double_chance", None, "1X")["gagne"] == pytest.approx(r["1"] + r["X"])
    dnb = marches.distribution_buts(m, "dnb", None, "1")
    assert dnb["rembourse"] == pytest.approx(r["X"]) and not marches.est_binaire(dnb)


def test_handicap_cote_2_utilise_la_ligne_inversee_pas_la_meme_ligne():
    """Bug réel trouvé le 09/10/2026 : issue_buts appliquait la MÊME ligne (référencée domicile,
    convention OddsPapi) aux deux sélections du handicap au lieu de l'inverser pour "2" —
    domicile gagnant d'1 seul but à une ligne de -1.5 (ne couvre pas), l'extérieur à "2" doit
    gagner son pari (tête de -1.5 à +1.5 shifted), le code bogué renvoyait "perdu"."""
    assert marches.issue_buts("handicap", -1.5, "2", 2, 1) == "gagne"  # domicile gagne 1 but, ne couvre pas -1.5
    assert marches.issue_buts("handicap", -1.5, "1", 2, 1) == "perdu"  # même match, domicile perd son pari
    assert marches.issue_buts("handicap", -1.5, "2", 3, 1) == "perdu"  # domicile gagne 2 buts, couvre -1.5
    assert marches.issue_buts("handicap", -1.5, "1", 3, 1) == "gagne"


def test_handicap_1_et_2_sont_complementaires_gagne_perdu_push_ensemble():
    """Les deux côtés d'un même handicap asiatique doivent être des paris strictement
    complémentaires (l'un gagne si et seulement si l'autre perd, tous deux remboursés sur le
    même push) — sinon les probabilités du modèle ne somment plus correctement sur les deux
    sélections d'un même marché, une incohérence qui aurait dû révéler le bug ci-dessus."""
    m = lois.matrice_scores(1.6, 1.0)
    for ligne in (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
        d1 = marches.distribution_buts(m, "handicap", ligne, "1")
        d2 = marches.distribution_buts(m, "handicap", ligne, "2")
        assert d1["gagne"] == pytest.approx(d2["perdu"])
        assert d1["perdu"] == pytest.approx(d2["gagne"])
        assert d1["rembourse"] == pytest.approx(d2["rembourse"])


def test_edge_formule_exacte():
    assert cotes.edge(0.82, 1.30) == pytest.approx(0.066)
    binaire = {"gagne": 0.82, "demi_gagne": 0, "rembourse": 0, "demi_perdu": 0, "perdu": 0.18}
    assert marches.esperance(binaire, 1.30) == pytest.approx(cotes.edge(0.82, 1.30))


def test_sans_marge():
    p = cotes.sans_marge({"over": 1.85, "under": 1.95})
    assert sum(p.values()) == pytest.approx(1.0)
    assert cotes.marge({"over": 1.85, "under": 1.95}) > 0
    assert cotes.sans_marge({"over": 1.85}) is None


# ---------------------------------------------------------------- features : aucune fuite
def test_aucune_fuite_temporelle():
    """Modifier le score et les stats du match prédit ET de tous les matchs futurs ne doit
    rien changer aux features : la preuve qu'aucune donnée future n'est utilisée."""
    matchs, _ = championnat()
    cible = matchs[150]
    t = en_datetime(cible["date"])
    avant = construire_features(cible, Historique(matchs))
    falsifies = copy.deepcopy(matchs)
    for m in falsifies:
        if en_datetime(m["date"]) >= t:
            m["home_score"], m["away_score"] = 9, 0
            m["stats"] = {"home": {"corners": 30, "yellow_cards": 9, "shots": 60, "shots_on_target": 30, "fouls": 40},
                          "away": {"corners": 0, "yellow_cards": 0, "shots": 0, "shots_on_target": 0, "fouls": 0}}
    apres = construire_features(cible, Historique(falsifies))
    assert apres == avant


def test_match_simultane_exclu():
    matchs, _ = championnat()
    cible = matchs[100]
    jumeau = dict(copy.deepcopy(matchs[90]), match_id=99999, date=cible["date"], home_score=8, away_score=8)
    f1 = construire_features(cible, Historique(matchs))
    f2 = construire_features(cible, Historique(matchs + [jumeau]))
    assert f1 == f2


def test_elo_avant_le_match():
    matchs, _ = championnat()
    hist = Historique(matchs)
    premier = min(matchs, key=lambda m: m["date"])
    assert hist.elo(premier) == (1500.0, 1500.0)


# ---------------------------------------------------------------- 10 modèles
def test_les_10_modeles_produisent_des_probabilites_valides():
    matchs, _ = championnat()
    cible = matchs[200]
    preds = predire_match(construire_features(cible, Historique(matchs)), CFG)
    assert {p.modele for p in preds} == set(MODELES)
    for p in preds:
        assert 0 <= p.probabilite <= 1
        assert sum(p.issues.values()) == pytest.approx(1.0)


def test_pas_de_prediction_sans_historique():
    matchs, _ = championnat()
    premier = min(matchs, key=lambda m: m["date"])
    assert predire_match(construire_features(premier, Historique(matchs)), CFG) == []


def test_pas_de_modele_comptage_sans_statistiques():
    matchs, _ = championnat(avec_stats=False)
    preds = predire_match(construire_features(matchs[200], Historique(matchs)), CFG)
    assert {p.modele for p in preds} == set(range(1, 8))


def test_buts_attendus_suivent_les_forces_reelles():
    matchs, forces = championnat(n_equipes=8, saisons=(2023, 2024, 2025))
    hist = Historique(matchs)
    fort = max(forces, key=lambda e: forces[e][0] / forces[e][1])
    faible = min(forces, key=lambda e: forces[e][0] / forces[e][1])
    futur = {"match_id": -1, "date": matchs[-1]["date"] + timedelta(days=1), "competition_id": 1,
             "home_id": fort, "away_id": faible}
    preds = predire_match(construire_features(futur, hist), CFG)
    p1 = next(p for p in preds if p.marche == "resultat" and p.selection == "1")
    p2 = next(p for p in preds if p.marche == "resultat" and p.selection == "2")
    assert p1.probabilite > p2.probabilite


def test_issue_reelle():
    m = {"home_score": 2, "away_score": 1,
         "stats": {"home": {"corners": 6, "yellow_cards": 2}, "away": {"corners": 4, "yellow_cards": 3}}}
    assert issue_reelle(m, "resultat", None, "1") == "gagne"
    assert issue_reelle(m, "btts", None, "oui") == "gagne"
    assert issue_reelle(m, "corners_total", 9.5, "over") == "gagne"
    assert issue_reelle(m, "cartons_equipe2", 2.5, "over") == "gagne"
    assert issue_reelle(m, "tirs_total", 20.5, "over") is None  # statistique absente : jamais inventée


# ---------------------------------------------------------------- calibration
def test_isotone_monotone_et_corrige_une_surconfiance():
    points = [(0.9, 1 if i % 10 < 6 else 0) for i in range(200)] + [(0.6, 1 if i % 10 < 5 else 0) for i in range(200)]
    iso = calib.Isotone(points)
    assert iso(0.9) == pytest.approx(0.6) and iso(0.6) == pytest.approx(0.5)
    assert iso(0.95) >= iso(0.6)


def test_calibrateur_refuse_un_petit_echantillon():
    cal = calib.Calibrateur(min_n=100).ajuster([(1, "resultat", 0.7, 1)] * 10)
    p, n, fiable = cal.calibrer(1, "resultat", 0.7)
    assert (p, n, fiable) == (0.7, 10, False)


def test_brier_et_fiabilite():
    assert calib.brier([(1.0, 1), (0.0, 0)]) == 0
    t = calib.tableau_fiabilite([(0.75, 1), (0.75, 0), (0.85, 1)])
    assert t[0]["tranche"] == "70-80%" and t[0]["frequence_reelle"] == 0.5


# ---------------------------------------------------------------- sélection / corrélation / coupon
def _cand(match_id, marche="buts_total", ligne=2.5, selection="over", proba=0.8, cote=1.4, calibre=True):
    return Candidat(match_id, f"M{match_id}", None, "L", 4, marche, ligne, selection, proba, proba, calibre, 500,
                    True, cote, cotes.edge(proba, cote) if cote else None,
                    {"lambda_home": 1.6, "lambda_away": 1.2, "rho": 0.0})


def test_filtres_et_raisons():
    cfg = Config(proba_min=0.75, edge_min=0.02, cote_max=2.0)
    ok, faible, sans_cote, chere, non_cal = (_cand(1), _cand(2, proba=0.6), _cand(3, cote=None),
                                             _cand(4, cote=2.5), _cand(5, calibre=False))
    retenus = filtrer([ok, faible, sans_cote, chere, non_cal], cfg)
    assert retenus == [ok]
    assert any("probabilité" in r for r in faible.raisons_rejet)
    assert any("calibration" in r for r in non_cal.raisons_rejet)


def test_correlation_exacte_meme_match():
    over = _cand(1, "buts_total", 2.5, "over")
    btts = _cand(1, "btts", None, "oui")
    under = _cand(1, "buts_total", 2.5, "under")
    assert correlation(over, btts) > 0.3
    assert correlation(over, under) == pytest.approx(-1.0)
    assert correlation(over, _cand(2)) == 0.0
    assert correlation(over, _cand(1, "corners_total", 9.5)) == 1.0  # familles différentes : refusé


def test_coupon_jamais_rempli_artificiellement():
    cfg = Config(coupon_min=12, coupon_max=15)
    res = composer_coupon([_cand(i) for i in range(7)], cfg)
    assert not res["genere"] and "Coupon non généré" in res["raison"]
    res = composer_coupon([_cand(i, proba=0.8 + i / 1000) for i in range(20)], cfg)
    assert res["genere"] and len(res["jambes"]) == 15
    assert res["proba_combinee"] == pytest.approx(math.prod(j.proba for j in res["jambes"]))
    assert len({j.match_id for j in res["jambes"]}) == 15


def test_coupon_une_jambe_par_match_par_defaut():
    cfg = Config(coupon_min=1, coupon_max=15)
    res = composer_coupon([_cand(1), _cand(1, "resultat", None, "1")], cfg)
    assert len(res["jambes"]) == 1


# ---------------------------------------------------------------- backtest
def test_backtest_complet_sans_cotes_puis_avec():
    matchs, _ = championnat(n_equipes=10, saisons=(2023, 2024))
    cfg = Config(calibration_min_n=50)
    debut, fin = matchs[60]["date"], matchs[-1]["date"] + timedelta(days=1)
    r = executer(matchs, {}, cfg, debut, fin)
    assert r["global"]["n_predictions"] > 0
    assert not r["seuils"]["disponible"]
    assert r["selection"]["n_paris"] == 0
    # cotes justes (proba vraie inconnue -> on prend la proba brute du modèle) avec 5 % de marge,
    # relevées 2 h avant : la sélection ne doit trouver presque aucun edge
    cotes_par_match = {}
    for ln in r["_lignes"]:
        if ln.binaire and 0.05 < ln.proba_brute < 0.95:
            cotes_par_match.setdefault(ln.match_id, []).append(
                {"marche": ln.marche, "ligne": ln.ligne, "selection": ln.selection,
                 "cote": round(1 / (ln.proba_brute * 1.05), 3), "horodatage": ln.date - timedelta(hours=2)})
    # Sans calibration (min_n inatteignable) : proba = proba brute, la marge rend tout edge négatif.
    r2 = executer(matchs, cotes_par_match, Config(calibration_min_n=10 ** 9, exiger_calibration=False, edge_min=0.0),
                  debut, fin)
    assert r2["seuils"]["disponible"]
    assert r2["selection"]["n_paris"] == 0


def test_backtest_ignore_les_cotes_posterieures_au_coup_envoi():
    matchs, _ = championnat(n_equipes=8, saisons=(2023,))
    cible = matchs[-1]
    releves = {cible["match_id"]: [{"marche": "resultat", "ligne": None, "selection": "1", "cote": 1.5,
                                    "horodatage": en_datetime(cible["date"]) + timedelta(minutes=1)}]}
    lignes = generer_lignes(matchs, releves, CFG, cible["date"], cible["date"] + timedelta(seconds=1))
    assert all(ln.cote is None for ln in lignes)


def test_calibration_walk_forward_n_utilise_que_le_passe():
    matchs, _ = championnat(n_equipes=10, saisons=(2023, 2024))
    r = executer(matchs, {}, Config(calibration_min_n=50), matchs[60]["date"], matchs[-1]["date"] + timedelta(days=1))
    premier_mois = min(ln.mois for ln in r["_lignes"])
    assert not any(ln.calibre for ln in r["_lignes"] if ln.mois == premier_mois)


def test_comparaison_hors_echantillon():
    from moteur.comparaison import comparer

    matchs, _ = championnat(n_equipes=12, saisons=(2022, 2023, 2024))
    r = comparer(matchs, CFG)
    assert r["cibles"]["over_2_5"]["scores"]["poisson"]["n"] > 0
    assert r["cibles"]["over_2_5"]["meilleur_hors_echantillon"] is not None


def test_contrat_prediction_et_cote_invalide():
    from moteur import contrat

    matchs, _ = championnat()
    p = predire_match(construire_features(matchs[200], Historique(matchs)), CFG)[0]
    d = contrat.avec_cote(contrat.prediction(7, p), 1.30, "1xbet")
    assert d["implied_probability"] == pytest.approx(1 / 1.30)
    assert d["edge"] == pytest.approx(d["probability"] * 1.30 - 1)
    for invalide in (None, 0, 1.0, -2):
        assert contrat.avec_cote(contrat.prediction(7, p), invalide)["edge"] is None
    assert contrat.insuffisant(7, 8, "stats")["status"] == "INSUFFICIENT_DATA"
