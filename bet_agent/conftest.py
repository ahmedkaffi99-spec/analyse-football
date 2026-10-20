import pytest


@pytest.fixture(autouse=True)
def agents_familles_desactives_par_defaut(monkeypatch):
    """Les tests existants du stratège comptent ses appels IA : les agents de famille
    (agents_familles.py) y sont désactivés, et activés explicitement dans leurs propres tests."""
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "0")
