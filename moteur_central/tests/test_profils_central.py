"""Moteur central — trois profils de risque (recherche exhaustive, sans cote cible). Tests locaux ; aucune preuve de rentabilité."""
import itertools

import pytest

from moteur import profils_risque as pr
from moteur_central import profils as pc
from moteur_central.score_central import CandidatCentral

PROFILS = [{"cle": f"coupon{i + 1}", "niveau_risque": n} for i, n in enumerate(pr.NIVEAUX)]


def cand(match, cat="Total", sel="Over", cote=1.8, proba=60.0, comp="L1", calibree=None, hist=None):
    return CandidatCentral(match=match, marche=cat, selection=sel, cote=cote, moteur_responsable="bet_agent", proba_pct=proba, categorie=cat,
                           competition=comp, proba_calibree_pct=calibree, historique_marche=hist)


def pool_varie(n=8):
    pool = []
    for i in range(n):
        pool += [cand(f"M{i}", "Total", "Over", 1.8, 55 + i), cand(f"M{i}", "Double Chance", "1X", 1.3, 75 - i),
                 cand(f"M{i}", "BTTS", "Yes", 2.2, 45), cand(f"M{i}", "Total Corners", "Under", 1.9, 52)]
    return pool


def test_proba_effective_calibree_prioritaire_et_none_si_absente():
    assert pc.proba_effective(cand("A", proba=60.0)) == pytest.approx(0.6)
    assert pc.proba_effective(cand("A", proba=60.0, calibree=55.0)) == pytest.approx(0.55)
    assert pc.proba_effective(cand("A", proba=0.0)) is None


def test_attenuation_quand_l_historique_est_mal_calibre():
    mauvais = {"disponible": True, "brier": 0.35}
    bon = {"disponible": True, "brier": 0.20}
    assert pc.proba_effective(cand("A", proba=80.0, hist=mauvais)) < 0.8                 # ramenée vers 0,5
    assert pc.proba_effective(cand("A", proba=80.0, hist=mauvais)) == pytest.approx(0.5 + 0.3 * 0.8)   # plafond de 20 %
    assert pc.proba_effective(cand("A", proba=80.0, hist=bon)) == pytest.approx(0.8)
    assert pc.proba_effective(cand("A", proba=80.0, hist={"disponible": False, "brier": 0.9})) == pytest.approx(0.8)   # historique indisponible : aucun effet
    assert pc.proba_effective(cand("A", proba=20.0, hist=mauvais)) > 0.2                  # une probabilité basse est aussi ramenée vers 0,5 (symétrique)


def test_candidats_sans_probabilite_ou_cote_valide_ecartes():
    jambes = pc.vers_jambes([cand("A", proba=0.0), cand("B", cote=1.0), cand("C")])
    assert [j["match"] for j in jambes] == ["C"]


def test_trois_profils_differencies_et_matchs_disjoints():
    res = pc.selectionner_profils(pool_varie(), PROFILS)
    assert [r["profil"]["niveau_risque"] for r in res] == list(pr.NIVEAUX) and all(r["jambes"] for r in res)
    matchs = [j.match for r in res for j in r["jambes"]]
    assert len(matchs) == len(set(matchs))
    assert res[0]["proba_jointe"] > res[2]["proba_jointe"] and res[2]["cote_totale"] > res[0]["cote_totale"]


def test_la_recherche_exhaustive_est_optimale_sur_le_pool_reduit():
    jambes = pc.vers_jambes(pool_varie(5))
    niveau = "equilibre"
    choisie = pc.meilleure_combinaison(jambes, niveau, taille_pool=len(jambes))
    meilleur = max((c for t in range(2, pr.TAILLE_MAX[niveau] + 1) for c in itertools.combinations(jambes, t)
                    if len({j["match"] for j in c}) == t and not pr.regles_coupon(list(c), niveau)), key=lambda c: pr.utilite_coupon(niveau, c))
    assert pr.utilite_coupon(niveau, choisie) == pytest.approx(pr.utilite_coupon(niveau, meilleur))


def test_abstention_expliquee_quand_le_pool_est_trop_petit():
    res = pc.selectionner_profils([cand("A")], PROFILS)
    assert all(not r["jambes"] and "aucune combinaison cohérente" in r["raison"] for r in res)
    res = pc.selectionner_profils(pool_varie(3), PROFILS)                                # 3 matchs : le prudent prend 2, il en reste 1 : les autres s'abstiennent
    assert res[0]["jambes"] and not res[1]["jambes"] and not res[2]["jambes"]


def test_aucune_cote_cible_une_cote_tres_haute_est_possible_pour_le_risque():
    pool = [cand(f"M{i}", "Total", "Over" if i % 2 else "Under", 6.0, 22.0, comp=f"L{i}") for i in range(4)]
    res = pc.selectionner_profils(pool, [PROFILS[2]])
    assert res[0]["jambes"] and res[0]["cote_totale"] >= 36                              # aucun plafond de cote


def test_plancher_de_securite_de_probabilite_jointe_pour_le_risque():
    pool = [cand(f"M{i}", "Total", "Over" if i % 2 else "Under", 30.0, 3.0, comp=f"L{i}") for i in range(4)]   # chaque jambe 3 % : jointe 0,09 % < 2 %
    res = pc.selectionner_profils(pool, [PROFILS[2]])
    assert not res[0]["jambes"]


def test_correlation_proche_de_la_diversification():
    pool = [cand(f"M{i}", "Total", "Over", 1.8, 60.0, comp="L1") for i in range(6)] + [cand(f"N{i}", "BTTS", "Yes", 1.8, 59.0, comp=f"L{i}") for i in range(6)]
    res = pc.selectionner_profils(pool, [PROFILS[0]])
    familles = [pr.cle_famille_sens({"categorie": j.categorie, "selection": j.selection}) for j in res[0]["jambes"]]
    assert max(familles.count(f) for f in set(familles)) <= max(2, len(familles) // 2)   # jamais un coupon de seuls « Over »
