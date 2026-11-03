"""Agent de planification des vérifications : vagues, heures exactes (Djibouti), validation des ajustements IA,
activation par le plan et rapport final à l'échéance."""
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import PlanVerification
from app.services import plan_verification as pv
from app.services.verification import verification_due
from tests.conftest import collecte_exemple, ticket_exemple

T0 = datetime(2026, 11, 3, 17, 45, tzinfo=timezone.utc)  # 20h45 à Djibouti


def _m(i, minutes):
    return {"match_id": i, "libelle": f"M{i}", "coup_envoi": T0 + timedelta(minutes=minutes), "nb_jambes": 1}


def test_vagues_regroupent_les_matchs_qui_finissent_ensemble():
    vagues = pv.construire_vagues([_m(1, 0), _m(2, 0), _m(3, 135)])  # 20h45, 20h45, 23h00
    assert [len(v["match_ids"]) for v in vagues] == [2, 1]
    # 1re vérification = coup d'envoi + 90 min : 20h45 -> 22h15 (Djibouti)
    assert pv.hhmm(datetime.fromisoformat(vagues[0]["premiere_verif"])) == "22h15"
    assert pv.hhmm(datetime.fromisoformat(vagues[1]["premiere_verif"])) == "00h30"


def test_plan_final_et_message():
    vagues = pv.construire_vagues([_m(1, 0), _m(2, 135)])
    plan = pv.finaliser(vagues, [], pv.analyse_automatique(vagues))
    texte = pv.message_plan(plan, "2026-11-03")
    assert "Vague 1" in texte and "Vague 2" in texte and "Rapport final" in texte
    assert "22h15" in texte and "heure de Djibouti" in texte
    assert "+135 min" in plan["analyse"]


def test_ajustements_ia_valides_et_bornes():
    vagues = pv.construire_vagues([_m(1, 0)])
    vagues, analyse = pv.valider_ajustements(vagues, {
        "vagues": [{"numero": 1, "premiere_verif_apres_coup_envoi_min": 100, "cadence_min": 30}], "analyse": " ok "})
    assert vagues[0]["cadence_min"] == 30 and analyse == "ok"
    # la première vérification reste EXACTEMENT à +90 min (22h15) : l'IA ne peut pas la déplacer
    assert pv.hhmm(datetime.fromisoformat(vagues[0]["premiere_verif"])) == "22h15"
    # hors bornes ou illisible : ignoré, valeurs par défaut conservées
    v2 = pv.construire_vagues([_m(1, 0)])
    v2, _ = pv.valider_ajustements(v2, {"vagues": [{"numero": 1, "premiere_verif_apres_coup_envoi_min": 120, "cadence_min": 10}]})
    assert v2[0]["cadence_min"] == pv.CADENCE_MIN
    assert pv.hhmm(datetime.fromisoformat(v2[0]["premiere_verif"])) == "22h15"
    assert pv.valider_ajustements(v2, "n'importe quoi")[1] is None


def test_ia_indisponible_retombe_sur_le_plan_deterministe():
    vagues = pv.construire_vagues([_m(1, 0)])

    def en_panne(*_a, **_k):
        raise RuntimeError("pas de clé")
    resultat, analyse = pv.plan_par_ia(vagues, [], en_panne)
    assert resultat == vagues and analyse is None


def test_planifier_enregistre_et_active_a_l_heure(client, monkeypatch):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    envoyes = []
    with SessionLocal() as db:
        plan = pv.planifier(db, run_id=1, notifier=envoyes.append, avec_ia=False)
        assert plan and len(plan["vagues"]) == 1
        assert db.query(PlanVerification).count() == 1
        coup_envoi = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)
        avant = coup_envoi + timedelta(minutes=89)
        assert not pv.vagues_actives(db, avant)
        assert pv.vagues_actives(db, coup_envoi + timedelta(minutes=90))        # 20h30 UTC = 23h30 Djibouti
        assert verification_due(db, datetime(2026, 9, 25, 21, 5, tzinfo=timezone.utc))[0] is True   # filet horaire
        assert not pv.vagues_actives(db, coup_envoi + timedelta(hours=5))      # fenêtre close
        assert pv.echeances_depassees(db, coup_envoi + timedelta(hours=5))
    assert envoyes and "PLAN DE VÉRIFICATION" in envoyes[0]


