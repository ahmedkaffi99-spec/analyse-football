import json

import pytest

from app.services import protocole_comparatif as pc
from app.services import suivi_modeles as sm


def sel(m, marche="1X2", selection="1", cote=2.0, proba=50.0, h=None):
    return {"match_id": m, "marche": marche, "selection": selection, "cote": cote, "proba_pct": proba, "handicap": h}


def coupon(modele="openai/gpt-6.1-sol", sels=None, jour="2026-11-10", profil="p1"):
    return sm.nouveau_coupon("P", jour, modele, profil, sels or [sel(1), sel(2)])


# --- attribution ---
@pytest.mark.parametrize("ident,cle", [("deepseek-flash", "deepseek"), ("deepseek/deepseek-v4.1-flash", "deepseek"), ("openai/gpt-6.1-sol", "gpt"),
                                       ("gpt-6.1-sol", "gpt"), ("anthropic/claude-sonnet-5.5", "claude"), ("google/gemini-4-argon", "gemini")])
def test_modele_canonique(ident, cle):
    assert sm.modele_canonique(ident) == cle


@pytest.mark.parametrize("ident", ["base", "vote", "ecartes_ia", None, "gpt-3.1"])
def test_modele_inconnu_refuse(ident):
    with pytest.raises(sm.AttributionRefusee):
        sm.modele_canonique(ident)


def test_vote_collectif_refuse():
    with pytest.raises(sm.AttributionRefusee):
        sm.nouveau_coupon("P", "2026-11-10", "openai/gpt-6.1-sol", "p", [sel(1)], source="vote_collectif")
    r = sm.Registre()
    c = coupon()
    c["source"] = "vote_collectif"
    with pytest.raises(sm.AttributionRefusee):
        r.ajouter(c)


def test_rien_n_est_invente():
    with pytest.raises(ValueError):
        sm.nouveau_coupon("P", "2026-11-10", "gpt-6.1-sol", "p", [sel(1, cote=None)])
    c = sm.nouveau_coupon("P", "2026-11-10", "gpt-6.1-sol", "p", [sel(1, proba=None), sel(2)])
    assert c["proba_combinee_pct"] is None   # une probabilité manquante n'est pas remplacée


def test_adaptateur_ignore_base_et_vote():
    res = [{"modele": "base", "coupons": [{"profil": "a", "selections": [{"pick": sel(1)}]}]},
           {"modele": "google/gemini-4-argon", "coupons": [{"profil": "a", "selections": [{"pick": sel(1)}, {"pick": sel(2)}]}], "cout_usd": 0.2}]
    cs, ign = sm.depuis_resultats_ombre("P", "2026-11-10", res, run_id=9)
    assert [c["modele"] for c in cs] == ["gemini"] and ign == ["base"] and cs[0]["couts"]["cout_usd"] == 0.2


# --- anti-doublons ---
def test_doublon_ignore_et_ordre_sans_importance():
    r = sm.Registre()
    assert r.ajouter(coupon(sels=[sel(1), sel(2)])) is True
    assert r.ajouter(coupon(sels=[sel(2), sel(1)])) is False   # mêmes sélections, autre ordre
    assert r.ajouter(coupon(sels=[sel(1), sel(3)])) is True
    assert r.ajouter(coupon(modele="google/gemini-4-argon", sels=[sel(1), sel(2)])) is True   # autre modèle : pas un doublon
    assert len(r.coupons) == 3


def test_empreinte_ignore_la_cote():
    assert sm.empreinte([sel(1, cote=2.0)]) == sm.empreinte([sel(1, cote=2.1)])


# --- intégrité et résultats ---
def test_aller_retour_jsonl():
    r = sm.Registre([coupon(), coupon(sels=[sel(5)])])
    r2 = sm.Registre.depuis_jsonl(r.vers_jsonl())
    assert [c["cle_unique"] for c in r2.coupons] == [c["cle_unique"] for c in r.coupons]


@pytest.mark.parametrize("res,att", [(["gagne", "gagne"], "gagne"), (["gagne", "perdu"], "perdu"), (["gagne", "en_attente"], "en_attente"),
                                     (["perdu", "en_attente"], "perdu"), (["gagne", "push"], "gagne"), (["push", "push"], "annule"),
                                     (["gagne", "non_verifiable"], "en_attente")])
def test_statut_coupon(res, att):
    assert sm.statut_coupon([{"resultat": r} for r in res]) == att


def test_enregistrer_resultats_partiels():
    r = sm.Registre([coupon(sels=[sel(1), sel(2)])])
    assert r.enregistrer_resultats({1: {("1X2", "1", None): "gagne"}}) == 1
    assert r.coupons[0]["statut"] == "en_attente"
    assert r.enregistrer_resultats({2: {("1X2", "1", None): "gagne"}}) == 1
    assert r.coupons[0]["statut"] == "gagne"
    assert r.enregistrer_resultats({1: {("1X2", "1", None): "perdu"}}) == 0   # un résultat déjà jugé n'est pas réécrit


