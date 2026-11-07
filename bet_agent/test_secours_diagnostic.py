"""Diagnostic des échecs de fournisseur (07/11/2026) : la vraie cause n'est jamais perdue ni masquée par une bascule. Tests locaux."""
import pytest

import agent_pilote as pilote


class Rep:
    def __init__(self, code):
        self.status_code, self.content, self.text = code, b"x", f"corps {code}"

    def json(self):
        return {"error": {"message": f"erreur {self.status_code}"}}


def test_la_cause_de_l_echec_deepseek_est_conservee_et_remontee(monkeypatch):
    pilote._secours.update(actif=False, choix=None, cause_principale=None)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        pilote._appel_api("cle", [{"role": "user", "content": "x"}], 1000, poster=lambda *a, **k: Rep(500), pause=lambda s: None)
    assert "HTTP 500" in pilote._secours["cause_principale"] and pilote._secours["actif"] is False
    pilote._secours.update(actif=False, choix=None, cause_principale=None)


def test_l_erreur_du_modele_impose_nomme_le_modele_et_le_code_http(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-or")
    monkeypatch.setenv("PILOTE_MODELE", "google/gemini-4-argon")
    pilote._secours.update(actif=True, choix=None, cause_principale=None)
    with pytest.raises(RuntimeError) as e:
        pilote._appel_api(None, [{"role": "user", "content": "x"}], 1000, poster=lambda *a, **k: Rep(401), pause=lambda s: None)
    assert "google/gemini-4-argon" in str(e.value) and "HTTP 401" in str(e.value) and "aucun repli" in str(e.value)
    pilote._secours.update(actif=False, choix=None, cause_principale=None)


def test_un_echec_reseau_repete_remonte_sans_changer_de_modele(monkeypatch):
    import requests
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-or")
    monkeypatch.setenv("PILOTE_MODELE", "anthropic/claude-sonnet-5.5")
    pilote._secours.update(actif=True, choix=None, cause_principale=None)
    appels = []

    def poster(url, headers=None, json=None, timeout=None):
        appels.append(json["model"])
        raise requests.Timeout("lent")
    with pytest.raises(RuntimeError, match="Timeout"):
        pilote._appel_api(None, [{"role": "user", "content": "x"}], 1000, poster=poster, pause=lambda s: None)
    assert set(appels) == {"anthropic/claude-sonnet-5.5"} and len(appels) == 5            # 5 essais du MÊME modèle, aucun autre
    pilote._secours.update(actif=False, choix=None, cause_principale=None)
