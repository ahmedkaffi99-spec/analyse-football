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


def _faux_agent_pilote(monkeypatch, resultat):
    def fausse_executer(mission=None, telegram=True):
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