def test_cote_effective_push_et_demi():
    c = coupon(sels=[sel(1, cote=2.0), sel(2, cote=3.0)])
    c["jambes"][0]["resultat"], c["jambes"][1]["resultat"] = "push", "gagne"
    assert sm.cote_effective(c) == 3.0
    c["jambes"][1]["resultat"] = "demi_gagne"
    assert sm.cote_effective(c) == 2.0


# --- statistiques ---
def regle(statut, cote_jambe=2.0, matchs=(1,), jour="2026-11-10", modele="openai/gpt-6.1-sol", proba=50.0):
    c = sm.nouveau_coupon("P", jour, modele, "p", [sel(m, cote=cote_jambe, proba=proba) for m in matchs])
    for j in c["jambes"]:
        j["resultat"] = "gagne" if statut == "gagne" else "perdu"
    c["statut"] = statut
    return c


def test_wilson():
    assert sm.wilson(0, 0) is None
    lo, hi = sm.wilson(1, 15)
    assert (lo, hi) == (1.2, 29.8)   # valeur du rapport de phase 4 pour 1/15


def test_stats_roi_et_exclusion_des_non_regles():
    cs = [regle("gagne", 3.0, (1,)), regle("perdu", 2.0, (2,)), coupon()]   # 3e coupon en attente
    s = sm.statistiques_modele(cs)
    assert (s["n_total"], s["n_regles"], s["n_en_attente"], s["gagnes"]) == (3, 2, 1, 1)
    assert s["win_rate_pct"] == 50.0 and s["profit_theorique"] == 1.0 and s["roi_pct"] == 50.0
    assert s["cote_moyenne"] == 2.5 and s["suffisant"] is False
    assert any("insuffisant" in l for l in s["limites"]) and any("non réglé" in l for l in s["limites"])


def test_stats_vide():
    s = sm.statistiques_modele([])
    assert s["win_rate_pct"] is None and s["roi_pct"] is None and s["ic95_win_rate"] is None


def test_correlation_grappes():
    cs = [regle("perdu", matchs=(1, 2)), regle("perdu", matchs=(2, 3)), regle("gagne", matchs=(9,))]
    assert sm.nb_grappes(cs) == 2
    s = sm.statistiques_modele(cs)
    assert s["grappes"] == 2 and any("corrélées" in l for l in s["limites"])
    assert sm.nb_grappes([regle("perdu", matchs=(1,), jour="2026-11-10"), regle("perdu", matchs=(1,), jour="2026-11-11")]) == 2   # même id, autre jour


def test_proba_absente_non_estimee():
    c = regle("gagne")
    for j in c["jambes"]:
        j["proba_pct"] = None
    c["proba_combinee_pct"] = None
    s = sm.statistiques_modele([c, regle("perdu", matchs=(2,))])
    assert s["n_avec_proba"] == 1 and any("absente" in l for l in s["limites"])


def test_marches():
    c = regle("gagne")
    c["jambes"][0]["marche"] = "BTTS"
    s = sm.statistiques_modele([c])
    assert s["marches"]["BTTS"]["jambes_gagnees" if False else "gagnees"] == 1


def test_aucun_gagnant_sous_le_seuil():
    r = sm.Registre()
    for i in range(sm.SEUIL_ECHANTILLON):
        r.ajouter(regle("gagne" if i % 5 == 0 else "perdu", matchs=(100 + i,), modele="openai/gpt-6.1-sol"))
    out = sm.comparer(r)
    assert out["classement_autorise"] is False and "AUCUN CLASSEMENT" in out["verdict"]
    assert out["modeles"]["gpt"]["suffisant"] is True and out["modeles"]["claude"]["suffisant"] is False


def test_classement_autorise_si_quatre_suffisants():
    r = sm.Registre()
    for m in sm.MODELES:
        for i in range(sm.SEUIL_ECHANTILLON):
            r.ajouter(regle("perdu", matchs=(i,), jour=f"2026-11-{10 + i % 10}", modele=sm.MODELES[m]["ids"][0]))
    assert sm.comparer(r)["classement_autorise"] is True


# --- protocole ---
def test_plan_dix_jours_consecutifs():
    p = pc.plan("2026-11-10")
    assert len(p["jours"]) == 10 and p["jours"][0] == "2026-11-10" and p["jours"][-1] == "2026-11-19" and len(p["modeles"]) == 4


def test_controle_equite():
    cat = [{"match_id": 1, "marche": "1X2", "selection": "1", "cote": 2.0}]
    e = pc.empreinte_catalogue(cat)
    assert pc.controle_equite({m: e for m in sm.MODELES}) == []
    assert pc.controle_equite({"gpt": e, "claude": "autre", "gemini": e, "deepseek": e})
    assert "sans tirage" in pc.controle_equite({"gpt": e})[0]
    assert pc.empreinte_catalogue(cat) == pc.empreinte_catalogue(list(reversed(cat)))


def test_couverture_et_manques():
    r = sm.Registre([regle("gagne", matchs=(1,), modele="deepseek-flash")])
    cv = pc.couverture(r, pc.plan("2026-11-10")["jours"])
    assert cv["total"]["deepseek"] == 1 and cv["manque"]["deepseek"] == 29 and cv["manque"]["gpt"] == 30
