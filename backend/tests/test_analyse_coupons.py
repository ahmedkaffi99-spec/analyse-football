"""Analyse des coupons envoyés : faits chiffrés, repli déterministe, nettoyage Markdown, journal de l'agent."""
import json

from app.database import SessionLocal
from app.models import Coupon, Run
from app.services import analyse_coupons as ac
from tests.conftest import collecte_exemple, ticket_exemple


def _coupons(db):
    return list(db.query(Coupon).order_by(Coupon.profil))


def test_faits_et_analyse_deterministe(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    with SessionLocal() as db:
        coupons = _coupons(db)
        faits = ac.faits_coupons(coupons)
        assert faits and faits[0]["nb_jambes"] == len(coupons[0].jambes)
        j = faits[0]["jambes"][0]
        assert j["proba_implicite_cote_pct"] == round(100 / j["cote"], 1)
        texte = ac.analyse_deterministe(faits)
        assert faits[0]["coupon"] in texte and "cote" in texte


def test_journal_agent_alimente_les_idees_de_selection(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    with SessionLocal() as db:
        coupon = _coupons(db)[0]
        journal = {"strategies": {coupon.profil: "Prudent : lignes nettes, un pari par match."},
                   "raisons": {coupon.profil: [{"match": coupon.jambes[0].libelle_match,
                                                "cote": coupon.jambes[0].cote, "raison": "Absences côté adverse."}]}}
        db.get(Run, coupon.run_id).detail = "JOURNAL_AGENT " + json.dumps(journal)
        db.commit()
        faits = ac.faits_coupons([coupon])
    assert faits[0]["strategie_agent"].startswith("Prudent")
    assert faits[0]["jambes"][0]["raison_agent"] == "Absences côté adverse."
    assert "Idée de sélection" in ac.analyse_deterministe(faits)


def test_matchs_partages_et_jambes_fragiles(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    with SessionLocal() as db:
        coupons = _coupons(db)
        coupons[0].jambes[0].proba_modele_pct = 55.0
        faits = ac.faits_coupons(coupons)
    assert faits[0]["jambes_fragiles"]


def test_ia_nettoyee_ou_repli():
    faits = [{"coupon": "C1", "jambes": []}]
    assert ac.analyse_par_ia(faits, lambda *_a, **_k: "Texte *gras* avec_underscore et [lien] " + "x" * 100) \
        .count("*") == 0
    assert "_" not in ac.analyse_par_ia(faits, lambda *_a, **_k: "a_b " * 40)

    def en_panne(*_a, **_k):
        raise RuntimeError("pas de clé")
    assert ac.analyse_par_ia(faits, en_panne) is None
    assert ac.analyse_par_ia(faits, lambda *_a, **_k: "trop court") is None


def test_message_analyse_sans_ia_est_borne(client):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    with SessionLocal() as db:
        message = ac.message_analyse(_coupons(db), avec_ia=False)
    assert message.startswith("🔎 ANALYSE DES") and len(message) <= ac.MAX_CARACTERES_MESSAGE
