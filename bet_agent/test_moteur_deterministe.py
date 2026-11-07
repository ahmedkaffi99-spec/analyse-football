"""Moteur déterministe — trois profils de risque par règles Python. Tests locaux ; aucune preuve de rentabilité."""
import pytest

import moteur_deterministe as md
import profils_smart
from moteur import profils_risque as pr

PROFILS = profils_smart.profils(contraintes=False)


def c(match, cat="Total", sel="Over", cote=1.8, p=60.0, comp="L1"):
    return {"match": match, "competition": comp, "pick": {"categorie": cat, "selection": sel, "cote": cote, "proba_modele_pct": p, "marche": cat}}


def pool(n=10):
    return {f"M{i}": [c(f"M{i}", "Total", "Over", 1.8, 55 + i), c(f"M{i}", "Double Chance", "1X", 1.3, 75 - i), c(f"M{i}", "BTTS", "Yes", 2.2, 45),
                      c(f"M{i}", "Total", "Under", 2.0, 45)] for i in range(n)}


def test_jambes_invalides_ecartees_sans_rien_inventer():
    p = {"M1": [c("M1", p=None), c("M1", cote=1.0), c("M1", p=0.0), c("M1")], "M2": [{"match": "M2", "pick": {}}]}
    assert [j["match"] for j in md.jambes_du_pool(p)] == ["M1"]


def test_trois_profils_matchs_disjoints_et_diversifies():
    res = md.composer(pool(), PROFILS)
    assert [r["profil"]["niveau_risque"] for r in res] == list(pr.NIVEAUX) and all(r["selections"] for r in res)
    legs = [[{"match": s["match"], "competition": s["competition"], "categorie": s["pick"]["categorie"], "selection": s["pick"]["selection"],
              "p": s["pick"]["proba_modele_pct"] / 100, "cote": s["pick"]["cote"]} for s in r["selections"]] for r in res]
    assert pr.regles_entre_coupons(legs) == []
    assert all(pr.diversite_ok(l) and pr.regles_coupon(l) == [] for l in legs)


def test_tailles_de_reference_ramenees_aux_matchs_disponibles():
    res = md.composer(pool(14), PROFILS)
    assert [len(r["selections"]) for r in res] == [3, 4, 5]                               # assez de matchs : tailles de référence
    res = md.composer(pool(5), PROFILS)
    assert sum(len(r["selections"]) for r in res) <= 5                                    # jamais plus de jambes que de matchs
    assert any(r["selections"] == [] and "minimum 2" in r["abstention"] for r in res)     # un profil sans 2 matchs s'abstient (rien n'est forcé)


def test_profils_differencies():
    res = md.composer(pool(14), PROFILS)
    def proba(r): return pr.proba_jointe([{"match": s["match"], "competition": s["competition"], "categorie": s["pick"]["categorie"], "selection": s["pick"]["selection"],
                                           "p": s["pick"]["proba_modele_pct"] / 100, "cote": s["pick"]["cote"]} for s in r["selections"]])
    assert proba(res[0]) > proba(res[2])


def test_aucun_pool_ou_un_seul_match():
    assert all(r["selections"] == [] for r in md.composer({}, PROFILS))
    assert all(r["selections"] == [] for r in md.composer({"M1": [c("M1")]}, PROFILS))


def test_aucune_cote_imposee_une_cote_basse_ou_haute_est_acceptee():
    bas = {f"M{i}": [c(f"M{i}", cote=1.05, p=90, comp=f"L{i}")] for i in range(6)}
    haut = {f"M{i}": [c(f"M{i}", cote=12.0, p=40, comp=f"L{i}")] for i in range(6)}
    assert any(r["selections"] for r in md.composer(bas, PROFILS)) and any(r["selections"] for r in md.composer(haut, PROFILS))


def test_incoherence_entre_coupons_levee(monkeypatch):
    monkeypatch.setattr(pr, "regles_entre_coupons", lambda coupons: ["match M0 dans deux coupons"])
    with pytest.raises(ValueError, match="incohérence entre coupons"):
        md.composer(pool(), PROFILS)


def test_les_candidats_d_origine_sont_renvoyes_tels_quels():
    p = pool()
    res = md.composer(p, PROFILS)
    originaux = {id(x) for cs in p.values() for x in cs}
    assert all(id(s) in originaux for r in res for s in r["selections"])                  # aucune copie modifiée : cote et probabilité du catalogue