def test_rapport_final_partiel_force_a_l_echeance(client):
    from app.services.bilan import envoyer_bilans
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    messages = []
    with SessionLocal() as db:
        assert envoyer_bilans(db, lambda m: messages.append(m) or True) == 0      # jambes en attente : rien
        assert envoyer_bilans(db, lambda m: messages.append(m) or True, forcer_runs={1}) == 1
    assert "Rapport final partiel" in messages[0]


def test_replanifier_remplace_l_ancien_plan(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    with SessionLocal() as db:
        pv.planifier(db, run_id=1, avec_ia=False)
        pv.planifier(db, run_id=1, avec_ia=False)
        assert db.query(PlanVerification).count() == 1


def test_grille_tous_les_quarts_d_heure_a_partir_de_23h30(client):
    """Match de 19h00 UTC (22h00 Djibouti) : 1re vérification à +90 min (23h30), puis 23h40, 23h50... jusqu'à la limite."""
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    with SessionLocal() as db:
        plan = pv.planifier(db, run_id=1, avec_ia=False)
    points = pv.points_de_verification(plan["vagues"][0])
    assert [pv.hhmm(p) for p in points[:3]] == ["23h30", "23h45", "00h00"]
    assert points[-1] <= datetime.fromisoformat(plan["vagues"][0]["limite"])
    assert (points[1] - points[0]) == timedelta(minutes=15)


def test_filet_horaire_sans_attente(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    coup_envoi = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        pv.planifier(db, run_id=1, avec_ia=False)
        assert pv.vagues_actives(db, coup_envoi + timedelta(minutes=100))               # 20h40 UTC : fenêtre ouverte
        assert not pv.vagues_actives(db, coup_envoi + timedelta(minutes=89))            # avant 20h30 UTC
        assert verification_due(db, datetime(2026, 9, 25, 21, 5, tzinfo=timezone.utc))[0] is True    # passage horaire
        assert verification_due(db, datetime(2026, 9, 25, 21, 46, tzinfo=timezone.utc))[0] is True   # point 21h45 tombé


def test_cron_autonome_traite_chaque_point_de_la_grille(client):
    """Coupons du run automatique : sans session, le cron (quarts d'heure) vérifie juste après chaque point."""
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    coup_envoi = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)
    p1 = coup_envoi + timedelta(minutes=90)  # 20h30 UTC
    with SessionLocal() as db:
        pv.planifier(db, run_id=1, avec_ia=False)
        assert verification_due(db, p1 + timedelta(minutes=2))[0] is True             # passage 20h32 : point 20h30 tombé
        assert verification_due(db, p1 + timedelta(minutes=16))[0] is True            # passage 20h46 : point 20h45
        assert pv.points_dus(db, p1 - timedelta(minutes=1)) == []                     # avant la 1re vérification
        assert len(pv.points_dus(db, p1 + timedelta(minutes=2))) == 1


def test_run_automatique_envoye_declenche_la_planification(client, monkeypatch):
    """Run du midi (cron --telegram) : une fois les coupons partis, l'agent planifie les vérifications."""
    import argparse
    from app import taches
    from app.models import Run

    def faux_run(run_id, **_k):
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            run.statut, run.envoye_telegram = "termine", True
            db.commit()

    appels = []
    monkeypatch.setattr(taches, "executer_run", faux_run)
    monkeypatch.setattr(taches, "tache_planifier", lambda args: appels.append(args.run_id) or 0)
    args = argparse.Namespace(telegram=True, si_aucun_ticket_aujourdhui=False, sans_redaction=True, depuis_run=None,
                              moteur="agent", profils_json="", ignorer_diversite_croisee=False)
    assert taches.tache_run(args) == 0
    assert len(appels) == 1

    appels.clear()                                  # sans Telegram : pas de planification
    args.telegram = False
    taches.tache_run(args)
    assert appels == []


def test_workflow_active_puis_desactive(monkeypatch):
    from app.services import github_actions as ga
    appels = []

    class Rep:
        status_code = 204

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    assert ga.activer_workflow(actif=True, poster=lambda url, **k: appels.append(url) or Rep()) is True
    assert ga.activer_workflow(actif=False, poster=lambda url, **k: appels.append(url) or Rep()) is True
    assert appels[0].endswith("/actions/workflows/verification-resultats.yml/enable")
    assert appels[1].endswith("/actions/workflows/verification-resultats.yml/disable")


def test_workflow_sans_jeton_ne_fait_rien(monkeypatch):
    from app.services import github_actions as ga
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert ga.activer_workflow(poster=lambda *a, **k: (_ for _ in ()).throw(AssertionError("appel inattendu"))) is False
