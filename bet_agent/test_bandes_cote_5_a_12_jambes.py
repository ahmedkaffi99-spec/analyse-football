"""Demande du 07/11/2026 : 5 à 12 jambes par coupon, cote totale minimale 5, trois bandes de cote totale espacées. Tests locaux ; aucune preuve de rentabilité."""
import pytest

import agent_strategie as st
import moteur_deterministe as md
import profils_smart
from moteur import profils_risque as pr


def test_profils_par_defaut_cinq_a_douze_jambes_et_bandes_espacees():
    p = profils_smart.profils()
    assert all(x["nb_jambes_min"] == 5 and x["nb_jambes"] == 12 for x in p)
    bandes = [(x["cote_totale_min"], x["cote_totale_max"]) for x in p]
    assert bandes == [(5.0, 10.0), (12.0, 20.0), (25.0, 50.0)]
    assert min(b[0] for b in bandes) >= 5 and all(bandes[i][1] < bandes[i + 1][0] for i in range(2))


def test_bandes_modifiables_par_variable_et_invalides_ignorees(monkeypatch):
    monkeypatch.setenv("BANDE_COTE_RISQUE", "30-80")
    monkeypatch.setenv("BANDE_COTE_PRUDENT", "10-5")        # min >= max : ignoré
    monkeypatch.setenv("BANDE_COTE_EQUILIBRE", "abc")        # illisible : ignoré
    assert profils_smart.bande_cote("risque") == (30.0, 80.0)
    assert profils_smart.bande_cote("prudent") == (5.0, 10.0)
    assert profils_smart.bande_cote("equilibre") == (12.0, 20.0)


def _j(i, cote, cat="Total", sel="Over"):
    cat, sel = (("Total", "Over"), ("Double Chance", "1X"), ("BTTS", "Yes"), ("Corners", "Under"), ("Total", "Under"), ("Cartons", "Over"))[i % 6]
    return {"match": f"M{i}", "competition": f"L{i}", "categorie": cat, "selection": sel, "p": 0.7, "cote": cote}


def test_regles_coupon_nombre_de_jambes_et_bande():
    prudent = profils_smart.profils()[0]
    ok = [_j(i, 1.3) for i in range(7)]                       # 1.3^7 = 6.27 dans 5-10
    assert pr.regles_coupon(ok, "prudent", prudent) == []
    assert any("minimum 5" in x for x in pr.regles_coupon(ok[:4], "prudent", prudent))
    assert any("au-dessus du maximum" in x for x in pr.regles_coupon([_j(i, 1.5) for i in range(7)], "prudent", prudent))   # 1.5^7 = 17
    assert any("sous le minimum 5" in x for x in pr.regles_coupon([_j(i, 1.2) for i in range(6)], "prudent", prudent))       # 1.2^6 = 2.99
    assert any("maximum 12" in x for x in pr.regles_coupon([_j(i, 1.2) for i in range(13)], "prudent", prudent))


def _pool(n=19):
    return {f"M{i}": [{"match": f"M{i}", "competition": f"L{i % 4}",
                       "pick": {"categorie": cat, "selection": sel, "cote": cote, "proba_modele_pct": p, "edge_pct": 5.0, "marche": cat}}
                      for cat, sel, cote, p in (("Total", "Over", 1.55, 66), ("Double Chance", "1X", 1.35, 75), ("BTTS", "Yes", 2.0, 52), ("Corners", "Under", 1.7, 60))]
            for i in range(n)}


def test_moteur_deterministe_respecte_nombre_de_jambes_et_bandes():
    res = md.composer(_pool(), profils_smart.profils())
    for r in res:
        if r["selections"]:
            nb = len(r["selections"])
            cote = 1.0
            for s in r["selections"]:
                cote *= s["pick"]["cote"]
            assert 5 <= nb <= 12
            assert r["profil"]["cote_totale_min"] <= cote <= r["profil"]["cote_totale_max"], (r["profil"]["cle"], cote)
        else:
            assert r["abstention"]                                  # jamais de coupon forcé hors bande


