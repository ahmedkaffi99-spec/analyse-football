import json
"""Fusion de l'agent pilote DeepSeek comme moteur officiel (30/09/2026, demande explicite de
l'utilisateur) : mêmes tables/persistance que l'ancien enchaînement déterministe, mais piloté
par bet_agent/agent_pilote.py au lieu de collecte->calcul->IA ratifie. IA simulée (aucun vrai
appel réseau)."""
from types import SimpleNamespace

from app import taches
from app.database import SessionLocal
from app.models import Run
from app.services import pipeline
from tests.conftest import collecte_exemple, profils_exemple


def _profil_unique():
    return profils_exemple()[0]["profil"]


def _faux_agent_pilote(monkeypatch, resultat, appels=None):
    def fausse_executer(mission=None, telegram=True, profils=None, ignorer_diversite_croisee=False,
                        contexte_supplementaire=None):
        if appels is not None:
            appels.append({"profils": profils, "ignorer_diversite_croisee": ignorer_diversite_croisee,
                           "contexte_supplementaire": contexte_supplementaire})
        return resultat

    faux_module = SimpleNamespace(executer=fausse_executer)
    monkeypatch.setattr(pipeline, "charger_agent_pilote", lambda: faux_module)
    # reinitialiser_caches() a besoin de cd/ae réels ou compatibles — on garde le vrai pont
    # pour cd (collecte_donnees), seul agent_pilote est simulé.
    return faux_module


def test_moteur_agent_termine_et_persiste_le_coupon(monkeypatch):
    profil = _profil_unique()
    selections = profils_exemple()[0]["selections"]
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [{"profil": profil, "selections": selections}],
        "textes": ["ticket rédigé par l'agent"], "envoye": True, "raison_abandon": None,
    })

    assert taches.main(["run", "--telegram", "--moteur", "agent"]) == 0

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "termine"
        assert run.envoye_telegram is True
        assert len(run.coupons) == 1
        coupon = run.coupons[0]
        assert coupon.profil == profil["cle"]
        assert coupon.texte == "ticket rédigé par l'agent"
        assert len(coupon.jambes) == len(selections)


def test_moteur_agent_profils_json_et_ignorer_diversite_transmis_a_l_agent(monkeypatch):
    # Run PONCTUEL (01/10/2026, demande explicite : "6 coupon [...] oublie la diversité") —
    # --profils-json et --ignorer-diversite-croisee doivent atteindre agent_pilote.executer()
    # tels quels, sans jamais toucher au comportement par défaut (voir test juste au-dessus,
    # qui n'utilise ni l'un ni l'autre et reste inchangé).
    import json as json_module
    profil = _profil_unique()
    appels = []
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [], "textes": None,
        "envoye": False, "raison_abandon": "test",
    }, appels=appels)

    profils_6 = [{"cle": f"p{i}", "nom": f"Profil {i}", "cote_min": 100.0, "cote_max": 100000.0,
                 "nb_jambes_min": 10, "nb_jambes": 15} for i in range(1, 7)]

    assert taches.main(["run", "--telegram", "--moteur", "agent",
                        "--profils-json", json_module.dumps(profils_6),
                        "--ignorer-diversite-croisee"]) == 0

    assert len(appels) == 1
    assert appels[0]["profils"] == profils_6
    assert appels[0]["ignorer_diversite_croisee"] is True


def test_moteur_agent_persiste_les_3_profils_separement(monkeypatch):
    # Demande explicite du 30/09/2026 : "je veux chaque profil stocke sur les base" — repassé
    # à 3 profils (sûr/équilibré/audacieux) composés dans le même run par agent_pilote.py ;
    # chacun doit devenir sa PROPRE ligne Coupon (avec son texte et ses jambes), pas fusionnés.
    profils = profils_exemple()
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": profils,
        "textes": ["ticket profil 1", "ticket profil 2", "ticket profil 3 (abstention)"],
        "envoye": True, "raison_abandon": None,
    })

    assert taches.main(["run", "--telegram", "--moteur", "agent"]) == 0

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "termine"
        assert run.envoye_telegram is True
        assert len(run.coupons) == 3
        coupons_par_cle = {c.profil: c for c in run.coupons}
        assert set(coupons_par_cle) == {"profil1", "profil2", "profil3"}
        assert coupons_par_cle["profil1"].texte == "ticket profil 1"
        assert len(coupons_par_cle["profil1"].jambes) == 2
        assert coupons_par_cle["profil2"].texte == "ticket profil 2"
        assert len(coupons_par_cle["profil2"].jambes) == 1
        # profil3 : aucune sélection (abstention) — toujours sa propre ligne, 0 jambe.
        assert coupons_par_cle["profil3"].texte == "ticket profil 3 (abstention)"
        assert len(coupons_par_cle["profil3"].jambes) == 0


