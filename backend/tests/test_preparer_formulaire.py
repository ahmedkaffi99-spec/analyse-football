import json

from app import preparer_formulaire as pf


def test_defauts_donnent_trois_profils_de_risque_sans_cote_imposee():
    s = pf.construire({"EVENEMENT": "workflow_dispatch"})
    liste = json.loads(s["profils"])
    # 07/11/2026 : trois profils (prudent, équilibré, risque), l'IA choisit librement les paris ; demande ultérieure : 5 à 12 jambes, cote totale minimale 5 et
    # trois bandes de cote totale ESPACÉES (aucun chevauchement) ; aucune cote imposée par jambe
    assert [p["niveau_risque"] for p in liste] == ["prudent", "equilibre", "risque"]
    assert [p["cle"] for p in liste] == ["coupon1", "coupon2", "coupon3"]
    assert all(not any(k in p for k in ("cote_min", "cote_max", "proba_min_pct", "proba_max_pct", "prefere_cote_elevee")) for p in liste)
    bandes = [(p["cote_totale_min"], p["cote_totale_max"]) for p in liste]
    assert bandes == [(5.0, 10.0), (12.0, 20.0), (25.0, 50.0)] and min(b[0] for b in bandes) >= 5
    assert all(bandes[i][1] < bandes[i + 1][0] for i in range(2))                      # intervalles espacés : aucun chevauchement
    assert all(p["consigne"] for p in liste) and len({p["consigne"] for p in liste}) == 3
    # règles de cohérence conservées : 5 à 12 jambes (Python), un match dans un seul coupon, un pari par match
    assert all(p["nb_jambes_min"] == 5 and p["nb_jambes"] == 12 and p["jambes_max_par_match"] == 1 and p["match_repete_autorise"] is True for p in liste)
    assert s["moteur"] == "agent" and s["cote_min_jambe"] == "0" and s["cote_max_jambe"] == "0" and s["ignorer_diversite"] == "true"
    # 07/11/2026 : modèle par défaut = DeepSeek via OpenRouter, un seul modèle sans vote (l'API officielle DeepSeek reste choisissable)
    assert json.loads(s["matrice"]) == [{"etiquette": "deepseek-openrouter", "pilote": "deepseek/deepseek-v4.1-flash", "reutiliser": ""}]
    assert s["vote"] == "aucun" and s["ttl"] == "43200" and s["telegram"] == ""
    assert all(p["max_coupons_par_match"] == 2 for p in liste)   # un même match dans 2 coupons au plus


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
    """Un ancien appel qui fournirait NB_COUPONS ou COTE_COUPON_n ne peut plus changer la bande ni le nombre de coupons."""
    liste = json.loads(pf.construire({"EVENEMENT": "workflow_dispatch", "NB_COUPONS": "5", "COTE_COUPON_1": "50-100"})["profils"])
    assert len(liste) == 3 and [p["cote_totale_max"] for p in liste] == [10.0, 20.0, 50.0]


def test_modeles_et_vote():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "gpt-6.1-sol", "TELEGRAM_IN": "true"})
    assert json.loads(s["matrice"])[0]["pilote"] == "openai/gpt-6.1-sol" and s["vote"] == "aucun"
    c = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "claude-sonnet-5.5"})
    assert json.loads(c["matrice"])[0]["pilote"] == "anthropic/claude-sonnet-5.5"


def test_les_trois_moteurs_recoivent_les_memes_trois_profils_sans_pilote_ni_vote_pour_les_autres():
    """Comparaison équitable (07/11/2026) : agent, central et déterministe reçoivent EXACTEMENT les mêmes trois profils ; seul l'agent a un pilote IA et un vote."""
    profils = {m: pf.construire({"EVENEMENT": "workflow_dispatch", "MOTEUR": m, "MODELE": "gpt-6.1-sol"})["profils"] for m in ("agent", "central", "deterministe")}
    assert profils["agent"] == profils["central"] == profils["deterministe"] and len(json.loads(profils["agent"])) == 3
    for m in ("central", "deterministe"):
        s = pf.construire({"EVENEMENT": "workflow_dispatch", "MOTEUR": m, "MODELE": "gpt-6.1-sol"})
        assert s["moteur"] == m and s["vote"] == "aucun" and json.loads(s["matrice"]) == [{"etiquette": m, "pilote": "", "reutiliser": ""}]


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
    assert json.loads(s["matrice"]) == [{"etiquette": "deepseek-openrouter", "pilote": "deepseek/deepseek-v4.1-flash", "reutiliser": ""}] and s["vote"] == "aucun"
    officiel = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "deepseek"})
    assert json.loads(officiel["matrice"])[0]["pilote"] == "" and officiel["vote"] == pf.VOTE_DEFAUT          # l'API officielle garde son comportement


def test_le_formulaire_propose_deepseek_openrouter():
    import yaml
    from pathlib import Path
    wf = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))
    assert set(wf[True]["workflow_dispatch"]["inputs"]["modele"]["options"]) == set(pf.MODELES)


def test_deux_modeles_dans_le_meme_lancement_le_second_relit_la_collecte():
    """Comparaison de deux modèles (07/11/2026) : l'un après l'autre (max-parallel 1), même collecte, aucun vote."""
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "deepseek-openrouter", "MODELE_2": "gpt-6.1-sol"})
    m = json.loads(s["matrice"])
    assert [(x["etiquette"], x["reutiliser"]) for x in m] == [("deepseek-openrouter", ""), ("gpt-6.1-sol", "1")] and s["vote"] == "aucun"
    assert json.loads(pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE_2": "aucun"})["matrice"])[0]["reutiliser"] == ""
    import pytest
    with pytest.raises(ValueError):
        pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "gpt-6.1-sol", "MODELE_2": "gpt-6.1-sol"})


def test_jambes_et_bandes_parametrables_avec_defaut_en_cas_de_valeur_invalide():
    liste = json.loads(pf.construire({"EVENEMENT": "workflow_dispatch", "JAMBES": "3-6", "BANDES": "5-8 / 10-18 / 22-40"})["profils"])
    assert [(p["nb_jambes_min"], p["nb_jambes"], p["cote_totale_min"], p["cote_totale_max"]) for p in liste] == [(3, 6, 5.0, 8.0), (3, 6, 10.0, 18.0), (3, 6, 22.0, 40.0)]
    defaut = json.loads(pf.construire({"EVENEMENT": "workflow_dispatch", "JAMBES": "abc", "BANDES": "5-8 / 10-18"})["profils"])
    assert [(p["nb_jambes_min"], p["nb_jambes"], p["cote_totale_min"]) for p in defaut] == [(5, 12, 5.0), (5, 12, 12.0), (5, 12, 25.0)]
    vide = json.loads(pf.construire({"EVENEMENT": "schedule"})["profils"])
    assert [(p["nb_jambes_min"], p["nb_jambes"]) for p in vide] == [(5, 12)] * 3
