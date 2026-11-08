import pytest


@pytest.fixture(autouse=True)
def planchers_de_remuneration_neutralises(monkeypatch):
    """Les tests des utilités et des règles utilisent des cotes arbitraires (1.05 à 6) : les planchers de rémunération de production (1.20 par jambe, 1.60 par coupon) y sont
    neutralisés, et testés explicitement dans test_plancher_remuneration_moteurs.py."""
    from moteur import profils_risque as pr
    monkeypatch.setattr(pr, "COTE_MIN_JAMBE", 0.0)
    monkeypatch.setattr(pr, "COTE_TOTALE_MIN_COUPON", 0.0)
    monkeypatch.setattr(pr, "MAX_JAMBES_REMPLISSAGE", 0)   # limite des jambes de remplissage : testée explicitement dans bet_agent/test_ameliorations_07_11.py