def test_moteur_agent_abstention_marque_le_run_abandonne(monkeypatch):
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [{"profil": _profil_unique(), "selections": []}],
        "textes": None, "envoye": False, "raison_abandon": "rien de défendable aujourd'hui",
    })

    assert taches.main(["run", "--moteur", "agent"]) == 0

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "abandonne"
        assert run.detail == "rien de défendable aujourd'hui"
        assert run.coupons == []


def test_moteur_agent_cle_deepseek_manquante_abandonne_sans_donnees(monkeypatch):
    _faux_agent_pilote(monkeypatch, {
        "donnees": None, "resultats_profils": [], "textes": None, "envoye": False,
        "raison_abandon": None, "arret": "clé DEEPSEEK_API_KEY manquante",
    })

    assert taches.main(["run", "--moteur", "agent"]) == 0

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "abandonne"
        assert run.detail == "clé DEEPSEEK_API_KEY manquante"
        assert run.nb_matchs == 0  # aucune collecte enregistrée


def test_moteur_agent_depuis_run_inconnu_clot_le_run_en_erreur_explicite(monkeypatch):
    _faux_agent_pilote(monkeypatch, {"donnees": None, "resultats_profils": []})

    assert taches.main(["run", "--moteur", "agent", "--depuis-run", "999"]) == 1

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "erreur"
        assert "999" in run.detail and "introuvable" in run.detail


def test_moteur_agent_est_le_defaut_avec_trois_profils_de_risque(monkeypatch):
    # 20/10/2026, demande explicite : "l'IA choisit les paris" + "coupon de 12 à 15 jambes" —
    # sans --moteur ni --profils-json, le pipeline lance l'agent avec le profil quotidien.
    monkeypatch.delenv("NB_JAMBES", raising=False)
    monkeypatch.delenv("NB_JAMBES_MIN", raising=False)
    appels = []
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [], "textes": None,
        "envoye": False, "raison_abandon": "test",
    }, appels=appels)

    assert taches.main(["run"]) == 0

    assert len(appels) == 1
    profils = appels[0]["profils"]
    from app import preparer_formulaire
    # Phase 2 (06/11/2026) : le profil de secours EST le profil du formulaire (source unique, plus de règles retirées qui reviennent)
    assert profils == preparer_formulaire.profils()
    assert [p["cle"] for p in profils] == ["coupon1", "coupon2", "coupon3"]
    assert [p["niveau_risque"] for p in profils] == ["prudent", "equilibre", "risque"]   # 07/11/2026 : trois profils de risque ; bandes de cote totale espacées, minimum 5
    assert [(p["cote_totale_min"], p["cote_totale_max"]) for p in profils] == [(5.0, 10.0), (12.0, 20.0), (25.0, 50.0)]
    assert all(p["jambes_max_par_match"] == 1 and p["un_seul_pari_par_event"] for p in profils)
    regles_retirees = {"proba_min_pct", "proba_max_pct", "couvrir_tous_les_matchs", "dernier_profil", "diversifier_entre_coupons", "tous_les_matchs_obligatoires", "familles_obligatoires"}   # max_coupons_par_match est de nouveau actif (07/11/2026 : plafond de 2 coupons par match)
    assert not any(regles_retirees & set(p) for p in profils)


def test_profil_agent_quotidien_respecte_nb_jambes_du_workflow(monkeypatch):
    import analyser_et_envoyer as ae
    monkeypatch.setenv("NB_JAMBES", "8")
    monkeypatch.setenv("NB_JAMBES_MIN", "6")
    assert {(p["nb_jambes_min"], p["nb_jambes"]) for p in ae.profils_agent_quotidien()} == {(6, 8)}
    monkeypatch.setenv("NB_JAMBES", "10")
    monkeypatch.setenv("NB_JAMBES_MIN", "20")  # min jamais au-dessus du max
    assert {(p["nb_jambes_min"], p["nb_jambes"]) for p in ae.profils_agent_quotidien()} == {(10, 10)}


