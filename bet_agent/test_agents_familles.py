import json

import pytest

import agent_strategie as st
import agents_familles as af
import analyser_et_envoyer as ae


def _cand(match, categorie, selection, cote, proba, edge, marche="M"):
    return {"match": match, "pick": {"categorie": categorie, "marche": marche, "marche_affichage": marche,
                                      "selection": selection, "cote": cote, "proba_modele_pct": proba,
                                      "edge_pct": edge, "handicap": None}}


def _pool():
    return {
        "A vs B": [_cand("A vs B", "Double Chance", "1X", 1.8, 76.0, 8.0),
                   _cand("A vs B", "Total", "Over", 1.7, 74.0, 6.0)],
        "C vs D": [_cand("C vs D", "Total Corners", "Under", 1.9, 72.0, 25.0),
                   _cand("C vs D", "Score Exact Bizarre", "1-0", 6.0, 71.0, 5.0)],
    }


@pytest.fixture(autouse=True)
def agents_actifs(monkeypatch):
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "1")


def test_dix_familles_declarees_plus_derives():
    assert len(af.FAMILLES) == 9
    ids = {f[0] for f in af.FAMILLES} | {af.FAMILLE_DERIVES[0]}
    assert len(ids) == 10


def test_famille_de_categorie_connue_et_inconnue():
    assert af.famille_de("Double Chance")[0] == "resultat"
    assert af.famille_de("Total Corners")[0] == "corners"
    assert af.famille_de("Total Tirs")[0] == "tirs"
    assert af.famille_de("Score Exact Bizarre")[0] == "derives"


def test_veto_python_edge_suspect():
    assert af.veto_python({"categorie": "Total", "edge_pct": 25.0}) is not None
    assert af.veto_python({"categorie": "Total", "edge_pct": 20.0}) is None
    assert af.veto_python({"categorie": "Total", "edge_pct": None}) is None


def test_veto_python_categorie_exclue():
    assert "Total Tirs" in ae.CATEGORIES_EXCLUES
    assert af.veto_python({"categorie": "Total Tirs", "edge_pct": 1.0}) is not None


def test_revoir_catalogue_veto_python_sans_ia(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool())
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: True)
    ecartes, avis = af.revoir_catalogue(catalogue, appel=lambda *a, **k: pytest.fail("IA appelée"))
    ids_corners = [i for i, c in catalogue.items() if c["pick"]["categorie"] == "Total Corners"]
    assert set(ids_corners) == ecartes
    assert "edge suspect" in avis[ids_corners[0]]


def test_revoir_catalogue_ia_ecarte_un_pari_valide(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool())
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    id_dc = next(i for i, c in catalogue.items() if c["pick"]["categorie"] == "Double Chance")
    id_total = next(i for i, c in catalogue.items() if c["pick"]["categorie"] == "Total")

    def appel(prompt, max_tokens=0, json_attendu=False):
        if "Résultat 1X2" in prompt:
            return json.dumps({"ecartes": [{"id": id_dc, "raison": "1X surestimé"}], "avis": []})
        return json.dumps({"ecartes": [], "avis": [{"id": id_total, "note": "RAS"}]})

    ecartes, avis = af.revoir_catalogue(catalogue, appel=appel)
    assert id_dc in ecartes and "1X surestimé" in avis[id_dc]
    assert id_total not in ecartes and "RAS" in avis[id_total]


def test_ia_ne_peut_ecarter_que_des_ids_du_catalogue_et_moitie_max(monkeypatch):
    pool = {f"M{i} vs X{i}": [_cand(f"M{i} vs X{i}", "Total", "Over", 1.7, 74.0, 6.0)] for i in range(4)}
    catalogue, _ = st.construire_catalogue(pool)
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    tous = list(catalogue)

    def appel(prompt, max_tokens=0, json_attendu=False):
        return json.dumps({"ecartes": [{"id": i, "raison": "x"} for i in tous] + [{"id": "P999", "raison": "x"}]})

    ecartes, _ = af.revoir_catalogue(catalogue, appel=appel)
    assert len(ecartes) == 2 and ecartes <= set(tous)


def test_reponse_ia_invalide_laisse_la_famille_inchangee(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool())
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    ecartes, _ = af.revoir_catalogue(catalogue, appel=lambda *a, **k: "pas du json")
    ids_corners = {i for i, c in catalogue.items() if c["pick"]["categorie"] == "Total Corners"}
    assert ecartes == ids_corners


def test_catalogue_ids_stables_et_pari_ecarte_masque():
    pool = _pool()
    complet, _ = st.construire_catalogue(pool)
    cid = next(iter(complet))
    reduit, texte = st.construire_catalogue(pool, ecartes={cid}, avis={"P2": "note test"})
    assert cid not in reduit and set(reduit) == set(complet) - {cid}
    assert reduit[next(iter(reduit))] is complet[next(iter(reduit))]
    assert "note test" in texte


def test_composer_coupons_appelle_les_agents_puis_le_stratege(monkeypatch):
    pool = {f"M{i} vs X{i}": [_cand(f"M{i} vs X{i}", "Total", "Over", 1.7, 74.0, 6.0)] for i in range(3)}
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    prompts = []

    def appel(prompt, max_tokens=0, json_attendu=False):
        prompts.append(prompt)
        if "agent spécialiste" in prompt:
            return json.dumps({"ecartes": [], "avis": []})
        return json.dumps({"analyse_matchs": [], "coupons": [
            {"profil": "p", "strategie": "s", "jambes": [{"id": "P1", "raison": "r"}, {"id": "P2", "raison": "r"}]}]})

    profils = [{"cle": "p", "nom": "P", "cote_min": 1.0, "cote_max": 99.0, "nb_jambes_min": 2, "nb_jambes": 2}]
    st.composer_coupons(pool, profils, appel=appel)
    assert any("agent spécialiste" in p for p in prompts)
    assert any("MISSION : composer" in p for p in prompts)


def test_desactivable_par_variable(monkeypatch):
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "0")
    assert af.actif() is False


def test_les_agents_travaillent_en_parallele(monkeypatch):
    import threading
    import time
    pool = {
        "A vs B": [_cand("A vs B", "Double Chance", "1X", 1.8, 76.0, 8.0)],
        "C vs D": [_cand("C vs D", "Total", "Over", 1.7, 74.0, 6.0)],
        "E vs F": [_cand("E vs F", "Total Corners", "Under", 1.9, 72.0, 5.0)],
        "G vs H": [_cand("G vs H", "BTTS", "Yes", 1.9, 71.0, 5.0)],
    }
    catalogue, _ = st.construire_catalogue(pool)
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    barriere = threading.Barrier(4, timeout=5)  # les 4 agents doivent être EN VOL en même temps
    fils, passes = set(), []

    def appel(prompt, max_tokens=0, json_attendu=False):
        fils.add(threading.current_thread().name)
        barriere.wait()
        passes.append(1)
        time.sleep(0.05)
        return json.dumps({"ecartes": [], "avis": []})

    af.revoir_catalogue(catalogue, appel=appel)
    assert len(fils) == 4 and len(passes) == 4  # sans parallélisme, la barrière casserait
