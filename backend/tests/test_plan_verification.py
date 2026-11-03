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
        assert verification_due(db, coup_envoi + timedelta(minutes=105))[0] is True
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


def test_grille_toutes_les_10_minutes_a_partir_de_23h15(client, monkeypatch):
    """Match de 21h45 : 1re vérification à 23h15 pile, puis 23h25, 23h35... (heures de Djibouti)."""
    from app import taches
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    coup_envoi = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)
    debut = coup_envoi + timedelta(minutes=90)
    with SessionLocal() as db:
        pv.planifier(db, run_id=1, avec_ia=False)
        assert pv.prochains_points(db, debut - timedelta(minutes=17)) == []           # trop tôt pour attendre
        assert pv.prochains_points(db, debut - timedelta(minutes=10)) == [debut]
        assert pv.prochains_points(db, debut + timedelta(minutes=9)) == [debut + timedelta(minutes=10),
                                                                         debut + timedelta(minutes=20)]  # 16 min d'horizon
        # cron en retard de 1 min : le point manqué est quand même vérifié
        assert pv.prochains_points(db, debut + timedelta(minutes=1))[0] == debut

        horloge = [debut - timedelta(minutes=10)]
        dormis, verifs = [], []

        def dormir(secondes):
            dormis.append(secondes)
            horloge[0] += timedelta(seconds=secondes)

        monkeypatch.setattr(taches, "verifier_coupons_en_attente", lambda db_: verifs.append(horloge[0]) or {})
        points = [debut, debut + timedelta(minutes=10)]
        taches.executer_points(db, points, maintenant=lambda: horloge[0], dormir=dormir)
    assert dormis[0] == 600                                    # attend jusqu'à l'heure exacte
    assert verifs == points                                    # 23h15 puis 23h25 pile
    assert pv.hhmm(verifs[0]) == "22h15" and pv.hhmm(verifs[1]) == "22h25"  # 19h00 UTC + 90 min = 22h15 Djibouti