def test_moteur_agent_coupon_deja_envoye_sauvegarde_meme_si_la_collecte_plante(monkeypatch):
    # 21/10/2026 (runs 176/177) : la persistance de la collecte plantait (marche_id trop long)
    # APRÈS l'envoi Telegram : le coupon envoyé était perdu (run en erreur, aucune jambe) et le
    # garde-fou "un ticket par jour" en renvoyait un second. Le coupon doit être sauvegardé et
    # le run marqué envoyé quoi qu'il arrive à la persistance de la collecte.
    from app.services import runs as runs_service
    profil = _profil_unique()
    selections = profils_exemple()[0]["selections"]
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [{"profil": profil, "selections": selections}],
        "textes": ["ticket envoyé"], "envoye": True, "raison_abandon": None,
    })

    def collecte_qui_plante(db, run, donnees):
        raise RuntimeError("value too long for type character varying(32)")

    monkeypatch.setattr(runs_service, "enregistrer_collecte", collecte_qui_plante)

    assert taches.main(["run", "--telegram", "--moteur", "agent"]) == 0

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "termine"
        assert run.envoye_telegram is True
        assert len(run.coupons) == 1 and len(run.coupons[0].jambes) == len(selections)
        assert run.coupons[0].texte == "ticket envoyé"


def test_moteur_agent_enregistre_le_journal_des_recherches_dans_run_detail(monkeypatch):
    # 25/10/2026 : recherches web, pages lues, stratégie et raison de chaque jambe -> runs.detail (colonne texte existante)
    import json
    profil = _profil_unique()
    selections = profils_exemple()[0]["selections"]
    journal = {"recherches": [{"requete": "Chelsea composition", "source": "deepseek",
                               "resultats": [{"titre": "Predicted XI", "lien": "http://a", "extrait": "Penders joue"}]}],
               "pages": [], "strategies": {profil["cle"]: "prudent"}, "raisons": {profil["cle"]: []}}
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [{"profil": profil, "selections": selections}],
        "textes": ["ticket"], "envoye": False, "raison_abandon": None, "journal": journal,
    })

    assert taches.main(["run", "--moteur", "agent"]) == 0

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "termine"
        assert run.detail.startswith("JOURNAL_AGENT ")
        relu = json.loads(run.detail[len("JOURNAL_AGENT "):])
        assert relu["recherches"][0]["requete"] == "Chelsea composition"
        assert relu["strategies"][profil["cle"]] == "prudent"


def test_moteur_agent_accepte_depuis_run(monkeypatch):
    """--depuis-run n'est plus refusé avec le moteur agent : la collecte du run source est transmise à l'agent."""
    from app.services import runs
    recu = {}
    monkeypatch.setattr(runs, "charger_collecte_du_jour", lambda db, run_id: {"nb_matchs_avec_marches": 3, "marqueur": run_id})

    class FauxAgent:
        @staticmethod
        def executer(**kw):
            recu.update(kw)
            return {"donnees": None, "resultats_profils": [], "envoye": False, "raison_abandon": "essai"}
    monkeypatch.setattr(runs.pipeline, "charger_agent_pilote", lambda: FauxAgent)
    from app.database import SessionLocal
    from app.models import Run
    with SessionLocal() as db:
        run = Run(source="test", statut="en_cours"); db.add(run); db.commit(); rid = run.id
    runs.executer_run(rid, envoyer_telegram=False, depuis_run=271, moteur="agent")
    assert recu["donnees_reprises"]["marqueur"] == 271


def test_envoi_partiel_compte_comme_envoye_et_bloque_le_passage_cron_suivant(monkeypatch):
    """Si 2 coupons sur 3 sont partis, le run est « envoyé » : le cron des 20 minutes suivantes ne renvoie pas trois nouveaux coupons."""
    from app.taches import ticket_deja_produit_aujourdhui
    sel = {"match": "Lens vs Auxerre", "pick": {"categorie": "Total", "marche": "Over Under Full Time (2.5)", "selection": "Over",
                                               "handicap": 2.5, "cote": 1.8, "proba_modele_pct": 60.0, "edge_pct": 1.0}}
    _faux_agent_pilote(monkeypatch, {"donnees": collecte_exemple(), "textes": ["coupon"], "envoye": False, "envoi_partiel": "2/3",
                                     "resultats_profils": [{"profil": {"cle": "p1", "nom": "P1"}, "selections": [sel]}]})
    assert taches.main(["run", "--moteur", "agent", "--telegram"]) == 0
    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "termine" and run.envoye_telegram is True
        assert ticket_deja_produit_aujourdhui(db) is True


