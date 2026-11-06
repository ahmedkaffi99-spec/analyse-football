"""Suivi en ombre : détails des paris écartés, mesure des tokens/coût OpenRouter, plafond de dépense."""
import pytest

import ombre


def _cand(match, categorie, selection, cote=1.4, edge=1.0, proba=72.0):
    return {"match": match, "home_nom": match.split(" vs ")[0], "fixture_id_oddspapi": "f1",
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "selection": selection, "cote": cote,
                     "proba_modele_pct": proba, "edge_pct": edge}}


def test_details_ecartes_distingue_veto_python_et_ia(monkeypatch):
    import agents_familles
    monkeypatch.setattr(agents_familles, "veto_python", lambda pick: "edge suspect" if pick["edge_pct"] > 5 else None)
    catalogue = {"P1": _cand("A vs B", "Total", "Over", edge=9.0), "P2": _cand("C vs D", "Total", "Under", edge=1.0),
                 "P3": _cand("E vs F", "Total", "Over")}
    sortie = ombre.details_ecartes(catalogue, {"P1", "P2"}, {"P1": "[veto] x", "P2": "[IA] y"})
    assert {e["id"]: e["origine"] for e in sortie} == {"P1": "veto_python", "P2": "ia_famille"}
    assert all(e["raison"] for e in sortie)


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


def test_modeles_ombre_vide_par_defaut(monkeypatch):
    monkeypatch.delenv("MODELES_OMBRE", raising=False)
    assert ombre.modeles_ombre() == []
    monkeypatch.setenv("MODELES_OMBRE", " a/b , base ,")
    assert ombre.modeles_ombre() == ["a/b", "base"]
