"""Phase 3 (06/11/2026) : budget IA journalier — mesure depuis les journaux des runs, restant transmis à l'agent, alertes, aucune table."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import taches
from app.database import SessionLocal
from app.models import Run
from app.services import alertes, budget, pipeline
from tests.conftest import collecte_exemple, profils_exemple
from tests.test_moteur_agent import _profil_unique


def _couts(total, alerte=None, modele="gpt"):
    c = {"pilote": {}, "vote": [{"modele": modele, "cout_usd": total, "tokens_entree": 100, "tokens_sortie": 10, "appels": 2,
                                 "coupons_retenus": 1}], "gagnants": {}, "total_usd": total, "modeles_ignores": []}
    if alerte:
        c["alerte"] = alerte
    return c


def _run(db, couts, statut="termine", quand=None, abandon=False):
    detail = ("raison d'abandon" + budget.texte_couts_pour_detail(couts)) if abandon else "JOURNAL_AGENT " + json.dumps({"couts": couts})
    run = Run(source="api", statut=statut, detail=detail, lance_le=quand or datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    return run


def test_depense_du_jour_somme_les_runs_du_jour_seulement():
    with SessionLocal() as db:
        _run(db, _couts(0.4))
        _run(db, _couts(0.35), statut="abandonne", abandon=True)       # un run abandonné a quand même dépensé
        _run(db, _couts(9.0), quand=datetime.now(timezone.utc) - timedelta(days=1))
        db.add(Run(source="api", statut="erreur", detail="panne sans coûts"))
        db.commit()
        assert budget.depense_du_jour(db) == pytest.approx(0.75)


def test_aucun_plafond_de_budget_la_variable_est_ignoree(monkeypatch):
    """Plafond journalier SUPPRIMÉ (07/11/2026, demande du propriétaire) : BUDGET_JOUR_USD n'a plus aucun effet, quelle que soit sa valeur."""
    with SessionLocal() as db:
        _run(db, _couts(1.0))
    for valeur in ("3", "0", "0.5", "n'importe quoi", "aucun"):
        monkeypatch.setenv("BUDGET_JOUR_USD", valeur)
        assert budget.budget_jour_usd() is None
    assert not hasattr(budget, "budget_restant")


def test_resume_par_jour_et_par_modele(monkeypatch):
    with SessionLocal() as db:
        _run(db, _couts(0.4, modele="gpt"))
        _run(db, _couts(0.2, modele="gemini"))
        r = budget.resume(db)
        assert r["depense_aujourdhui_usd"] == pytest.approx(0.6) and "plafond_jour_usd" not in r
        assert r["par_modele"]["gpt"]["cout_usd"] == 0.4 and r["par_modele"]["gemini"]["tokens_entree"] == 100
        assert list(r["par_jour"].values()) == [pytest.approx(0.6)]


def _pilote_espion(monkeypatch, couts, appels):
    profil = _profil_unique()
    selections = profils_exemple()[0]["selections"]

    def executer(mission=None, telegram=True, profils=None, ignorer_diversite_croisee=False, contexte_supplementaire=None,
                 donnees_reprises=None, budget_restant_usd=None):
        appels.append(budget_restant_usd)
        return {"donnees": collecte_exemple(), "resultats_profils": [{"profil": profil, "selections": selections}], "textes": ["t"],
                "envoye": True, "raison_abandon": None, "couts": couts, "journal": {"couts": couts}}

    monkeypatch.setattr(pipeline, "charger_agent_pilote", lambda: SimpleNamespace(executer=executer))


def test_l_agent_ne_recoit_aucun_budget_et_les_couts_sont_enregistres(monkeypatch):
    monkeypatch.setenv("BUDGET_JOUR_USD", "2")                          # ignorée
    appels = []
    _pilote_espion(monkeypatch, _couts(0.7), appels)
    assert taches.main(["run", "--moteur", "agent"]) == 0
    assert taches.main(["run", "--moteur", "agent"]) == 0
    assert appels == [None, None]                                       # aucun plafond transmis, même après 0,7 $ déjà dépensés
    with SessionLocal() as db:
        assert budget.depense_du_jour(db) == pytest.approx(1.4)         # le coût reste mesuré
        assert budget.couts_du_run(db.query(Run).first())["total_usd"] == 0.7


def test_sans_plafond_l_agent_n_est_pas_contraint(monkeypatch):
    monkeypatch.delenv("BUDGET_JOUR_USD", raising=False)
    appels = []
    _pilote_espion(monkeypatch, _couts(0.7), appels)
    assert taches.main(["run", "--moteur", "agent"]) == 0
    assert appels == [None]


def test_detail_d_un_run_abandonne_ne_pollue_pas_l_alerte_d_abandon():
    with SessionLocal() as db:
        run = _run(db, _couts(0.35), statut="abandonne", abandon=True)
        texte = alertes.message("abandonne", run)
        assert "raison d'abandon" in texte and "COUTS_AGENT" not in texte


def test_commande_budget_en_lecture_seule(monkeypatch, capsys):
    with SessionLocal() as db:
        _run(db, _couts(0.5, modele="openai/gpt-6.1-sol"))
        avant = db.query(Run).count()
    assert taches.main(["budget"]) == 0
    sortie = capsys.readouterr().out
    assert "Dépensé aujourd'hui : 0.50 $ (aucun plafond)" in sortie and "restant" not in sortie and "openai/gpt-6.1-sol" in sortie
    with SessionLocal() as db:
        assert db.query(Run).count() == avant


def test_le_jour_budgetaire_est_utc(monkeypatch):
    """Un run de la veille UTC (même à 23h59) ne compte pas dans la dépense d'aujourd'hui (le suivi des coûts reste mesuré, sans plafond)."""
    maintenant = datetime(2026, 11, 7, 0, 5, tzinfo=timezone.utc)
    with SessionLocal() as db:
        _run(db, _couts(1.0), quand=datetime(2026, 11, 6, 23, 59, tzinfo=timezone.utc))
        assert budget.depense_du_jour(db, maintenant) == 0.0
        _run(db, _couts(0.4), quand=datetime(2026, 11, 7, 0, 1, tzinfo=timezone.utc))
        assert budget.depense_du_jour(db, maintenant) == pytest.approx(0.4)
