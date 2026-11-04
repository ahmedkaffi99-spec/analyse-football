from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import Cote, Jambe, Match, Run
from app.services import persistance


def collecte():
    return {"matchs": [{
        "match_demande": {"home": "A", "away": "B"}, "api_football": None,
        "oddspapi": {"fixture_id": "f1", "start_time": "2026-11-08T15:00:00Z", "tous_marches": [
            {"marche_id": "x" * 50, "marche": "Total", "handicap": 2.5, "periode": "p" * 40,
             "selections": [{"selection": "Over", "cote": 1.9}, {"selection": "Under", "cote": 1.95}]}]}}]}


def test_coup_envoi_repli_oddspapi_cotes_horodatees_et_troncatures():
    with SessionLocal() as db:
        run = Run(source="api", statut="termine", lance_le=datetime.now(timezone.utc))
        db.add(run)
        index = persistance.enregistrer_collecte(db, run, collecte())
        m = index["f1"]
        assert m.coup_envoi is not None and m.coup_envoi.year == 2026         # API-Football absent : repli OddsPapi
        assert all(c.capture_le is not None and len(c.marche_id) == 32 and len(c.periode) == 32 for c in m.cotes)
        selections = [{"match": "A vs B", "fixture_id_oddspapi": "f1", "home_nom": "A",
                       "pick": {"categorie": "Total", "marche": "Total (2.5)", "handicap": 2.5, "selection": "Over", "cote": 1.9,
                                "proba_modele_pct": 55.0, "edge_pct": 1.0, "proba_poisson_pct": 58.0, "proba_marche_pct": 53.0}}]
        persistance.enregistrer_coupons(db, run, [{"profil": {"cle": "c1", "nom": "N"}, "selections": selections}], index)
        db.commit()
        j = db.query(Jambe).one()
        assert (j.proba_modele_pct, j.proba_modele_seul_pct, j.proba_marche_pct) == (55.0, 58.0, 53.0) and j.collecte_le is not None
