import os
import tempfile

# Base temporaire et jeton de test — AVANT l'import de l'application (lus au chargement)
_dossier = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_dossier}/test.db"
os.environ["API_TOKEN"] = "jeton-test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

JETON = {"X-API-Key": "jeton-test"}


@pytest.fixture(autouse=True)
def base_vide():
    from app import models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def collecte_exemple():
    """Extrait réduit au format exact de donnees_collectees.json."""
    return {
        "date_collecte": "2026-09-25T12:00:00",
        "nb_matchs_demandes": 1, "nb_matchs_avec_marches": 1, "nb_marches_total": 2,
        "matchs": [{
            "match_demande": {"home": "RC Lens", "away": "Auxerre"},
            "api_football": {"home_name": "Lens", "away_name": "Auxerre", "league_name": "Ligue 1",
                             "fixture_date": "2026-09-25T19:00:00+00:00", "fixture_id_api_football": 42},
            "oddspapi": {"fixture_id": "idLENSAUX", "score_matching": 100, "tous_marches": [
                {"marche_id": "1010", "marche": "Over Under Full Time", "handicap": 2.5, "periode": "fulltime",
                 "selections": [{"selection": "Over", "cote": 1.8}, {"selection": "Under", "cote": 2.0}]},
                {"marche_id": "104", "marche": "Both Teams To Score", "handicap": 0.0, "periode": "fulltime",
                 "selections": [{"selection": "Yes", "cote": 1.7}, {"selection": "No", "cote": 2.1}]},
            ]},
            "serper": None, "stats_historiques": {"home": None, "away": None},
            "understat_xg": {"home": None, "away": None}, "clubelo": {"home": None, "away": None},
            "classement": {"home": None, "away": None},
        }],
    }


def selection(categorie, marche, selection_, cote, handicap=None):
    return {"match": "Lens vs Auxerre", "home_nom": "Lens", "away_nom": "Auxerre",
            "fixture_id_oddspapi": "idLENSAUX",
            "pick": {"categorie": categorie, "marche": marche, "handicap": handicap, "selection": selection_,
                     "cote": cote, "proba_modele_pct": 60.0, "edge_pct": 5.0, "guide": "g", "onglet": "o"}}


def profils_exemple():
    return [
        {"profil": {"cle": "profil1", "nom": "🛡️ COUPON 1", "cote_min": 5, "cote_max": 10},
         "selections": [selection("Total", "Over Under Full Time (2.5)", "Over", 1.8, 2.5),
                        selection("BTTS", "Both Teams To Score (0.0)", "Yes", 1.7, 0.0)]},
        {"profil": {"cle": "profil2", "nom": "⚖️ COUPON 2", "cote_min": 10, "cote_max": 50},
         "selections": [selection("BTTS", "Both Teams To Score (0.0)", "No", 2.1, 0.0)]},
        {"profil": {"cle": "profil3", "nom": "🔥 COUPON 3", "cote_min": 50, "cote_max": 100}, "selections": []},
    ]


def ticket_exemple():
    return {"date": "2026-09-25", "genere_a": "2026-09-25T12:05:00",
            "profils": [{"cle": p["profil"]["cle"], "nom": p["profil"]["nom"], "selections": p["selections"]}
                        for p in profils_exemple()],
            "resultat_envoye": False}
