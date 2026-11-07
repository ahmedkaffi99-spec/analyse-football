"""Phase 1 (06/11/2026) : plus d'échec silencieux — alertes Telegram sur abandon, erreur, envoi partiel, run bloqué."""
import json
from datetime import datetime, timezone

import pytest

from app.database import SessionLocal
from app.models import Run
from app.services import alertes

TOT = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)       # passage intermédiaire
DERNIER = datetime(2026, 11, 6, 13, 27, tzinfo=timezone.utc)  # dernier passage de la fenêtre


@pytest.fixture(autouse=True)
def temoin(tmp_path, monkeypatch):
    monkeypatch.setattr(alertes, "FICHIER_TEMOIN", tmp_path / "alerte.flag")
    return tmp_path / "alerte.flag"


def _run(db, statut, detail="", envoye=False, quand=TOT):
    run = Run(source="api", statut=statut, detail=detail, envoye_telegram=envoye, lance_le=quand)
    db.add(run)
    db.commit()
    return run.id


def _notifier(messages, ok=True):
    return lambda m: messages.append(m) or ok


def test_decider_regles():
    d = alertes.decider
    assert d("abandonne", False, TOT, False) == (True, "abandonne")          # run manuel : tout de suite
    assert d("abandonne", True, TOT, False) == (False, "abandonne")          # cron : les passages suivants réessaient
    assert d("abandonne", True, DERNIER, False) == (True, "abandonne")       # cron : dernier passage
    assert d("erreur", True, TOT, False) == (True, "erreur")                 # erreur : tout de suite
    assert d("termine", True, DERNIER, False)[0] is False
    assert d("erreur", True, DERNIER, True)[0] is False                      # jamais deux alertes le même jour
    assert d("termine", True, TOT, False, envoi_partiel="2/3") == (True, "partiel")


def test_abandon_au_dernier_passage_alerte_une_seule_fois(temoin):
    msgs = []
    with SessionLocal() as db:
        run_id = _run(db, "abandonne", "aucun match collecté", quand=DERNIER)
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier(msgs), cron=True, maintenant=DERNIER) == "abandonne"
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier(msgs), cron=True, maintenant=DERNIER) is None
        assert alertes.MARQUEUR in db.get(Run, run_id).detail
    assert len(msgs) == 1 and "aucun match collecté" in msgs[0]
    assert temoin.exists()   # l'étape d'alerte du workflow ne doublonne pas


def test_abandon_en_cours_de_fenetre_reste_silencieux():
    msgs = []
    with SessionLocal() as db:
        run_id = _run(db, "abandonne", "collecte vide")
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier(msgs), cron=True, maintenant=TOT) is None
    assert msgs == []


def test_erreur_alerte_tout_de_suite_meme_en_cron():
    msgs = []
    with SessionLocal() as db:
        run_id = _run(db, "erreur", "panne _API_")
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier(msgs), cron=True, maintenant=TOT) == "erreur"
    assert "panne API" in msgs[0]   # caractères Markdown retirés


def test_envoi_partiel_alerte_sans_alterer_le_journal():
    msgs = []
    detail = "JOURNAL_AGENT " + json.dumps({"envoi_partiel": "2/3"})
    with SessionLocal() as db:
        run_id = _run(db, "termine", detail, envoye=True)
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier(msgs), cron=True, maintenant=TOT) == "partiel"
        assert db.get(Run, run_id).detail == detail
    assert "partiel" in msgs[0]


def test_echec_de_la_notification_ne_pose_pas_de_marqueur_et_ne_leve_pas():
    with SessionLocal() as db:
        run_id = _run(db, "erreur", "x")
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier([], ok=False), cron=False, maintenant=TOT) is None
        assert alertes.MARQUEUR not in db.get(Run, run_id).detail

        def casse(_):
            raise RuntimeError("telegram HS")
        assert alertes.envoyer_alerte_si_besoin(db, run_id, casse, cron=False, maintenant=TOT) is None


def test_passage_saute_alerte_seulement_au_dernier_passage_sans_envoi():
    msgs = []
    with SessionLocal() as db:
        _run(db, "en_cours", "", quand=TOT)
        assert alertes.envoyer_alerte_passage_saute(db, _notifier(msgs), maintenant=TOT) is None
        assert alertes.envoyer_alerte_passage_saute(db, _notifier(msgs), maintenant=DERNIER) == "bloque"
        assert alertes.envoyer_alerte_passage_saute(db, _notifier(msgs), maintenant=DERNIER) is None   # une seule fois
    assert len(msgs) == 1


def test_passage_saute_silencieux_si_un_coupon_est_deja_parti():
    msgs = []
    with SessionLocal() as db:
        _run(db, "termine", "", envoye=True, quand=TOT)
        assert alertes.envoyer_alerte_passage_saute(db, _notifier(msgs), maintenant=DERNIER) is None
    assert msgs == []


def test_tache_run_en_erreur_envoie_l_alerte(monkeypatch):
    from app import taches
    from app.services import pipeline
    from tests.conftest import collecte_exemple, profils_exemple
    from tests.test_api import _faux_pipeline

    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple(), erreur=RuntimeError("panne"))
    msgs = []
    reel = pipeline.modules
    def modules():
        a, ae, c = reel()
        ae.notifier_telegram = lambda m: msgs.append(m) or True
        return a, ae, c
    monkeypatch.setattr(pipeline, "modules", modules)
    assert taches.main(["run", "--telegram", "--si-aucun-ticket-aujourdhui", "--moteur", "deterministe"]) == 1
    assert len(msgs) == 1 and "en erreur" in msgs[0]


def test_erreur_apres_envoi_est_signalee_comme_telle():
    msgs = []
    with SessionLocal() as db:
        run_id = _run(db, "erreur", "[APRES_ENVOI] panne base", envoye=True)
        assert alertes.envoyer_alerte_si_besoin(db, run_id, _notifier(msgs), cron=True, maintenant=TOT) == "erreur"
    assert "APRÈS l'envoi" in msgs[0] and "ne seront pas renvoyés" in msgs[0]


def test_passage_saute_silencieux_si_un_run_en_erreur_a_deja_envoye():
    msgs = []
    with SessionLocal() as db:
        _run(db, "erreur", "[APRES_ENVOI] x", envoye=True)
        assert alertes.envoyer_alerte_passage_saute(db, _notifier(msgs), maintenant=DERNIER) is None
    assert msgs == []
