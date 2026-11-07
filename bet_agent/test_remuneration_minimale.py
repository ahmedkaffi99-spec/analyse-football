"""07/11/2026 — plancher de rémunération d'un coupon (un coupon à 1.04 est refusé) et information probabilité / valeur espérée renvoyée à l'IA.
Tests locaux ; ils ne prouvent aucune rentabilité prédictive."""
import pytest

import agent_pilote as pilote
import agent_strategie as st
import profils_smart

PROFIL = dict(profils_smart.profils(contraintes=False)[0])


def sel(match, cote, proba=95.0, cat="Total", selection="Over"):
    return {"match": match, "pick": {"marche": cat, "selection": selection, "cote": cote, "categorie": cat, "proba_modele_pct": proba,
                                     "handicap": None, "edge_pct": 1.0}, "home_nom": match, "fixture_id_oddspapi": match}


def catalogue(cotes, probas=None):
    return {f"P{i + 1}": sel(f"M{i}", c, (probas or [95.0] * len(cotes))[i], cat=("Total", "BTTS", "Double Chance", "Total Corners")[i % 4],
                             selection=("Over", "Yes", "1X", "Under")[i % 4]) for i, c in enumerate(cotes)}


def prop(ids):
    return {"coupons": [{"profil": PROFIL["cle"], "strategie": "s", "jambes": [{"id": i, "raison": "ok"} for i in ids]}]}


@pytest.fixture(autouse=True)
def plancher_actif(monkeypatch):
    monkeypatch.setattr(st, "COTE_TOTALE_MIN_COUPON", 1.60)     # la valeur de production (le conftest la neutralise pour les anciens tests)
    monkeypatch.setattr(st, "COTE_MIN_JAMBE_AGENT", 1.0)        # on isole ici le plancher de cote TOTALE


def test_un_coupon_a_1_04_est_refuse_avec_une_explication_utile():
    acceptes, problemes, calculs = st.valider(prop(["P1", "P2"]), catalogue([1.02, 1.02]), [PROFIL])
    assert not acceptes
    assert any("sous le plancher de rémunération 1.6" in p and "probabilité ET la rémunération" in p for p in problemes), problemes
    assert any("cote totale 1.04" in c for c in calculs)


def test_un_coupon_correctement_remunere_est_accepte():
    acceptes, problemes, _ = st.valider(prop(["P1", "P2"]), catalogue([1.30, 1.30]), [PROFIL])    # 1,69
    assert PROFIL["cle"] in acceptes, problemes


@pytest.mark.parametrize("cotes,accepte", [([1.25, 1.25], False), ([1.27, 1.27], True), ([1.2, 1.2, 1.2], True)])
def test_frontiere_du_plancher(cotes, accepte):
    ids = [f"P{i + 1}" for i in range(len(cotes))]
    acceptes, _, _ = st.valider(prop(ids), catalogue(cotes), [PROFIL])
    assert (PROFIL["cle"] in acceptes) is accepte


def test_aucun_plafond_une_cote_tres_haute_reste_acceptee():
    acceptes, _, _ = st.valider(prop(["P1", "P2", "P3"]), catalogue([20.0, 20.0, 20.0]), [PROFIL])
    assert PROFIL["cle"] in acceptes


def test_le_plancher_est_desactivable(monkeypatch):
    monkeypatch.setattr(st, "COTE_TOTALE_MIN_COUPON", 0.0)
    acceptes, _, _ = st.valider(prop(["P1", "P2"]), catalogue([1.02, 1.02]), [PROFIL])
    assert PROFIL["cle"] in acceptes


def test_un_profil_personnalise_garde_son_propre_plancher_explicite():
    perso = dict(PROFIL, cote_totale_min=3.0)
    _, problemes, _ = st.valider(prop(["P1", "P2"]), catalogue([1.5, 1.5]), [perso])                # 2,25 < 3 : message du profil, pas celui du plancher général
    assert any("trop basse (minimum 3 pour ce profil)" in p for p in problemes) and not any("plancher de rémunération" in p for p in problemes)


def test_probabilite_jointe_et_valeur_esperee_renvoyees_a_l_ia():
    _, _, calculs = st.valider(prop(["P1", "P2"]), catalogue([1.6, 1.6], [80.0, 70.0]), [PROFIL])
    ligne = next(c for c in calculs if "cote totale" in c)
    assert "probabilité jointe 56.0%" in ligne and "valeur espérée +43%" in ligne                      # 0,56 × 2,56 − 1 = +0,43


def test_rentabilite_sans_probabilite_n_invente_rien():
    s1, s2 = sel("A", 1.5), sel("B", 1.5)
    s2["pick"]["proba_modele_pct"] = None
    assert st.rentabilite([s1, s2]) == (None, None) and st.rentabilite([]) == (None, None)
    p, ev = st.rentabilite([sel("A", 2.0, 50.0), sel("B", 2.0, 50.0)])
    assert p == pytest.approx(0.25) and ev == pytest.approx(0.0)


def test_lecture_robuste_de_la_variable(monkeypatch):
    import importlib
    try:
        for valeur, attendu in (("2.5", 2.5), ("abc", 1.6), ("", 1.6), ("0", 0.0), ("-3", 0.0)):
            monkeypatch.setenv("COTE_TOTALE_MIN_COUPON", valeur)
            importlib.reload(st)
            assert st.COTE_TOTALE_MIN_COUPON == attendu, valeur
    finally:
        monkeypatch.delenv("COTE_TOTALE_MIN_COUPON", raising=False)
        importlib.reload(st)


def test_les_consignes_de_l_ia_parlent_de_probabilite_et_de_remuneration():
    prompt = pilote.construire_prompt_systeme(profils_smart.profils(contraintes=False))
    assert "COMPTE SUR LA PROBABILITÉ ET SUR LA RÉMUNÉRATION" in prompt and "1.04" in prompt and "valeur espérée" in prompt
    texte = st.construire_prompt({"A - B": [sel("A - B", 1.5)]}, profils_smart.profils(contraintes=False), "\n- P1 : ...")
    assert "RÉMUNÉRATION" in texte and "1.6" in texte and "1.04" in texte and "valeur espérée" in texte