def test_validation_agent_refuse_hors_bande_et_trop_peu_de_jambes():
    catalogue, _ = st.construire_catalogue(_pool(), seuil_proba=0)
    ids = {(c["match"], c["pick"]["categorie"], c["pick"]["selection"]): cid for cid, c in catalogue.items()}
    prudent = profils_smart.profils()[0]
    jambes = lambda ms, cat, sel: [{"id": ids[(m, cat, sel)], "raison": "r"} for m in ms]
    trop_court = {"coupons": [{"profil": "coupon1", "strategie": "s", "jambes": jambes(["M0", "M1", "M2"], "Double Chance", "1X")}]}
    acceptes, problemes, _ = st.valider(trop_court, catalogue, [prudent])
    assert "coupon1" not in acceptes and "minimum 5" in " ".join(problemes)
    hors_bande = {"coupons": [{"profil": "coupon1", "strategie": "s", "jambes": jambes([f"M{i}" for i in range(8)], "BTTS", "Yes")}]}   # 2^8 = 256
    acceptes, problemes, _ = st.valider(hors_bande, catalogue, [prudent])
    assert "coupon1" not in acceptes and "trop haute" in " ".join(problemes)
    bon = {"coupons": [{"profil": "coupon1", "strategie": "s", "jambes": jambes([f"M{i}" for i in range(7)], "Double Chance", "1X")}]}      # 1.35^7 = 8.17
    acceptes, problemes, _ = st.valider(bon, catalogue, [prudent])
    assert "coupon1" in acceptes, problemes


def test_moteur_central_respecte_nombre_de_jambes_et_bandes():
    from moteur_central.profils import selectionner_profils
    from moteur_central.score_central import CandidatCentral
    cands = [CandidatCentral(match=f"M{i}", marche=cat, selection=sel, cote=cote, moteur_responsable="x", proba_pct=p, categorie=cat, competition=f"L{i % 4}")
             for i in range(19) for cat, sel, cote, p in (("Total", "Over", 1.55, 66), ("Double Chance", "1X", 1.35, 75), ("BTTS", "Yes", 2.0, 52), ("Corners", "Under", 1.7, 60))]
    sortie = selectionner_profils(cands, profils_smart.profils())
    assert all(r["jambes"] for r in sortie), [r["raison"] for r in sortie]
    for r in sortie:
        assert 5 <= len(r["jambes"]) <= 12
        assert r["profil"]["cote_totale_min"] <= r["cote_totale"] <= r["profil"]["cote_totale_max"]
    for r in sortie:
        assert len({c.match for c in r["jambes"]}) == len(r["jambes"])                                      # un seul pari par match DANS un coupon
    exacts = [(c.match, c.categorie, c.selection) for r in sortie for c in r["jambes"]]
    assert len(set(exacts)) == len(exacts)                                                                  # jamais le même pari exact dans deux coupons


def test_desequilibre_penalise_beaucoup_de_jambes_basses_et_peu_de_jambes_hautes():
    profil = profils_smart.profils()[1]
    def jambes(n, cote):
        return [_j(i, cote) for i in range(n)]
    assert pr.desequilibre(jambes(12, 1.2), profil) > pr.desequilibre(jambes(8, 1.6), profil)
    assert pr.desequilibre(jambes(5, 2.5), profil) > pr.desequilibre(jambes(8, 1.6), profil)
    assert pr.desequilibre(jambes(8, 1.6), profil) < 0.25


def test_moteur_deterministe_prefere_la_taille_equilibree_dans_la_bande():
    legs = [_j(i, 1.3) for i in range(12)]
    profil = profils_smart.profils()[0]                      # bande 5-10 : tailles 7 (6.27) à 8 (8.16) et 9 (10.6 hors bande)
    choisi = md._dans_la_bande(legs, profil)
    assert 7 <= len(choisi) <= 8 and 5 <= pr.cote_totale(choisi) <= 10


def test_un_match_peut_figurer_dans_plusieurs_coupons_avec_des_paris_differents():
    """Demande du 07/11/2026 : 2 paris sur un même match sont permis s'ils sont dans des coupons différents ; chaque coupon choisit parmi tous les matchs."""
    assert all(p["match_repete_autorise"] for p in profils_smart.profils())
    assert pr.regles_entre_coupons([[_j(0, 1.3)], [dict(_j(0, 1.5), selection="Autre")]], True) == []
    assert any("deux coupons" in x for x in pr.regles_entre_coupons([[_j(0, 1.3)], [_j(0, 1.3)]], True))      # même pari exact : interdit
    assert pr.regles_entre_coupons([[_j(0, 1.3)], [dict(_j(0, 1.5), selection="Autre")]]) != []               # règle par défaut : un match, un coupon
    res = md.composer(_pool(19), profils_smart.profils())
    assert all(r["selections"] for r in res), [r.get("abstention") for r in res]                               # les trois profils obtiennent un coupon
    tous = [s for r in res for s in r["selections"]]
    exacts = [(s["match"], s["pick"]["categorie"], s["pick"]["selection"]) for s in tous]
    assert len(set(exacts)) == len(exacts)
