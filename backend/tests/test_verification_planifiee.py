"""verification_due / `python -m app.taches verifier --si-du` : la vérification part à l'heure exacte
(coup d'envoi + 90 min), puis à chaque passage du cron jusqu'à la fin de la fenêtre — sans IA."""
from datetime import datetime, timezone

from app import taches
from app.database import SessionLocal
from app.services.verification import verification_due
from tests.conftest import collecte_exemple, ticket_exemple

COUP_ENVOI = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)  # fixture_date de collecte_exemple


def _due(heure, minute, jour=25):
    with SessionLocal() as db:
        return verification_due(db, datetime(2026, 9, jour, heure, minute, tzinfo=timezone.utc))


def test_pas_de_verification_avant_90_minutes(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    due, _ = _due(20, 29)
    assert due is False


def test_verification_due_a_l_heure_exacte_puis_a_chaque_passage(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    assert _due(20, 30)[0] is True   # 19h00 + 90 min
    assert _due(21, 45)[0] is True   # toujours dans la fenêtre de 4 h
    assert _due(22, 59)[0] is True


def test_fenetre_close_puis_rattrapage_horaire(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    assert _due(23, 30)[0] is False  # 19h00 + 4 h = 23h00 passé, pas le passage de rattrapage
    assert _due(23, 10)[0] is True   # minute < 15 : rattrapage horaire


def test_rien_en_attente(client):
    with SessionLocal() as db:
        due, raison = verification_due(db, COUP_ENVOI)
    assert due is False and "aucune jambe" in raison


def test_cli_si_du_ne_fait_rien_avant_l_heure(client, monkeypatch, capsys):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    monkeypatch.setattr("app.taches.verification_due", lambda db: (False, "test"))
    appels = []
    monkeypatch.setattr("app.taches.verifier_coupons_en_attente", lambda db: appels.append(1) or {})
    assert taches.main(["verifier", "--si-du"]) == 0
    assert appels == []
    assert "Rien à vérifier" in capsys.readouterr().out


def test_cli_si_du_verifie_quand_c_est_l_heure(client, monkeypatch, capsys):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    monkeypatch.setattr("app.taches.verification_due", lambda db: (True, "test"))
    appels = []
    monkeypatch.setattr("app.taches.verifier_coupons_en_attente", lambda db: appels.append(1) or {})
    assert taches.main(["verifier", "--si-du"]) == 0
    assert appels == [1]
