"""Fiabilité de l'envoi Telegram (06/11/2026) : nouvelles tentatives sans risque de doublon, et envoi partiel connu du run."""
import json
from unittest import mock

import pytest
import requests

import agent_pilote as pilote
import analyser_et_envoyer as ae
import collecte_donnees as cd


class _Rep:
    def __init__(self, code, texte="", donnees=None):
        self.status_code, self.text, self._d = code, texte, donnees or {}

    def json(self):
        return self._d


@pytest.fixture(autouse=True)
def _jeton(monkeypatch):
    monkeypatch.setattr(ae, "TELEGRAM_TOKEN", "jeton-test")
    monkeypatch.setattr(ae, "TELEGRAM_TENTATIVES", 3)


def _envoyer(reponses):
    with mock.patch.object(ae.requests, "post", side_effect=reponses) as post:
        ok = ae._envoyer_a_un_chat("123", "bonjour")
    return ok, post.call_count


def test_succes_direct_une_seule_requete():
    assert _envoyer([_Rep(200)]) == (True, 1)


def test_429_est_retente_puis_reussit():
    ok, appels = _envoyer([_Rep(429, "trop de requetes", {"parameters": {"retry_after": 1}}), _Rep(200)])
    assert ok and appels == 2


def test_erreur_de_passerelle_503_retentee_jusqu_a_trois_fois_puis_echec():
    ok, appels = _envoyer([_Rep(503), _Rep(503), _Rep(503)])
    assert not ok and appels == 3


def test_connexion_refusee_est_retentee():
    ok, appels = _envoyer([requests.exceptions.ConnectionError("refusée"), _Rep(200)])
    assert ok and appels == 2


def test_delai_de_lecture_depasse_n_est_jamais_retente_pour_eviter_un_doublon():
    ok, appels = _envoyer([requests.exceptions.ReadTimeout("lent"), _Rep(200)])
    assert not ok and appels == 1


def test_erreur_definitive_400_et_403_non_retentees():
    assert _envoyer([_Rep(400, "chat not found"), _Rep(200)]) == (False, 1)
    assert _envoyer([_Rep(403, "bot bloqué"), _Rep(200)]) == (False, 1)


def test_repli_markdown_en_texte_brut_conserve():
    ok, appels = _envoyer([_Rep(400, "Bad Request: can't parse entities"), _Rep(200)])
    assert ok and appels == 2


def test_envoi_partiel_memorise_le_detail(monkeypatch):
    monkeypatch.setattr(ae.time, "sleep", lambda s: None)
    resultats = iter([True, False, True])
    monkeypatch.setattr(ae, "notifier_telegram", lambda m: next(resultats))
    assert ae.agent5_envoyer_coupons(["coupon 1", "coupon 2", "coupon 3"]) is False
    assert ae.DERNIER_ENVOI == (2, 3)


def test_envoi_complet_memorise_le_detail(monkeypatch):
    monkeypatch.setattr(ae.time, "sleep", lambda s: None)
    monkeypatch.setattr(ae, "notifier_telegram", lambda m: True)
    assert ae.agent5_envoyer_coupons(["a", "b"]) is True
    assert ae.DERNIER_ENVOI == (2, 2)
