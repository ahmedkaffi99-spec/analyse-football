"""Correctifs du 07/11/2026 (runs 279-280) côté agent : cote arrondie acceptée, coût DeepSeek réaliste. Tests locaux ; aucune preuve de rentabilité."""
import pytest

import agent_pilote as pilote
import agent_strategie as st


@pytest.mark.parametrize("raison,cote,faute", [
    ("Real gagne partout, cote 1.2 très solide : à 1.2", 1.24, False),     # run 280 : cote arrondie, coupon valable rejeté à tort
    ("valeur à 1.65", 1.65, False),
    ("pari à 1.7", 1.65, False),
    ("pari à 1.65", 3.16, True),                                            # cote nettement différente : raison écrite pour un autre pari
    ("pari à 1.5", 1.24, True),
    ("cote @ 2.1 et @ 3.16", 3.16, False),                                  # une des cotes citées correspond
])
def test_tolerance_sur_la_cote_citee(raison, cote, faute):
    pick = {"cote": cote, "selection": "Over"}
    assert (st.incoherence_raison(raison, pick) is not None) is faute


def test_le_sens_oppose_est_toujours_detecte():
    assert st.incoherence_raison("under 2.5 à 1.65", {"cote": 1.65, "selection": "Over"}) is not None


def test_cout_deepseek_estime_de_facon_realiste(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_PRIX_ENTREE_USD_M", raising=False)
    monkeypatch.delenv("DEEPSEEK_PRIX_SORTIE_USD_M", raising=False)
    pilote._secours.update(actif=False, choix=None)
    usage = {"prompt_tokens": 204703, "completion_tokens": 21245}               # tokens du run 280
    cout = pilote._cout_appel(usage)
    assert 0.05 < cout < 0.15                                                   # ~0,09 $ au lieu de 0,93 $ (prix « premium » prudents)
    pilote._secours.update(actif=True, choix=None)                               # route de secours/OpenRouter sans coût renvoyé : estimation PRUDENTE conservée
    assert pilote._cout_appel(usage) == pytest.approx((204703 * 3 + 21245 * 15) / 1e6)
    pilote._secours.update(actif=False, choix=None)
    assert pilote._cout_appel({"prompt_tokens": 1000, "cost": 0.0}) == 0.0       # un vrai zéro du fournisseur reste zéro
    assert pilote._cout_appel({}) > 0                                            # aucune donnée : jamais gratuit
