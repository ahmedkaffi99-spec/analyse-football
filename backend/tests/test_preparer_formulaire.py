import json

from app import preparer_formulaire as pf


def test_defauts_donnent_trois_profils_de_risque_sans_cote_imposee():
    s = pf.construire({"EVENEMENT": "workflow_dispatch"})
    liste = json.loads(s["profils"])
    # 07/11/2026 : trois profils (prudent, équilibré, risque), l'IA choisit librement : AUCUNE bande, plancher ni plafond de cote
    assert [p["niveau_risque"] for p in liste] == ["prudent", "equilibre", "risque"]
    assert [p["cle"] for p in liste] == ["coupon1", "coupon2", "coupon3"]
    assert all(not any(k in p for k in ("cote_totale_min", "cote_totale_max", "cote_min", "cote_max", "proba_min_pct", "proba_max_pct",
                                         "max_coupons_par_match", "prefere_cote_elevee")) for p in liste)
    assert all(p["consigne"] for p in liste) and len({p["consigne"] for p in liste}) == 3
    # règles de cohérence conservées : 2 jambes minimum (Python), un match dans un seul coupon, un pari par match
    assert all(p["nb_jambes_min"] == 2 and p["nb_jambes"] == 99 and p["jambes_max_par_match"] == 1 and p["match_repete_autorise"] is False for p in liste)
    assert s["moteur"] == "agent" and s["cote_min_jambe"] == "0" and s["cote_max_jambe"] == "0" and s["ignorer_diversite"] == "true"
    assert json.loads(s["matrice"]) == [{"etiquette": "deepseek", "pilote": ""}]
    assert s["vote"] == pf.VOTE_DEFAUT and s["ttl"] == "43200" and s["telegram"] == ""


def test_cron_ne_fixe_ni_date_ni_ttl():
    s = pf.construire({"EVENEMENT": "schedule"})
    assert s["date_debut"] == s["date_fin"] == s["ttl"] == ""


def test_choix_du_formulaire_sont_appliques():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "UN_PARI_PAR_MATCH": "desactive", "TELEGRAM_IN": "true", "DEPUIS_RUN": " 271 ",
                      "DATE_DEBUT": "2026-11-07", "DATE_FIN": "2026-11-07"})
    liste = json.loads(s["profils"])
    assert len(liste) == 3 and all(p["jambes_max_par_match"] == 3 for p in liste)
    assert (s["depuis_run"], s["telegram"]) == ("271", "true")
    assert s["date_debut"] == s["date_fin"] == "2026-11-07"


def test_anciens_champs_de_cote_et_de_nombre_de_coupons_sont_ignores():
    """Un ancien appel qui fournirait NB_COUPONS ou COTE_COUPON_n ne peut plus imposer de bande ni changer le nombre de coupons."""
    liste = json.loads(pf.construire({"EVENEMENT": "workflow_dispatch", "NB_COUPONS": "5", "COTE_COUPON_1": "50-100"})["profils"])
    assert len(liste) == 3 and all("cote_totale_min" not in p for p in liste)


def test_modeles_et_vote():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "gpt-6.1-sol", "TELEGRAM_IN": "true"})
    assert json.loads(s["matrice"])[0]["pilote"] == "openai/gpt-6.1-sol" and s["vote"] == "aucun"
    c = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "claude-sonnet-5.5"})
    assert json.loads(c["matrice"])[0]["pilote"] == "anthropic/claude-sonnet-5.5"


def test_autres_moteurs_sans_profils_ni_pilote():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MOTEUR": "deterministe", "MODELE": "gpt-6.1-sol"})
    assert s["profils"] == "" and s["vote"] == "aucun" and json.loads(s["matrice"])[0]["pilote"] == ""


def test_ecriture_dans_github_output(tmp_path):
    fichier = tmp_path / "sortie.txt"
    pf.ecrire(pf.construire({"EVENEMENT": "workflow_dispatch"}), str(fichier))
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    assert any(l.startswith("profils=[") for l in lignes) and all("\n" not in l for l in lignes)


def test_le_modele_duel_n_existe_plus():
    import pytest
    with pytest.raises(ValueError):
        pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "duel"})


def test_deepseek_via_openrouter_est_un_modele_independant_sans_vote():
    """07/11/2026 : « lance DeepSeek sur l'API OpenRouter » — le pilote est DeepSeek via OpenRouter (modèle imposé, aucun repli), sans vote ni mélange avec d'autres modèles."""
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "deepseek-openrouter", "TELEGRAM_IN": "true"})
    assert json.loads(s["matrice"]) == [{"etiquette": "deepseek-openrouter", "pilote": "deepseek/deepseek-v4.1-flash"}] and s["vote"] == "aucun"
    officiel = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "deepseek"})
    assert json.loads(officiel["matrice"])[0]["pilote"] == "" and officiel["vote"] == pf.VOTE_DEFAUT          # l'API officielle garde son comportement


def test_le_formulaire_propose_deepseek_openrouter():
    import yaml
    from pathlib import Path
    wf = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))
    assert set(wf[True]["workflow_dispatch"]["inputs"]["modele"]["options"]) == set(pf.MODELES)
