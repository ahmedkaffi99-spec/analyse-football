"""14/11/2026 : (1) paris déjà pris par un autre run du jour (plafond « un même pari par jour ») ; (2) bilan Telegram attendant TOUTES les jambes, y compris celles d'un coupon déjà perdu."""
from datetime import date

from app.database import SessionLocal
from app.models import Coupon, Run
from app.services.bilan import envoyer_bilans
from app.services.paris_du_jour import paris_deja_pris
from tests.conftest import collecte_exemple, ticket_exemple


def _importer(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})


def test_paris_deja_pris_par_un_autre_run(client, monkeypatch):
    monkeypatch.delenv("PLAFOND_PARI_JOUR", raising=False)
    _importer(client)
    with SessionLocal() as db:
        jour = db.query(Coupon).first().jour
        pris = paris_deja_pris(db, run_id=2, jour=jour)
        assert ("Lens vs Auxerre", "Total", "over", 2.5) in pris and ("Lens vs Auxerre", "BTTS", "yes", 0.0) in pris
        assert paris_deja_pris(db, run_id=1, jour=jour) == frozenset()                # jamais ses propres paris
        assert paris_deja_pris(db, run_id=2, jour=date(2020, 1, 1)) == frozenset()      # un autre jour : rien


def test_plafond_des_paris_du_jour_desactivable(client, monkeypatch):
    _importer(client)
    monkeypatch.setenv("PLAFOND_PARI_JOUR", "0")
    with SessionLocal() as db:
        assert paris_deja_pris(db, run_id=2, jour=db.query(Coupon).first().jour) == frozenset()


def test_bilan_attend_les_jambes_en_attente_d_un_coupon_deja_perdu(client):
    _importer(client)
    messages = []
    with SessionLocal() as db:
        db.get(Run, 1).envoye_telegram = True
        coupons = db.query(Coupon).all()
        for c in coupons:
            c.statut = "perdu"
            for j in c.jambes:
                j.resultat = "perdu"
        coupon_avec_jambes = next(c for c in coupons if len(c.jambes) >= 2)
        coupon_avec_jambes.jambes[-1].resultat = "en_attente"      # coupon perdu, mais un match reste à jouer
        db.commit()
        assert envoyer_bilans(db, lambda m: messages.append(m) or True) == 0           # on attend la fin du dernier match
        coupon_avec_jambes.jambes[-1].resultat = "perdu"
        db.commit()
        assert envoyer_bilans(db, lambda m: messages.append(m) or True) == 1
    assert messages
