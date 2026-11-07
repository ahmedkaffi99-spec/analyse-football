"""07/11/2026 — aucun plafond de dépense ; repli DeepSeek -> DeepSeek via OpenRouter quand le solde DeepSeek est épuisé (HTTP 402, runs 282 et 284). Tests locaux."""
import os
from unittest import mock

import pytest

import agent_pilote as pilote
import budget_ia
import ombre


def test_repartition_sans_plafond_par_modele_ni_budget():
    assert budget_ia.repartir(None, ["a", "b"], None) == ({"a": None, "b": None}, [])
    budgets, ignores = budget_ia.repartir(2.0, ["a", "b"], None, minimum=0.1)         # un restant fourni sans plafond propre ne plante plus
    assert budgets == {"a": 1.0, "b": 1.0} and ignores == []


def test_le_vote_et_le_mode_modele_seul_n_ont_aucun_plafond_meme_si_la_variable_existe(monkeypatch):
    monkeypatch.setenv("OMBRE_BUDGET_USD", "0.01")
    appel = ombre.AppelOpenRouter("m", "cle", None)
    appel.cout_usd = 1000.0
    with mock.patch.object(appel, "_poster", return_value=mock.Mock(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 5.0}}, raise_for_status=lambda: None)):
        assert appel("prompt") == "ok"                                                  # aucun BudgetEpuise : le plafond n'existe plus
    assert os.getenv("OMBRE_BUDGET_USD") == "0.01"


def test_le_pilote_ne_s_arrete_jamais_pour_une_raison_de_budget(monkeypatch):
    monkeypatch.delenv("COUTS_FICHIER", raising=False)
    pilote._usage_pilote.update(appels=0, tokens_entree=0, tokens_sortie=0, cout_usd=0.0, appels_cout_estime=0)
    pilote._budget_pilote.update(restant_usd=None, etat={})
    reponse = ({"choices": [{"message": {"role": "assistant", "content": "…"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 99.0}}, 65536)
    with mock.patch.object(pilote, "MAX_ETAPES", 4), mock.patch.object(pilote, "_appel_api", side_effect=[reponse] * 8) as appel:
        resultat = pilote.piloter("cle", {}, lambda: False, "mission")
    assert appel.call_count == 4 and resultat["arret"] != "budget IA atteint"           # seule la limite d'étapes arrête, jamais l'argent


def test_deepseek_via_openrouter_est_le_premier_repli_quand_le_solde_deepseek_est_epuise(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-or")
    monkeypatch.delenv("UTILISER_OPENROUTER", raising=False)
    monkeypatch.delenv("PILOTE_MODELE", raising=False)
    courses = pilote._fournisseurs_secours()
    assert courses[0][0] == "OpenRouter" and courses[0][3] == pilote.MODELE_OPENROUTER_DEEPSEEK and courses[0][2] == "cle-or"
    assert courses[0][4].get("usage") == {"include": True}                              # le coût réel est demandé
    assert all(c[3] == pilote.MODELE_OPENROUTER_DEEPSEEK for c in courses if c[0] == "OpenRouter")   # pas de modèle gratuit sans UTILISER_OPENROUTER


def test_sans_cle_openrouter_aucun_repli_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("PILOTE_MODELE", raising=False)
    assert all(c[0] != "OpenRouter" for c in pilote._fournisseurs_secours())


def test_solde_deepseek_epuise_le_run_continue_avec_le_meme_modele_via_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-or")
    monkeypatch.delenv("UTILISER_OPENROUTER", raising=False)
    monkeypatch.delenv("PILOTE_MODELE", raising=False)
    pilote._secours.update(actif=False, choix=None, cause_principale=None)

    class Rep:
        def __init__(self, code, corps):
            self.status_code, self.corps, self.content, self.text = code, corps, b"x", str(corps)

        def json(self):
            return self.corps
    appels = []

    def poster(url, headers=None, json=None, timeout=None):
        appels.append((url, json["model"]))
        if "deepseek.com" in url:
            return Rep(402, {"error": {"message": "Insufficient Balance"}})
        return Rep(200, {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"cost": 0.01}})
    data, _ = pilote._appel_api("cle-ds", [{"role": "user", "content": "x"}], 1000, poster=poster, pause=lambda s: None)
    assert data["choices"][0]["message"]["content"] == "ok"
    assert appels[0][0].startswith("https://api.deepseek.com") and appels[-1] == ("https://openrouter.ai/api/v1/chat/completions", pilote.MODELE_OPENROUTER_DEEPSEEK)
    assert "402" in pilote._secours["cause_principale"]                                 # la cause de la bascule est conservée
    pilote._secours.update(actif=False, choix=None, cause_principale=None)