def test_echec_total_d_envoi_laisse_le_run_non_envoye(monkeypatch):
    sel = {"match": "Lens vs Auxerre", "pick": {"categorie": "Total", "marche": "Over Under Full Time (2.5)", "selection": "Over",
                                               "handicap": 2.5, "cote": 1.8, "proba_modele_pct": 60.0, "edge_pct": 1.0}}
    _faux_agent_pilote(monkeypatch, {"donnees": collecte_exemple(), "textes": ["coupon"], "envoye": False,
                                     "resultats_profils": [{"profil": {"cle": "p1", "nom": "P1"}, "selections": [sel]}]})
    taches.main(["run", "--moteur", "agent", "--telegram"])
    with SessionLocal() as db:
        assert db.query(Run).one().envoye_telegram is False


def test_profil_de_secours_et_formulaire_sont_identiques_pour_toutes_les_options(monkeypatch):
    import analyser_et_envoyer as ae
    from app import preparer_formulaire as pf
    monkeypatch.delenv("NB_JAMBES", raising=False)
    monkeypatch.delenv("NB_JAMBES_MIN", raising=False)
    assert ae.profils_agent_quotidien() == pf.profils()
    # le formulaire, sans aucun choix, produit les mêmes profils que le secours
    sortie = pf.construire({"EVENEMENT": "schedule"})
    assert json.loads(sortie["profils"]) == ae.profils_agent_quotidien()
    # catalogue : aucun seuil de probabilité hérité des profils (la valeur de SEUIL_PROBA_MIN, 0 en production, s'applique)
    import agent_strategie as st
    assert st.seuil_catalogue(ae.profils_agent_quotidien()) == st.SEUIL_PROBA_CATALOGUE


def test_garde_un_run_envoye_bloque_le_passage_suivant_quel_que_soit_son_statut():
    """Phase 2 (06/11/2026) : un run « erreur » ou « abandonné » APRÈS l'envoi ne doit pas déclencher un second envoi."""
    from datetime import datetime, timezone
    from app.taches import ticket_deja_produit_aujourdhui
    maintenant = datetime.now(timezone.utc)
    for statut, envoye, attendu in (("erreur", True, True), ("abandonne", True, True), ("termine", True, True),
                                    ("erreur", False, False), ("abandonne", False, False), ("termine", False, False)):
        with SessionLocal() as db:
            db.query(Run).delete()
            db.add(Run(source="api", statut=statut, envoye_telegram=envoye, lance_le=maintenant))
            db.commit()
            assert ticket_deja_produit_aujourdhui(db) is attendu, (statut, envoye)


def test_plantage_apres_envoi_garde_le_run_envoye_et_empeche_le_renvoi(monkeypatch):
    from app.services import runs as runs_service
    profil = _profil_unique()
    selections = profils_exemple()[0]["selections"]
    appels = []
    _faux_agent_pilote(monkeypatch, {
        "donnees": collecte_exemple(), "resultats_profils": [{"profil": profil, "selections": selections}],
        "textes": ["ticket envoyé"], "envoye": True, "raison_abandon": None,
    }, appels=appels)

    def coupons_qui_plantent(db, run, resultats, index, textes=None):
        raise RuntimeError("panne base après envoi")

    monkeypatch.setattr(runs_service, "enregistrer_coupons", coupons_qui_plantent)
    assert taches.main(["run", "--telegram", "--si-aucun-ticket-aujourdhui", "--moteur", "agent"]) == 1
    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "erreur" and run.envoye_telegram is True
        assert run.detail.startswith("[APRES_ENVOI]")
    # passage cron suivant : rien n'est relancé, donc aucun second envoi
    assert taches.main(["run", "--telegram", "--si-aucun-ticket-aujourdhui", "--moteur", "agent"]) == 0
    assert len(appels) == 1
    with SessionLocal() as db:
        assert db.query(Run).count() == 1
