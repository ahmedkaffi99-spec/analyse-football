"""Phase 4 (07/11/2026) — corrections contrôlées côté pipeline : relances payantes, exécution simultanée, finalisation après arrêt du job,
coûts conservés en cas d'erreur, idempotence et date réelle des coupons, cohérence des workflows.
Tests locaux : aucun réseau, aucune clé, aucune écriture en production (base de test vide). Ils ne prouvent AUCUNE rentabilité prédictive."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import garde, taches
from app.database import SessionLocal
from app.models import STATUTS_RUN, Coupon, Match, Run
from app.services import alertes, pipeline
from app.services.budget import couts_depuis_fichier, couts_du_run, texte_couts_pour_detail
from app.services.persistance import enregistrer_coupons, jour_du_coupon

RACINE = Path(__file__).resolve().parents[2]
TOT = datetime.now(timezone.utc).replace(hour=9, minute=7, second=0, microsecond=0)
DERNIER = TOT.replace(hour=13, minute=27)


def _run(db, statut, cout=None, envoye=False, quand=None):
    detail = None
    if cout is not None:
        detail = "erreur technique" + texte_couts_pour_detail({"total_usd": cout, "pilote": {}, "vote": []})
    r = Run(source="api", statut=statut, envoye_telegram=envoye, lance_le=quand or TOT, detail=detail)
    db.add(r)
    db.commit()
    return r.id


# ---------- C. relances payantes ----------
def test_statuts_de_run_distinguent_reussi_echoue_interrompu_en_cours():
    assert {"termine", "erreur", "interrompu", "en_cours", "abandonne"} <= set(STATUTS_RUN)


def test_seuls_les_echecs_avec_depense_comptent():
    with SessionLocal() as db:
        _run(db, "abandonne")                      # sans dépense : gratuit, ne compte pas
        _run(db, "erreur", cout=0.0)               # coût nul : ne compte pas
        _run(db, "termine", cout=1.0)              # réussi : ne compte pas
        assert garde.echecs_payants_du_jour(db, TOT) == 0
        _run(db, "erreur", cout=0.4)
        _run(db, "abandonne", cout=0.2)
        _run(db, "interrompu", cout=0.1)
        assert garde.echecs_payants_du_jour(db, TOT) == 3


def test_relances_payantes_epuisees_bloque_le_passage_planifie(monkeypatch):
    monkeypatch.setattr(garde.config, "MAX_ECHECS_PAYANTS_PAR_JOUR", 2)
    with SessionLocal() as db:
        _run(db, "erreur", cout=0.4)
        assert garde.decision_passage(db, TOT)[0] is True                  # un seul échec payant : on réessaie
        _run(db, "interrompu", cout=0.3)
        lancer, raison = garde.decision_passage(db, TOT)
        assert lancer is False and "relances payantes épuisées" in raison
        lancer, raison = garde.decision_passage(db, DERNIER)               # dernier passage sans coupon : le job tourne SEULEMENT pour alerter
        assert lancer is True and "sans rien dépenser" in raison


def test_un_coupon_envoye_prime_sur_les_echecs():
    with SessionLocal() as db:
        _run(db, "erreur", cout=0.4)
        _run(db, "termine", envoye=True)
        assert garde.decision_passage(db, TOT)[0] is False


def test_tache_run_planifiee_ne_depense_plus_quand_les_relances_sont_epuisees(monkeypatch):
    monkeypatch.setattr(garde.config, "MAX_ECHECS_PAYANTS_PAR_JOUR", 1)
    with SessionLocal() as db:
        _run(db, "erreur", cout=0.5, quand=datetime.now(timezone.utc))
    monkeypatch.setattr(taches, "executer_run", lambda *a, **k: pytest.fail("aucun run ne doit démarrer"))
    args = SimpleNamespace(si_aucun_ticket_aujourdhui=True, telegram=False, moteur="agent", profils_json="", ignorer_diversite_croisee=False,
                           sans_redaction=False, depuis_run=None)
    assert taches.tache_run(args) == 0
    with SessionLocal() as db:
        assert db.query(Run).count() == 1                                  # aucun nouveau run créé


def test_un_lancement_manuel_n_est_pas_bloque_par_les_relances(monkeypatch):
    monkeypatch.setattr(garde.config, "MAX_ECHECS_PAYANTS_PAR_JOUR", 1)
    with SessionLocal() as db:
        _run(db, "erreur", cout=0.5, quand=datetime.now(timezone.utc))
    appels = []
    monkeypatch.setattr(taches, "executer_run", lambda run_id, **k: appels.append(run_id))
    args = SimpleNamespace(si_aucun_ticket_aujourdhui=False, telegram=False, moteur="agent", profils_json="", ignorer_diversite_croisee=False,
                           sans_redaction=False, depuis_run=None)
    taches.tache_run(args)
    assert len(appels) == 1                                                 # l'utilisateur décide : le run manuel démarre


# ---------- C. exécutions simultanées ----------
def test_autre_run_en_cours_detecte_seulement_un_run_plus_ancien_et_recent():
    with SessionLocal() as db:
        ancien = _run(db, "en_cours", quand=datetime.now(timezone.utc) - timedelta(minutes=10))
        perime = _run(db, "en_cours", quand=datetime.now(timezone.utc) - timedelta(hours=5))
        nouveau = _run(db, "en_cours", quand=datetime.now(timezone.utc))
        assert garde.autre_run_en_cours(db, nouveau) == ancien              # le périmé est ignoré
        assert garde.autre_run_en_cours(db, ancien) is None                 # le plus ancien n'attend personne
        assert perime != ancien


def test_run_simultane_s_abstient_sans_rien_depenser(monkeypatch):
    with SessionLocal() as db:
        premier = _run(db, "en_cours", quand=datetime.now(timezone.utc) - timedelta(minutes=5))
    monkeypatch.setattr(taches, "executer_run", lambda *a, **k: pytest.fail("un run concurrent ne doit rien exécuter"))
    args = SimpleNamespace(si_aucun_ticket_aujourdhui=False, telegram=False, moteur="agent", profils_json="", ignorer_diversite_croisee=False,
                           sans_redaction=False, depuis_run=None)
    assert taches.tache_run(args) == 0
    with SessionLocal() as db:
        second = db.query(Run).order_by(Run.id.desc()).first()
        assert second.statut == "abandonne" and f"run {premier}" in second.detail and second.termine_le is not None


# ---------- A/D. finalisation après arrêt du job ----------
@pytest.fixture
def fichier_couts(tmp_path, monkeypatch):
    chemin = tmp_path / "couts.json"
    monkeypatch.setenv("COUTS_FICHIER", str(chemin))
    pipeline.modules()
    return chemin


def test_finaliser_cloture_en_interrompu_et_conserve_les_couts(fichier_couts):
    with SessionLocal() as db:
        rid = _run(db, "en_cours")
    fichier_couts.write_text(json.dumps({"run_id": rid, "pilote": {"cout_usd": 0.42, "appels": 7, "appels_cout_estime": 2},
                                         "vote": [{"modele": "gpt", "cout_usd": 0.3}]}), encoding="utf-8")
    assert taches.tache_finaliser(SimpleNamespace()) == 0
    with SessionLocal() as db:
        run = db.get(Run, rid)
        assert run.statut == "interrompu" and run.termine_le is not None and "Interrompu" in run.detail
        couts = couts_du_run(run)
        assert couts["total_usd"] == pytest.approx(0.72) and "estimé" in couts["alerte"]
    with SessionLocal() as db:
        assert garde.echecs_payants_du_jour(db, TOT) == 1                       # comptabilisé comme échec payant du jour


def test_finaliser_est_idempotent_et_ne_touche_pas_un_run_termine(fichier_couts):
    with SessionLocal() as db:
        rid = _run(db, "termine", envoye=True)
    fichier_couts.write_text(json.dumps({"run_id": rid, "pilote": {"cout_usd": 9.0}, "vote": []}), encoding="utf-8")
    taches.tache_finaliser(SimpleNamespace())
    taches.tache_finaliser(SimpleNamespace())
    with SessionLocal() as db:
        run = db.get(Run, rid)
        assert run.statut == "termine" and run.detail is None


def test_finaliser_sans_fichier_ou_avec_fichier_illisible_ne_plante_pas(fichier_couts):
    assert taches.tache_finaliser(SimpleNamespace()) == 0                  # fichier absent
    fichier_couts.write_text("{pas du json", encoding="utf-8")
    assert taches.tache_finaliser(SimpleNamespace()) == 0
    fichier_couts.write_text(json.dumps({"run_id": 99999, "pilote": {"cout_usd": 1}}), encoding="utf-8")
    assert taches.tache_finaliser(SimpleNamespace()) == 0                  # run introuvable


def test_finaliser_appliquee_deux_fois_ne_double_pas_la_depense(fichier_couts):
    with SessionLocal() as db:
        rid = _run(db, "en_cours")
    fichier_couts.write_text(json.dumps({"run_id": rid, "pilote": {"cout_usd": 0.5}, "vote": []}), encoding="utf-8")
    taches.tache_finaliser(SimpleNamespace())
    with SessionLocal() as db:
        premier = db.get(Run, rid).detail
    taches.tache_finaliser(SimpleNamespace())
    with SessionLocal() as db:
        assert db.get(Run, rid).detail == premier


def test_couts_depuis_fichier():
    assert couts_depuis_fichier(None) is None and couts_depuis_fichier({"run_id": 1, "pilote": {}, "vote": []}) is None
    b = couts_depuis_fichier({"pilote": {"cout_usd": 0.1}, "vote": [{"cout_usd": 0.2}, {"cout_usd": None}]})
    assert b["total_usd"] == pytest.approx(0.3) and b["source"] == "fichier_couts"


# ---------- D. coûts conservés quand le run plante, sans masquer l'erreur ----------
def test_un_run_qui_plante_reste_en_erreur_et_garde_ses_couts(fichier_couts, monkeypatch):
    with SessionLocal() as db:
        rid = _run(db, "en_cours")
    fichier_couts.write_text(json.dumps({"run_id": rid, "pilote": {"cout_usd": 0.6}, "vote": []}), encoding="utf-8")
    from app.services import runs
    vrai_modules, etat = pipeline.modules, {"n": 0}

    def modules_qui_plante_une_fois():
        etat["n"] += 1
        if etat["n"] == 1:
            raise RuntimeError("panne simulée après dépense")
        return vrai_modules()
    monkeypatch.setattr(runs.pipeline, "modules", modules_qui_plante_une_fois)
    runs.executer_run(rid, moteur="agent")
    with SessionLocal() as db:
        run = db.get(Run, rid)
        assert run.statut == "erreur"                                         # l'erreur n'est PAS masquée en succès
        assert "panne simulée" in run.detail and run.termine_le is not None
        assert couts_du_run(run)["total_usd"] == pytest.approx(0.6)           # la dépense est conservée


def test_un_run_en_erreur_sans_fichier_de_couts_reste_en_erreur(monkeypatch):
    monkeypatch.delenv("COUTS_FICHIER", raising=False)
    with SessionLocal() as db:
        rid = _run(db, "en_cours")
    from app.services import runs
    monkeypatch.setattr(runs.pipeline, "modules", lambda: (_ for _ in ()).throw(ValueError("boum")))
    runs.executer_run(rid, moteur="agent")
    with SessionLocal() as db:
        run = db.get(Run, rid)
        assert run.statut == "erreur" and "boum" in run.detail and couts_du_run(run) is None


# ---------- alertes ----------
def test_une_interruption_declenche_une_alerte_meme_en_cron():
    assert alertes.decider("interrompu", True, TOT, False) == (True, "interrompu")
    assert alertes.decider("termine", True, TOT, False) == (False, None)
    run = SimpleNamespace(id=5, detail="Interrompu : job arrêté", envoye_telegram=False)
    assert "interrompu" in alertes.message("interrompu", run) and "relances payantes" in alertes.message("relances", None)


# ---------- F. idempotence et date réelle ----------
def _selection(match="A - B", fixture="f1"):
    return {"match": match, "home_nom": "A", "fixture_id_oddspapi": fixture,
            "pick": {"categorie": "resultat", "marche": "1X2", "selection": "1", "cote": 2.0, "handicap": None, "proba_modele_pct": 55.0, "edge_pct": 1.0}}


def _match(db, run, quand):
    m = Match(run=run, domicile="A", exterieur="B", coup_envoi=quand, fixture_id_oddspapi="f1")
    db.add(m)
    db.flush()
    return m


def test_enregistrer_coupons_est_idempotent():
    with SessionLocal() as db:
        run = Run(source="api", statut="en_cours")
        db.add(run)
        db.flush()
        profil = {"cle": "coupon1", "nom": "C1"}
        premiers = enregistrer_coupons(db, run, [{"profil": profil, "selections": [_selection(), _selection("C - D", "f2")]}], {})
        db.commit()
        assert len(premiers) == 1
        deuxiemes = enregistrer_coupons(db, run, [{"profil": profil, "selections": [_selection()]}], {})
        db.commit()
        assert deuxiemes == [] and db.query(Coupon).count() == 1


def test_le_jour_du_coupon_est_celui_des_matchs_pas_celui_du_run():
    with SessionLocal() as db:
        run = Run(source="api", statut="en_cours")
        db.add(run)
        db.flush()
        demain = datetime.now(timezone.utc).replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1)
        m = _match(db, run, demain)
        index = {"f1": m}
        assert jour_du_coupon([_selection()], index) == demain.date()
        coupons = enregistrer_coupons(db, run, [{"profil": {"cle": "c", "nom": "C"}, "selections": [_selection()]}], index)
        db.commit()
        assert coupons[0].jour == demain.date()


def test_jour_du_coupon_prend_le_plus_tot_et_se_replie_sans_inventer():
    class M:
        def __init__(self, d):
            self.coup_envoi = d
    tard, tot = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc), datetime(2026, 11, 8, 12, 30, tzinfo=timezone.utc)
    index = {"f1": M(tard), "f2": M(tot)}
    assert jour_du_coupon([_selection(fixture="f1"), _selection("C - D", "f2")], index) == date(2026, 11, 8)
    assert jour_du_coupon([_selection(fixture="inconnu")], index, aujourd_hui=date(2026, 1, 2)) == date(2026, 1, 2)   # repli explicite
    assert jour_du_coupon([], {}, aujourd_hui=date(2026, 1, 2)) == date(2026, 1, 2)
    naif = {"f1": M(datetime(2026, 11, 9, 23, 30))}                                                                  # sans fuseau : lu comme UTC
    assert jour_du_coupon([_selection()], naif) == date(2026, 11, 9)


# ---------- H. cohérence des workflows ----------
def _charger(nom):
    import yaml
    return yaml.safe_load((RACINE / ".github" / "workflows" / nom).read_text(encoding="utf-8")), \
        (RACINE / ".github" / "workflows" / nom).read_text(encoding="utf-8")


def test_les_deux_workflows_sont_dans_le_meme_etat_de_pause():
    """Réactiver le pipeline SANS la vérification laisserait des coupons envoyés jamais jugés (et l'inverse n'a pas de sens) : les deux crons
    doivent être tous les deux actifs ou tous les deux en pause. Ce test NE réactive rien."""
    etats = {}
    for nom in ("pipeline-quotidien.yml", "verification-resultats.yml"):
        wf, texte = _charger(nom)
        declencheurs = wf.get(True) or wf.get("on")
        actif = "schedule" in declencheurs
        en_pause = "# PAUSE   - cron:" in texte
        assert actif != en_pause, f"{nom} : cron à la fois actif et en pause, ou ni l'un ni l'autre"
        assert "workflow_dispatch" in declencheurs
        etats[nom] = actif
    assert len(set(etats.values())) == 1, f"états différents : {etats}"


def test_les_crons_conserves_dans_les_deux_workflows():
    assert '- cron: "7,27,47 6-13 * * *"' in _charger("pipeline-quotidien.yml")[1]
    assert "*/15 12-23,0-2" in _charger("verification-resultats.yml")[1]


def test_le_workflow_ne_contient_plus_de_chat_telegram_en_dur():
    for nom in ("pipeline-quotidien.yml", "verification-resultats.yml"):
        assert "1446772592" not in _charger(nom)[1]
    env = _charger("pipeline-quotidien.yml")[0]["jobs"]["run"]["env"]
    assert "vars.TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES" in env["TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES"]
