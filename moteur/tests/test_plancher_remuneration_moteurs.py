"""07/11/2026 — mêmes planchers de rémunération pour les trois moteurs : aucune jambe sous 1.20, aucun coupon sous 1.60 (jamais de coupon à 1.04), aucun plafond.
Tests locaux ; ils ne prouvent aucune rentabilité prédictive."""
import importlib
import os
import sys

import pytest

from moteur import profils_risque as pr

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
for chemin in (RACINE, os.path.join(RACINE, "bet_agent")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)


@pytest.fixture(autouse=True)
def planchers_de_production(monkeypatch):
    monkeypatch.setattr(pr, "COTE_MIN_JAMBE", 1.20)
    monkeypatch.setattr(pr, "COTE_TOTALE_MIN_COUPON", 1.60)


def jambe(match, cote, p=0.8, categorie="Total", selection="Over", comp="L1"):
    return {"match": match, "competition": comp, "categorie": categorie, "selection": selection, "p": p, "cote": cote}


def test_jambe_sous_le_plancher_technique_refusee():
    assert "plancher technique" in pr.valider_jambe(jambe("A", 1.02))
    assert pr.valider_jambe(jambe("A", 1.20)) is None and pr.valider_jambe(jambe("A", 25.0)) is None   # aucun plafond


def test_coupon_a_1_04_refuse_meme_si_chaque_jambe_est_valide():
    legs = [jambe("A", 1.20, categorie="Total"), jambe("B", 1.20, categorie="BTTS", selection="Yes")]       # 1,44
    assert any("plancher de rémunération" in p for p in pr.regles_coupon(legs))
    legs = [jambe("A", 1.30), jambe("B", 1.30, categorie="BTTS", selection="Yes")]                         # 1,69
    assert pr.regles_coupon(legs) == []


def test_planchers_desactivables(monkeypatch):
    monkeypatch.setattr(pr, "COTE_MIN_JAMBE", 0.0)
    monkeypatch.setattr(pr, "COTE_TOTALE_MIN_COUPON", 0.0)
    assert pr.valider_jambe(jambe("A", 1.02)) is None
    assert pr.regles_coupon([jambe("A", 1.02), jambe("B", 1.02, categorie="BTTS", selection="Yes")]) == []


def test_lecture_des_variables_d_environnement(monkeypatch):
    try:
        for valeur, attendu in (("1.5", 1.5), ("abc", 1.2), ("", 1.2), ("0", 0.0), ("-2", 0.0)):
            monkeypatch.setenv("COTE_MIN_JAMBE_AGENT", valeur)
            importlib.reload(pr)
            assert pr.COTE_MIN_JAMBE == attendu, valeur
    finally:
        monkeypatch.delenv("COTE_MIN_JAMBE_AGENT", raising=False)
        importlib.reload(pr)


def _pool_bas_et_haut():
    """Chaque match offre une jambe à 1.02 (écartée) et des jambes correctement payées."""
    pool = {}
    for i in range(12):
        pool[f"M{i}"] = [
            {"match": f"M{i}", "competition": f"L{i % 3}", "pick": {"categorie": "Double Chance", "selection": "1X", "cote": 1.02, "proba_modele_pct": 97.0, "marche": "dc"}},
            {"match": f"M{i}", "competition": f"L{i % 3}", "pick": {"categorie": "Total", "selection": "Over", "cote": 1.55, "proba_modele_pct": 62.0, "marche": "t"}},
            {"match": f"M{i}", "competition": f"L{i % 3}", "pick": {"categorie": "BTTS", "selection": "Yes", "cote": 1.9, "proba_modele_pct": 52.0, "marche": "b"}},
            {"match": f"M{i}", "competition": f"L{i % 3}", "pick": {"categorie": "Total Corners", "selection": "Under", "cote": 2.4, "proba_modele_pct": 41.0, "marche": "c"}}]
    return pool


def test_le_moteur_deterministe_ne_produit_jamais_de_coupon_sous_les_planchers():
    import moteur_deterministe as md
    profils = [{"cle": f"c{i}", "niveau_risque": n} for i, n in enumerate(pr.NIVEAUX)]
    for r in md.composer(_pool_bas_et_haut(), profils):
        assert r["selections"], r.get("abstention")
        cotes = [s["pick"]["cote"] for s in r["selections"]]
        assert min(cotes) >= 1.20                                                      # la jambe à 1.02 n'est jamais retenue, même pour le prudent (probabilité 97 %)
        total = 1.0
        for c in cotes:
            total *= c
        assert total >= 1.60


def test_le_moteur_central_ne_produit_jamais_de_coupon_sous_les_planchers():
    from moteur_central.profils import selectionner_profils
    from moteur_central.score_central import CandidatCentral
    pool = [CandidatCentral(match=m, marche=c["pick"]["categorie"], selection=c["pick"]["selection"], cote=c["pick"]["cote"], moteur_responsable="bet_agent",
                            proba_pct=c["pick"]["proba_modele_pct"], categorie=c["pick"]["categorie"], competition=c["competition"])
            for m, cs in _pool_bas_et_haut().items() for c in cs]
    profils = [{"cle": f"c{i}", "niveau_risque": n} for i, n in enumerate(pr.NIVEAUX)]
    for r in selectionner_profils(pool, profils):
        assert r["jambes"], r["raison"]
        assert min(j.cote for j in r["jambes"]) >= 1.20 and r["cote_totale"] >= 1.60


def test_un_pool_de_seules_cotes_minuscules_donne_une_abstention_expliquee_pas_un_coupon():
    import moteur_deterministe as md
    pool = {f"M{i}": [{"match": f"M{i}", "competition": "L", "pick": {"categorie": "Double Chance", "selection": "1X", "cote": 1.02, "proba_modele_pct": 97.0, "marche": "dc"}}] for i in range(8)}
    profils = [{"cle": f"c{i}", "niveau_risque": n} for i, n in enumerate(pr.NIVEAUX)]
    res = md.composer(pool, profils)
    assert all(r["selections"] == [] and r.get("abstention") for r in res)
