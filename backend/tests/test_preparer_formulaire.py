import json

from app import preparer_formulaire as pf


def test_defauts_gardent_le_comportement_smart_habituel():
    s = pf.construire({"EVENEMENT": "workflow_dispatch"})
    liste = json.loads(s["profils"])
    assert [(p["cote_totale_min"], p["cote_totale_max"]) for p in liste] == [(5, 10), (12, 18), (20, 35)]
    assert all(p["nb_jambes_min"] == 1 and p["nb_jambes"] == 12 and p["jambes_max_par_match"] == 1 for p in liste)
    assert s["moteur"] == "agent" and s["cote_min_jambe"] == "1.01" and s["cote_max_jambe"] == "0"
    assert json.loads(s["matrice"]) == [{"etiquette": "deepseek", "pilote": ""}]
    assert s["vote"] == pf.VOTE_DEFAUT and s["ttl"] == "43200" and s["telegram"] == ""


def test_cron_ne_fixe_ni_date_ni_ttl():
    s = pf.construire({"EVENEMENT": "schedule"})
    assert s["date_debut"] == s["date_fin"] == s["ttl"] == ""


def test_choix_du_formulaire_sont_appliques():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "NB_COUPONS": "2", "COTE_TOTALE": "10-18", "NB_JAMBES_MIN": "3", "NB_JAMBES_MAX": "6",
                      "COTE_MIN_JAMBE": "1.3", "COTE_MAX_JAMBE": "3.1", "UN_PARI_PAR_MATCH": "desactive", "TELEGRAM_IN": "true",
                      "DEPUIS_RUN": " 271 ", "IGNORER_DIVERSITE": "true", "DATE_DEBUT": "2026-11-07", "DATE_FIN": "2026-11-07"})
    liste = json.loads(s["profils"])
    assert len(liste) == 2 and all((p["cote_totale_min"], p["cote_totale_max"]) == (10, 18) for p in liste)
    assert all(p["nb_jambes_min"] == 3 and p["nb_jambes"] == 6 and p["jambes_max_par_match"] == 3 for p in liste)
    assert (s["cote_min_jambe"], s["cote_max_jambe"], s["depuis_run"], s["telegram"], s["ignorer_diversite"]) == ("1.3", "3.1", "271", "true", "true")
    assert s["date_debut"] == s["date_fin"] == "2026-11-07"


def test_minimum_de_jambes_ne_depasse_jamais_le_maximum():
    liste = pf.profils(nb_min=8, nb_max=4)
    assert liste[0]["nb_jambes_min"] == 4 and liste[0]["nb_jambes"] == 4


def test_nombre_de_coupons_au_dela_de_trois_reprend_les_bandes_smart():
    liste = pf.profils(nb_coupons=5)
    assert [(p["cote_totale_min"], p["cote_totale_max"]) for p in liste] == [(5, 10), (12, 18), (20, 35), (5, 10), (12, 18)]
    assert len({p["cle"] for p in liste}) == 5


def test_modeles_vote_et_duel():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "gpt-6.1-sol", "TELEGRAM_IN": "true"})
    assert json.loads(s["matrice"])[0]["pilote"] == "openai/gpt-6.1-sol" and s["vote"] == "aucun" and s["ombre"] == "aucun"
    d = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "duel", "TELEGRAM_IN": "true"})
    assert [m["pilote"] for m in json.loads(d["matrice"])] == ["", "openai/gpt-6.1-sol"] and d["telegram"] == "" and d["vote"] == "aucun"
    c = pf.construire({"EVENEMENT": "workflow_dispatch", "MODELE": "claude-sonnet-5.5"})
    assert json.loads(c["matrice"])[0]["pilote"] == "anthropic/claude-sonnet-5.5"


def test_autres_moteurs_sans_profils_ni_pilote():
    s = pf.construire({"EVENEMENT": "workflow_dispatch", "MOTEUR": "deterministe", "MODELE": "gpt-6.1-sol", "NB_COUPONS": "2"})
    assert s["profils"] == "" and s["vote"] == "aucun" and json.loads(s["matrice"])[0]["pilote"] == ""


def test_ecriture_dans_github_output(tmp_path):
    fichier = tmp_path / "sortie.txt"
    pf.ecrire(pf.construire({"EVENEMENT": "workflow_dispatch"}), str(fichier))
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    assert any(l.startswith("profils=[") for l in lignes) and all("\n" not in l for l in lignes)
