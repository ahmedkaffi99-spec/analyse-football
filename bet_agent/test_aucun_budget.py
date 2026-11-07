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


def test_aucun_repli_meme_avec_toutes_les_cles_presentes(monkeypatch):
    for cle in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(cle, "x")
    monkeypatch.setenv("UTILISER_OPENROUTER", "1")
    monkeypatch.delenv("PILOTE_MODELE", raising=False)
    assert pilote._fournisseurs_secours() == []                                         # DeepSeek officiel seul : aucun autre fournisseur n'est jamais essayé


def test_solde_deepseek_epuise_le_run_echoue_avec_sa_vraie_cause_sans_bascule(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle-or")
    monkeypatch.delenv("PILOTE_MODELE", raising=False)
    pilote._secours.update(actif=False, choix=None, cause_principale=None)

    class Rep:
        status_code, content, text = 402, b"x", "Insufficient Balance"

        def json(self):
            return {"error": {"message": "Insufficient Balance"}}
    urls = []

    def poster(url, headers=None, json=None, timeout=None):
        urls.append(url)
        return Rep()
    with pytest.raises(RuntimeError, match="402"):
        pilote._appel_api("cle-ds", [{"role": "user", "content": "x"}], 1000, poster=poster, pause=lambda s: None)
    assert urls and all(u.startswith("https://api.deepseek.com") for u in urls)         # jamais OpenRouter
    pilote._secours.update(actif=False, choix=None, cause_principale=None)
