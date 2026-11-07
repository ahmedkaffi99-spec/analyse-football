"""Phase 4 (07/11/2026) — corrections contrôlées : durée, budget pendant l'exécution, coûts inconnus, coupons, Telegram, seuils, modèle pilote.
Tests locaux : aucun réseau, aucune clé, aucune écriture en production. Ils ne prouvent AUCUNE rentabilité prédictive."""
import importlib
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import agent_pilote as pilote
import agent_strategie as st
import analyser_et_envoyer as ae
import budget_ia
import profils_smart
import vote

RACINE = Path(__file__).resolve().parent.parent


# ---------- A. durée ----------
def test_duree_agent_par_defaut_inferieure_au_delai_du_job(monkeypatch):
    monkeypatch.delenv("AGENT_DUREE_MAX_MIN", raising=False)
    importlib.reload(pilote)
    try:
        assert pilote.DUREE_MAX_S == 45 * 60
    finally:
        importlib.reload(pilote)


def test_le_workflow_arrete_l_agent_avant_le_delai_du_job():
    import yaml
    wf = yaml.safe_load((RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["run"]
    duree_agent = float(job["env"]["AGENT_DUREE_MAX_MIN"])
    # marge pour la collecte, le vote (VOTE_DUREE_MAX_S 300 s), l'envoi et l'enregistrement
    assert duree_agent + 5 + 5 < job["timeout-minutes"]
    etapes = [e.get("name") for e in job["steps"]]
    assert "Finaliser le run (coûts conservés)" in etapes
    finale = next(e for e in job["steps"] if e.get("name") == "Finaliser le run (coûts conservés)")
    assert "always()" in str(finale["if"]) and "finaliser" in finale["run"]
    assert etapes.index("Finaliser le run (coûts conservés)") > etapes.index("Lancer le pipeline")


# ---------- B. budget pendant l'exécution, coûts inconnus ----------
def test_cout_inconnu_n_est_jamais_gratuit():
    assert budget_ia.cout_appel({"prompt_tokens": 1_000_000, "completion_tokens": 0}) == (3.0, True)
    assert budget_ia.cout_appel({"prompt_tokens": 0, "completion_tokens": 1_000_000}) == (15.0, True)
    cout, estime = budget_ia.cout_appel({})
    assert cout > 0 and estime is True                      # aucune donnée du tout : forfait minimal, jamais 0
    assert budget_ia.cout_appel({"prompt_tokens": 5}, 0.0123) == (0.0123, False)   # coût réel renvoyé : utilisé tel quel
    assert budget_ia.cout_appel({"prompt_tokens": 5}, 0.0) == (0.0, False)         # un vrai zéro du fournisseur reste zéro
    assert budget_ia.cout_appel({"prompt_tokens": 5}, "abc")[1] is True            # coût illisible : estimation
    assert budget_ia.cout_appel({"prompt_tokens": 5}, float("nan"))[1] is True
    assert budget_ia.cout_appel({"prompt_tokens": 5}, -1)[1] is True               # coût négatif invalide


def test_prix_par_defaut_remplacables(monkeypatch):
    monkeypatch.setenv("PRIX_DEFAUT_ENTREE_USD_M", "10")
    assert budget_ia.cout_appel({"prompt_tokens": 1_000_000})[0] == pytest.approx(10.0)
    monkeypatch.setenv("PRIX_DEFAUT_ENTREE_USD_M", "abc")
    assert budget_ia.cout_appel({"prompt_tokens": 1_000_000})[0] == pytest.approx(3.0)


def test_budget_atteint():
    assert budget_ia.budget_atteint(100.0, None) is False      # pas de plafond
    assert budget_ia.budget_atteint(0.0, 0.0) is True          # mode « aucune dépense payante »
    assert budget_ia.budget_atteint(0.0, -1) is True
    assert budget_ia.budget_atteint(0.99, 1.0) is False and budget_ia.budget_atteint(1.0, 1.0) is True


def _message_sans_outil(cout):
    return ({"choices": [{"message": {"role": "assistant", "content": "…"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cout}}, 65536)


def test_le_pilote_s_arrete_avant_l_appel_suivant_quand_le_budget_est_atteint(monkeypatch):
    monkeypatch.delenv("COUTS_FICHIER", raising=False)
    pilote._usage_pilote.update(appels=0, tokens_entree=0, tokens_sortie=0, cout_usd=0.0, appels_cout_estime=0)
    pilote._budget_pilote.update(restant_usd=0.4, etat={})
    with mock.patch.object(pilote, "_appel_api", side_effect=[_message_sans_outil(0.5), _message_sans_outil(0.5)]) as appel:
        resultat = pilote.piloter("cle", {}, lambda: False, "mission")
    assert appel.call_count == 1                                  # le second appel n'a PAS eu lieu
    assert resultat["arret"] == "budget IA atteint" and resultat["termine"] is False
    assert pilote._usage_pilote["cout_usd"] == pytest.approx(0.5)


def test_mode_sans_depense_aucun_appel(monkeypatch):
    pilote._usage_pilote.update(appels=0, tokens_entree=0, tokens_sortie=0, cout_usd=0.0, appels_cout_estime=0)
    pilote._budget_pilote.update(restant_usd=0.0, etat={})
    with mock.patch.object(pilote, "_appel_api") as appel:
        resultat = pilote.piloter("cle", {}, lambda: False, "mission")
    appel.assert_not_called()
    assert resultat["arret"] == "budget IA atteint"


def test_sans_plafond_le_pilote_n_est_pas_bride(monkeypatch):
    monkeypatch.delenv("COUTS_FICHIER", raising=False)
    pilote._usage_pilote.update(appels=0, tokens_entree=0, tokens_sortie=0, cout_usd=0.0, appels_cout_estime=0)
    pilote._budget_pilote.update(restant_usd=None, etat={})
    with mock.patch.object(pilote, "MAX_ETAPES", 3), mock.patch.object(pilote, "_appel_api", side_effect=[_message_sans_outil(5.0)] * 6) as appel:
        pilote.piloter("cle", {}, lambda: False, "mission")
    assert appel.call_count >= 3


def test_cout_du_pilote_estime_est_compte_et_signale(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_PRIX_ENTREE_USD_M", raising=False)
    monkeypatch.delenv("DEEPSEEK_PRIX_SORTIE_USD_M", raising=False)
    pilote._usage_pilote.update(appels=0, tokens_entree=0, tokens_sortie=0, cout_usd=0.0, appels_cout_estime=0)
    assert pilote._cout_appel({"prompt_tokens": 100_000, "completion_tokens": 10_000}) > 0
    assert pilote._usage_pilote["appels_cout_estime"] == 1


# ---------- D. coûts écrits au fil de l'eau ----------
def test_fichier_de_couts_ecriture_atomique_et_lecture(tmp_path, monkeypatch):
    chemin = tmp_path / "sous" / "couts.json"
    monkeypatch.setenv("COUTS_FICHIER", str(chemin))
    assert budget_ia.ecrire_couts({"run_id": 7, "pilote": {"cout_usd": 0.2}}) is True
    assert budget_ia.lire_couts() == {"run_id": 7, "pilote": {"cout_usd": 0.2}}
    assert not [p for p in chemin.parent.iterdir() if p.name.startswith(".couts_")]   # pas de fichier temporaire oublié
    budget_ia.ecrire_couts({"run_id": 7, "pilote": {"cout_usd": 0.9}})
    assert budget_ia.lire_couts()["pilote"]["cout_usd"] == 0.9


def test_fichier_de_couts_jamais_bloquant(tmp_path, monkeypatch):
    monkeypatch.delenv("COUTS_FICHIER", raising=False)
    assert budget_ia.ecrire_couts({"a": 1}) is False and budget_ia.lire_couts() is None
    (tmp_path / "x.json").write_text("{pas du json", encoding="utf-8")
    assert budget_ia.lire_couts(str(tmp_path / "x.json")) is None
    assert budget_ia.ecrire_couts({"a": 1}, str(tmp_path / "fichier" / "x.json")) is True


def test_le_pilote_ecrit_ses_couts_apres_chaque_appel(tmp_path, monkeypatch):
    monkeypatch.setenv("COUTS_FICHIER", str(tmp_path / "c.json"))
    pilote._usage_pilote.update(appels=0, tokens_entree=0, tokens_sortie=0, cout_usd=0.0, appels_cout_estime=0)
    pilote._budget_pilote.update(restant_usd=None, etat={})
    with mock.patch.object(pilote, "MAX_ETAPES", 2), mock.patch.object(pilote, "_appel_api", side_effect=[_message_sans_outil(0.1)] * 5):
        pilote.piloter("cle", {}, lambda: False, "mission")
    assert budget_ia.lire_couts()["pilote"]["cout_usd"] == pytest.approx(0.2)


# ---------- G. modèle pilote, seuils, POIDS_MARCHE ----------
def test_modele_pilote_toujours_enregistre_meme_pour_deepseek(monkeypatch):
    import test_budget_ia as tb
    monkeypatch.delenv("PILOTE_MODELE", raising=False)
    resultat, _ = tb._lancer(monkeypatch, None, tb._composer_fort)
    journal = resultat["journal"]
    assert journal["modele_pilote"].startswith("deepseek") and journal["route_pilote"].startswith("DeepSeek/")


def test_modele_pilote_impose_est_enregistre(monkeypatch):
    import test_budget_ia as tb
    monkeypatch.setenv("PILOTE_MODELE", "openai/gpt-6.1-sol")
    resultat, _ = tb._lancer(monkeypatch, None, tb._composer_fort)
    assert resultat["journal"]["modele_pilote"] == "openai/gpt-6.1-sol"


def test_poids_marche_reste_065_par_defaut(monkeypatch):
    monkeypatch.delenv("POIDS_MARCHE_OVERRIDE", raising=False)
    importlib.reload(ae)
    try:
        assert ae.POIDS_MARCHE == 0.65
    finally:
        importlib.reload(ae)


def test_ecarts_entre_seuils_du_workflow_et_du_code_sont_documentes_et_figes():
    """Les seuils du workflow (0 = aucun) diffèrent volontairement des valeurs par défaut du code (70 %, 1,2-1,8) : on fige les DEUX côtés pour
    qu'aucun changement n'arrive en silence (la décision de les modifier appartient à l'utilisateur)."""
    import yaml
    env = yaml.safe_load((RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))["jobs"]["run"]["env"]
    assert env["SEUIL_PROBA_MIN"] == "0" and env["COTE_MIN_JAMBE"] == "${{ needs.preparer.outputs.cote_min_jambe }}"
    assert ae.lire_seuil_proba(None) == 70.0 and ae.COTE_MIN_JAMBE_DEFAUT == 1.2 and ae.COTE_MAX_JAMBE_DEFAUT == 1.8
    assert ae.lire_seuil_proba("0") == 0.0


# ---------- E. Telegram ----------
def test_aucun_chat_telegram_par_defaut(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES", raising=False)
    importlib.reload(ae)
    try:
        assert ae.TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES == []
    finally:
        importlib.reload(ae)


def test_le_chat_supplementaire_vient_uniquement_de_la_variable(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES", "111, 222")
    importlib.reload(ae)
    try:
        assert ae.TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES == ["111", "222"]
    finally:
        monkeypatch.delenv("TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES", raising=False)
        importlib.reload(ae)


def test_aucun_identifiant_de_chat_code_en_dur_dans_le_code():
    for fichier in list((RACINE / "bet_agent").glob("*.py")) + list((RACINE / "backend" / "app").rglob("*.py")):
        if fichier.name.startswith("test_"):
            continue
        assert "1446772592" not in fichier.read_text(encoding="utf-8"), fichier


# ---------- F. coupons ----------
def _catalogue(n_matchs=6):
    cat = {}
    for i in range(1, n_matchs + 1):
        cat[f"P{i}"] = {"match": f"M{i} - X{i}", "pick": {"marche": "1X2", "selection": "1", "cote": 2.0, "categorie": "resultat",
                                                          "proba_modele_pct": 55.0, "handicap": None, "edge_pct": 1.0},
                        "home_nom": f"M{i}", "fixture_id_oddspapi": f"f{i}"}
    cat["P7"] = {"match": "M1 - X1", "pick": {"marche": "BTTS", "selection": "Yes", "cote": 2.0, "categorie": "btts",
                                                "proba_modele_pct": 50.0, "handicap": None, "edge_pct": 1.0},
                 "home_nom": "M1", "fixture_id_oddspapi": "f1"}
    return cat


def _prop(cle, ids):
    return {"coupons": [{"profil": cle, "strategie": "s", "jambes": [{"id": i, "raison": "ok"} for i in ids]}]}


def test_profils_smart_exigent_deux_jambes_et_pas_de_match_commun():
    for p in profils_smart.profils(contraintes=False):
        assert p["nb_jambes_min"] == 2 and p["match_repete_autorise"] is False


def test_un_coupon_d_une_seule_jambe_est_refuse():
    profil = profils_smart.profils(contraintes=False)[0]
    acceptes, problemes, _ = st.valider(_prop("coupon1", ["P1"]), _catalogue(), [profil])
    assert not acceptes and any("minimum 2" in p for p in problemes)


def test_deux_jambes_de_matchs_differents_sont_acceptees():
    profil = dict(profils_smart.profils(contraintes=False)[0], cote_totale_min=1.0, cote_totale_max=100.0)
    acceptes, problemes, _ = st.valider(_prop("coupon1", ["P1", "P2"]), _catalogue(), [profil])
    assert "coupon1" in acceptes, problemes


def test_un_match_deja_pris_par_un_autre_coupon_est_refuse():
    profil = dict(profils_smart.profils(contraintes=False)[0], cote_totale_min=1.0, cote_totale_max=100.0)
    deja = [{"match": "M1 - X1", "pick": {"marche": "1X2", "selection": "1", "handicap": None, "categorie": "resultat", "cote": 2.0}}]
    acceptes, problemes, _ = st.valider(_prop("coupon1", ["P7", "P2"]), _catalogue(), [profil], selections_precedentes=deja)
    assert not acceptes and any("déjà utilisé dans un autre profil" in p for p in problemes)


def test_le_meme_pari_exact_reste_interdit_meme_quand_la_repetition_est_autorisee():
    profil = dict(profils_smart.profils(contraintes=False)[0], cote_totale_min=1.0, cote_totale_max=100.0, match_repete_autorise=True)
    cat = _catalogue()
    deja = [dict(cat["P1"])]
    acceptes, problemes, _ = st.valider(_prop("coupon1", ["P1", "P2"]), cat, [profil], selections_precedentes=deja)
    assert not acceptes and any("même pari exact" in p for p in problemes)


def test_ajuster_repetition_selon_le_nombre_de_matchs():
    profil = profils_smart.profils(contraintes=False)[0]
    assert st.ajuster_repetition(profil, 6, 3) is profil                         # 3 coupons x 2 jambes = 6 matchs : assez
    ajuste = st.ajuster_repetition(profil, 5, 3)
    assert ajuste["match_repete_autorise"] is True and ajuste["repetition_ajustee"] is True   # 5 < 6 : répétition permise
    assert profil["match_repete_autorise"] is False                              # l'original n'est pas modifié
    deja = dict(profil, match_repete_autorise=True)
    assert st.ajuster_repetition(deja, 1, 3) is deja


def test_aucune_cote_marche_ni_probabilite_inventee_par_l_ia():
    profil = dict(profils_smart.profils(contraintes=False)[0], cote_totale_min=1.0, cote_totale_max=100.0)
    cat = _catalogue()
    acceptes, problemes, _ = st.valider(_prop("coupon1", ["P1", "P99"]), cat, [profil])
    assert not acceptes and any("identifiant inconnu" in p for p in problemes)       # un identifiant hors catalogue est refusé
    acceptes, _, _ = st.valider({"coupons": [{"profil": "coupon1", "strategie": "s", "jambes": [
        {"id": "P1", "raison": "ok", "cote": 9.9, "proba_modele_pct": 99, "marche": "inventé"}, {"id": "P2", "raison": "ok"}]}]}, cat, [profil])
    sel = acceptes["coupon1"]["selections"][0]
    assert sel["pick"]["cote"] == 2.0 and sel["pick"]["proba_modele_pct"] == 55.0 and sel["pick"]["marche"] == "1X2"   # valeurs du catalogue


def test_le_vote_respecte_un_match_dans_un_seul_coupon():
    profils = [dict(profils_smart.profils(contraintes=False)[0], cle="c1"), dict(profils_smart.profils(contraintes=False)[0], cle="c2")]

    def sel(match, proba, marche="1X2"):
        return {"match": match, "pick": {"marche": marche, "selection": "1", "handicap": None, "proba_modele_pct": proba}}
    pilote_res = [{"profil": profils[0], "selections": [sel("A", 70), sel("B", 70)]}, {"profil": profils[1], "selections": [sel("C", 60), sel("D", 60)]}]
    gpt = [{"modele": "gpt", "coupons": [{"profil": "c2", "dans_la_bande": True, "selections": [sel("A", 95, "BTTS"), sel("E", 95)]}]}]
    sortie, _, gagnants = vote.choisir_detail(profils, pilote_res, gpt)
    assert gagnants["c1"] == "pilote"
    assert gagnants["c2"] == "pilote"          # le coupon de GPT reprend le match A déjà pris : écarté malgré sa probabilité plus forte
    assert {x["match"] for x in sortie[1]["selections"]} == {"C", "D"}
    permissifs = [dict(p, match_repete_autorise=True) for p in profils]
    assert vote.choisir_detail(permissifs, pilote_res, gpt)[2]["c2"] == "gpt"   # avec l'ajustement de répétition, l'ancien comportement reste possible
