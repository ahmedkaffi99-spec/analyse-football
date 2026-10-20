import pytest


@pytest.fixture(autouse=True)
def agents_familles_desactives_par_defaut(monkeypatch):
    """Les tests existants du stratège comptent ses appels IA : les agents de famille
    (agents_familles.py) y sont désactivés, et activés explicitement dans leurs propres tests."""
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "0")


@pytest.fixture(autouse=True)
def fourchette_de_cote_par_jambe_neutralisee(monkeypatch):
    """Les tests existants du calcul utilisent des cotes arbitraires (1.08 à 9.0) : la fourchette
    par jambe de production (1.2-1.8, voir ae.COTE_MIN_JAMBE_DEFAUT) y est neutralisée, et testée
    explicitement dans test_fourchette_de_cote_par_jambe_1_2_a_1_8."""
    import analyser_et_envoyer as ae
    monkeypatch.setattr(ae, "COTE_MIN_JAMBE", 0.0)
    monkeypatch.setattr(ae, "COTE_MAX_JAMBE", 0.0)
