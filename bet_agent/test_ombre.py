"""Suivi en ombre : détails des paris écartés, mesure des tokens/coût OpenRouter, plafond de dépense."""
import pytest

import ombre


def _cand(match, categorie, selection, cote=1.4, edge=1.0, proba=72.0):
    return {"match": match, "home_nom": match.split(" vs ")[0], "fixture_id_oddspapi": "f1",
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "selection": selection, "cote": cote,
                     "proba_modele_pct": proba, "edge_pct": edge}}


class _Reponse:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def test_appel_openrouter_cumule_tokens_et_cout_puis_plafond():
    def poster(url, **kw):
        assert kw["json"]["usage"] == {"include": True} and "openrouter.ai" in url
        return _Reponse({"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "cost": 0.04}})
    appel = ombre.AppelOpenRouter("m/x", "cle", budget_usd=0.05, poster=poster)
    assert appel("p") == "{}" and appel("p") == "{}"
    assert (appel.tokens_entree, appel.tokens_sortie, appel.appels) == (2000, 400, 2)
    assert round(appel.cout_usd, 2) == 0.08
    with pytest.raises(ombre.BudgetEpuise):
        appel("p")


def test_composer_ombre_sans_cle_ou_modele_inconnu_ne_plante_pas():
    sortie = ombre.composer_ombre({}, [], {"P1": _cand("A vs B", "Total", "Over")}, "txt", modeles=["m/x"], cle="")
    assert sortie[0]["erreur"] == "OPENROUTER_API_KEY absente" and sortie[0]["coupons"] == []


def test_composer_ombre_parallele_borne_dans_le_temps(monkeypatch):
    """Un modèle trop lent est abandonné à l'échéance (erreur « délai dépassé ») sans bloquer les autres."""
    import time
    import agent_strategie

    def faux_composer(pool, profils, appel=None, nb_tours=2, catalogue_pret=None, controle_budget=True, diagnostic=None):
        if appel == "lent":
            time.sleep(5)
        return {"coupons": {}, "analyse_matchs": []}
    monkeypatch.setattr(agent_strategie, "composer_coupons", faux_composer)
    monkeypatch.setattr(ombre.st, "composer_coupons", faux_composer)
    debut = time.time()
    sortie = ombre.composer_ombre({}, [], {"P1": _cand("A vs B", "Total", "Over")}, "txt", modeles=["base"], appel_base="lent",
                                  duree_max_s=0.4)
    assert time.time() - debut < 2
    assert "délai dépassé" in sortie[0]["erreur"]


def test_appel_openrouter_repli_sans_raisonnement_si_400():
    appels = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}}

    def poster(url, **kw):
        appels.append("reasoning" in kw["json"])
        return R(400 if "reasoning" in kw["json"] else 200)
    assert ombre.AppelOpenRouter("m/x", "cle", 1.0, poster=poster)("p") == "ok"
    assert appels == [True, False]


def test_appel_openrouter_echeance_depassee():
    appel = ombre.AppelOpenRouter("m/x", "cle", 1.0, poster=lambda *a, **k: None, echeance=0)
    with pytest.raises(TimeoutError):
        appel("p")


def test_composer_ombre_ignore_le_budget_de_production_et_explique_l_absence_de_coupon(monkeypatch):
    """Le 06/11 : budget IA de production épuisé => aucun appel, aucun message. Désormais le budget de production est ignoré
    et un modèle sans coupon reçoit une explication."""
    import agent_strategie
    vus = {}

    def faux_composer(pool, profils, appel=None, nb_tours=2, catalogue_pret=None, controle_budget=True, diagnostic=None):
        vus["controle_budget"] = controle_budget
        try:
            appel("p", 100)
        except Exception:
            pass
        return None
    monkeypatch.setattr(agent_strategie, "composer_coupons", faux_composer)
    monkeypatch.setattr(ombre.st, "composer_coupons", faux_composer)

    def poster(url, **kw):
        raise ConnectionError("réseau coupé")
    monkeypatch.setattr(ombre, "AppelOpenRouter", lambda m, c, b, echeance=None: _CLASSE_ORIGINALE(m, c, b, poster=poster, echeance=echeance))
    sortie = ombre.composer_ombre({}, [], {"P1": _cand("A vs B", "Total", "Over")}, "txt", modeles=["m/x"], cle="k")
    assert vus["controle_budget"] is False
    assert "appel(s) en échec : ConnectionError" in sortie[0]["erreur"]


_CLASSE_ORIGINALE = ombre.AppelOpenRouter


def test_rejets_de_python_dans_l_erreur_du_modele(monkeypatch):
    import agent_strategie

    def faux_composer(pool, profils, appel=None, nb_tours=2, catalogue_pret=None, controle_budget=True, diagnostic=None):
        appel("p", 100)
        diagnostic.extend(["P3 : même pari exact déjà pris", "2 paris sur A vs B (maximum 1)"])
        return None

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.001}}
    monkeypatch.setattr(agent_strategie, "composer_coupons", faux_composer)
    monkeypatch.setattr(ombre.st, "composer_coupons", faux_composer)
    monkeypatch.setattr(ombre, "AppelOpenRouter", lambda m, c, b, echeance=None: _CLASSE_ORIGINALE(m, c, b, poster=lambda *a, **k: R(), echeance=echeance))
    sortie = ombre.composer_ombre({}, [], {"P1": _cand("A vs B", "Total", "Over")}, "txt", modeles=["m/x"], cle="k")
    assert "rejets de Python : P3 : même pari exact déjà pris | 2 paris sur A vs B" in sortie[0]["erreur"]
