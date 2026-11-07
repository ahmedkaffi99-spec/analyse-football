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


def test_budget_restant_selon_la_variable(monkeypatch):
    with SessionLocal() as db:
        _run(db, _couts(1.0))
        monkeypatch.delenv("BUDGET_JOUR_USD", raising=False)
        assert budget.budget_restant(db) is None                        # pas de plafond
        monkeypatch.setenv("BUDGET_JOUR_USD", "3")
        assert budget.budget_restant(db) == 2.0
        monkeypatch.setenv("BUDGET_JOUR_USD", "0.5")
        assert budget.budget_restant(db) == 0.0                         # jamais négatif
        monkeypatch.setenv("BUDGET_JOUR_USD", "n'importe quoi")
        assert budget.budget_restant(db) == 0.0                         # mal saisi : prudence
        monkeypatch.setenv("BUDGET_JOUR_USD", "aucun")
        assert budget.budget_restant(db) is None


def test_resume_par_jour_et_par_modele(monkeypatch):
    monkeypatch.setenv("BUDGET_JOUR_USD", "5")
    with SessionLocal() as db:
        _run(db, _couts(0.4, modele="gpt"))
        _run(db, _couts(0.2, modele="gemini"))
        r = budget.resume(db)
        assert r["depense_aujourdhui_usd"] == pytest.approx(0.6) and r["plafond_jour_usd"] == 5.0
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


def test_le_restant_est_transmis_a_l_agent_et_les_couts_sont_enregistres(monkeypatch):
    monkeypatch.setenv("BUDGET_JOUR_USD", "2")
    appels = []
    _pilote_espion(monkeypatch, _couts(0.7), appels)
    assert taches.main(["run", "--moteur", "agent"]) == 0
    assert taches.main(["run", "--moteur", "agent"]) == 0
    assert appels == [2.0, pytest.approx(1.3)]                          # le 2e run voit le coût du 1er
    with SessionLocal() as db:
        assert budget.depense_du_jour(db) == pytest.approx(1.4)
        assert budget.couts_du_run(db.query(Run).first())["total_usd"] == 0.7


def test_sans_plafond_l_agent_n_est_pas_contraint(monkeypatch):
    monkeypatch.delenv("BUDGET_JOUR_USD", raising=False)
    appels = []
    _pilote_espion(monkeypatch, _couts(0.7), appels)
    assert taches.main(["run", "--moteur", "agent"]) == 0
    assert appels == [None]


def test_alerte_budget_envoyee_une_fois_par_run_concerne(monkeypatch):
    msgs = []
    with SessionLocal() as db:
        avec = _run(db, _couts(0.4, alerte="vote réduit ou annulé : gemini (plafond journalier atteint)"))
        sans = _run(db, _couts(0.1))
        assert "plafond journalier atteint" in alertes.envoyer_alerte_budget(db, avec.id, lambda m: msgs.append(m) or True)
        assert alertes.envoyer_alerte_budget(db, sans.id, lambda m: msgs.append(m) or True) is None
        assert alertes.envoyer_alerte_budget(db, avec.id, lambda m: (_ for _ in ()).throw(RuntimeError("HS"))) is None   # jamais bloquant
    assert len(msgs) == 1 and msgs[0].startswith("💰 Budget IA")


def test_detail_d_un_run_abandonne_ne_pollue_pas_l_alerte_d_abandon():
    with SessionLocal() as db:
        run = _run(db, _couts(0.35), statut="abandonne", abandon=True)
        texte = alertes.message("abandonne", run)
        assert "raison d'abandon" in texte and "COUTS_AGENT" not in texte


def test_commande_budget_en_lecture_seule(monkeypatch, capsys):
    monkeypatch.setenv("BUDGET_JOUR_USD", "3")
    with SessionLocal() as db:
        _run(db, _couts(0.5, modele="openai/gpt-6.1-sol"))
        avant = db.query(Run).count()
    assert taches.main(["budget"]) == 0
    sortie = capsys.readouterr().out
    assert "restant : 2.50 $" in sortie and "openai/gpt-6.1-sol" in sortie
    with SessionLocal() as db:
        assert db.query(Run).count() == avant


def test_alerte_avant_epuisement_puis_a_l_epuisement(monkeypatch):
    monkeypatch.setenv("BUDGET_JOUR_USD", "3")
    monkeypatch.delenv("BUDGET_ALERTE_PCT", raising=False)           # 80 % -> 2,40 $
    msgs = []
    notifier = lambda m: msgs.append(m) or True  # noqa: E731
    with SessionLocal() as db:
        r1 = _run(db, _couts(1.0))                                   # 1,00 $ : sous le seuil
        assert alertes.envoyer_alerte_seuil_budget(db, r1.id, notifier) is None
        r2 = _run(db, _couts(1.5))                                   # 2,50 $ : franchit 80 %
        texte = alertes.envoyer_alerte_seuil_budget(db, r2.id, notifier)
        assert "presque épuisé" in texte and "2.50" in texte and "0.50" in texte
        r3 = _run(db, _couts(0.1))                                   # 2,60 $ : déjà au-dessus du seuil, pas de nouvelle alerte
        assert alertes.envoyer_alerte_seuil_budget(db, r3.id, notifier) is None
        r4 = _run(db, _couts(0.5))                                   # 3,10 $ : épuisé
        assert "épuisé" in alertes.envoyer_alerte_seuil_budget(db, r4.id, notifier)
        r5 = _run(db, _couts(0.2))                                   # déjà épuisé : silence (une alerte d'épuisement par jour)
        assert alertes.envoyer_alerte_seuil_budget(db, r5.id, notifier) is None


def test_alerte_seuil_sans_plafond_ni_erreur(monkeypatch):
    monkeypatch.delenv("BUDGET_JOUR_USD", raising=False)
    with SessionLocal() as db:
        run = _run(db, _couts(5.0))
        assert alertes.envoyer_alerte_seuil_budget(db, run.id, lambda m: True) is None          # pas de plafond
        monkeypatch.setenv("BUDGET_JOUR_USD", "3")
        assert alertes.envoyer_alerte_seuil_budget(db, run.id, lambda m: (_ for _ in ()).throw(RuntimeError("HS"))) is None
        monkeypatch.setenv("BUDGET_ALERTE_PCT", "abc")
        assert alertes.seuil_alerte_budget_pct() == 80.0


def test_le_jour_budgetaire_est_utc(monkeypatch):
    """Un run de la veille UTC (même à 23h59) ne compte pas dans le budget d'aujourd'hui ; un run d'hier ne bloque pas aujourd'hui."""
    monkeypatch.setenv("BUDGET_JOUR_USD", "1")
    maintenant = datetime(2026, 11, 7, 0, 5, tzinfo=timezone.utc)
    with SessionLocal() as db:
        _run(db, _couts(1.0), quand=datetime(2026, 11, 6, 23, 59, tzinfo=timezone.utc))
        assert budget.depense_du_jour(db, maintenant) == 0.0
        assert budget.budget_restant(db, maintenant) == 1.0
        _run(db, _couts(0.4), quand=datetime(2026, 11, 7, 0, 1, tzinfo=timezone.utc))
        assert budget.depense_du_jour(db, maintenant) == pytest.approx(0.4)
