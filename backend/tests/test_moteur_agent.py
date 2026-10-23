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


def test_moteur_agent_refuse_depuis_run(monkeypatch):
    _faux_agent_pilote(monkeypatch, {"donnees": None, "resultats_profils": []})

    assert taches.main(["run", "--moteur", "agent", "--depuis-run", "1"]) == 1

    with SessionLocal() as db:
        run = db.query(Run).one()
        assert run.statut == "erreur"
        assert "depuis-run" in run.detail


def test_moteur_agent_est_le_defaut_avec_profil_12_a_15_jambes(monkeypatch):
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
    assert [p["cle"] for p in profils] == ["coupon1", "coupon2", "coupon3"]
    assert all(p["nb_jambes_min"] == 5 and p["nb_jambes"] == 10 for p in profils)
    # 1xBet : un seul pari par EVENT (« Event already added » sinon, 23/10/2026)
    assert all(p["un_seul_pari_par_event"] and not p.get("tous_les_matchs_obligatoires") for p in profils)
    assert all(p["diversifier_entre_coupons"] for p in profils)
    assert all(p["couvrir_tous_les_matchs"] for p in profils) and [p.get("dernier_profil") for p in profils] == [None, None, True]
    # 24/10/2026 : petite cote 5-15 (prudent), cote moyenne 20-40 (équilibré), haute cote 50-100+ (très risqué)
    assert [(p["cote_totale_min"], p.get("cote_totale_max")) for p in profils] == [
        (5.0, 15.0), (20.0, 40.0), (50.0, None)]
    assert [p["proba_min_pct"] for p in profils] == [70.0, 62.0, 55.0]


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
