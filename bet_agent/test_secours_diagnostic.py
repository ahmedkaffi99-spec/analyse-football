"""Run 282 du 07/11/2026 : bascule DeepSeek -> Gemini en cours de run échouée (HTTP 400 thought_signature) et cause initiale perdue dans le message d'erreur. Tests locaux."""
import json
from types import SimpleNamespace

import pytest

import agent_pilote as pilote

HISTORIQUE = [
    {"role": "system", "content": "sys"}, {"role": "user", "content": "mission"},
    {"role": "assistant", "content": "", "reasoning_content": "pense", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "voir_catalogue", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": '{"catalogue": "P1 ..."}'},
]


def test_aplatir_outils_remplace_les_appels_structures_par_du_texte():
    plat = pilote._aplatir_outils(HISTORIQUE)
    assert all("tool_calls" not in m and m["role"] != "tool" for m in plat)
    assert "[appel d'outil voir_catalogue({})]" in plat[2]["content"] and plat[3] == {"role": "user", "content": '[résultat de l\'outil] {"catalogue": "P1 ..."}'}
    assert "tool_calls" in HISTORIQUE[2] and HISTORIQUE[3]["role"] == "tool"            # l'historique d'origine n'est pas modifié


class FausseReponse:
    def __init__(self, code, corps):
        self.status_code, self.corps, self.content = code, corps, b"x"
        self.text = json.dumps(corps)

    def json(self):
        return self.corps


def _courses(*specs):
    return [(nom, url, "cle", modele, {}) for nom, url, modele in specs]


def test_gemini_recoit_un_historique_aplati_pas_les_autres_fournisseurs(monkeypatch):
    envoyes = {}

    def poster(url, headers=None, json=None, timeout=None):
        envoyes[url] = json["messages"]
        return FausseReponse(200, {"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
    for url in ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "https://api.groq.com/openai/v1/chat/completions"):
        pilote._secours.update(actif=True, choix=None, cause_principale=None)
        monkeypatch.setattr(pilote, "_fournisseurs_secours", lambda url=url: _courses(("X", url, "m")))
        pilote._appel_secours(HISTORIQUE, 1000, poster=poster)
    gemini = envoyes["https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"]
    groq = envoyes["https://api.groq.com/openai/v1/chat/completions"]
    assert not any("tool_calls" in m or m["role"] == "tool" for m in gemini)
    assert any("tool_calls" in m for m in groq) and not any("reasoning_content" in m for m in groq)   # structure conservée, champ DeepSeek retiré


def test_l_erreur_finale_garde_la_cause_initiale_et_tous_les_essais(monkeypatch):
    def poster(url, headers=None, json=None, timeout=None):
        return FausseReponse(400, {"error": {"message": f"refus de {json['model']}"}})
    monkeypatch.setattr(pilote, "_fournisseurs_secours", lambda: _courses(("Groq", "https://g/x", "m1"), ("Gemini", "https://generativelanguage.googleapis.com/x", "m2")))
    pilote._secours.update(actif=True, choix=None, cause_principale="RuntimeError: DeepSeek HTTP 402 Insufficient Balance")
    with pytest.raises(RuntimeError) as e:
        pilote._appel_secours(HISTORIQUE, 1000, poster=poster)
    message = str(e.value)
    assert "cause initiale : RuntimeError: DeepSeek HTTP 402 Insufficient Balance" in message
    assert "Groq/m1" in message and "Gemini/m2" in message                              # les deux échecs, pas seulement le dernier


def test_la_cause_de_la_bascule_est_conservee(monkeypatch):
    def deepseek_en_panne(*a, **k):
        raise RuntimeError("DeepSeek HTTP 500 boom")
    monkeypatch.setattr(pilote, "_appel_deepseek", deepseek_en_panne)
    monkeypatch.setattr(pilote, "secours_disponible", lambda: True)
    monkeypatch.setattr(pilote, "_appel_secours", lambda *a, **k: ({"choices": []}, 100))
    pilote._secours.update(actif=False, choix=None, cause_principale=None)
    pilote._appel_api("cle", HISTORIQUE, 1000)
    assert pilote._secours["actif"] is True and "DeepSeek HTTP 500 boom" in pilote._secours["cause_principale"]
    pilote._secours.update(actif=False, choix=None, cause_principale=None)
