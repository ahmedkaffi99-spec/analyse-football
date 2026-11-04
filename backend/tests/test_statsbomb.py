import json

from app.database import SessionLocal
from app.models_historique import SbMatch, SbTir
from app.services import statsbomb as sb

META = {"match_id": 1, "match_date": "2024-01-02", "competition": {"competition_id": 9, "competition_name": "1. Bundesliga"},
        "season": {"season_id": 281, "season_name": "2023/2024"}, "home_team": {"home_team_name": "A"},
        "away_team": {"away_team_name": "B"}, "home_score": 2, "away_score": 1}


def ev(i, equipe, issue, xg, periode=1, t="Shot"):
    e = {"id": f"e{i}", "type": {"name": t}, "team": {"name": equipe}, "period": periode, "minute": 10, "location": [100, 40],
         "player": {"name": "P"}}
    if t == "Shot":
        e["shot"] = {"statsbomb_xg": xg, "outcome": {"name": issue}, "type": {"name": "Open Play"}, "body_part": {"name": "Right Foot"}}
    return e


EVENTS = [ev(1, "A", "Goal", 0.4), ev(2, "A", "Saved", 0.1), ev(3, "B", "Goal", 0.3),
          ev(4, "B", "Goal", 0.9, periode=5),                      # séance de tirs au but : exclue
          {"id": "og", "type": {"name": "Own Goal For"}, "team": {"name": "A"}, "period": 2}]


def faux(url):
    return json.dumps(EVENTS if "/events/" in url else [META]).encode()


def test_analyse_buts_xg_et_exclusion_des_tirs_au_but():
    tirs, buts, xg, nb = sb.analyser_evenements(EVENTS, "A", "B")
    assert buts == {"A": 2, "B": 1} and nb == {"A": 2, "B": 1}
    assert round(xg["A"], 2) == 0.5 and round(xg["B"], 2) == 0.3 and len(tirs) == 3


def test_import_idempotent_provenance_et_controle():
    with SessionLocal() as db:
        cr = sb.importer(db, 9, 281, 10, telecharge=faux)
        assert cr["ajoutes"] == 1 and not cr["erreurs"]
        assert sb.importer(db, 9, 281, 10, telecharge=faux)["existants"] == 1
        m = db.get(SbMatch, 1)
        assert m.coherent is True and len(m.hash_fichier) == 64 and "attribution" in m.licence_ref and m.url_source.endswith("/events/1.json")
        assert db.query(SbTir).count() == 3
        assert sb.controle_qualite(db)["scores_coherents"] == "1/1"


def test_erreur_reseau_rapportee_sans_bloquer():
    def casse(url):
        if "/events/" in url:
            raise OSError("réseau")
        return json.dumps([META]).encode()
    with SessionLocal() as db:
        cr = sb.importer(db, 9, 281, 10, telecharge=casse)
        assert cr["ajoutes"] == 0 and len(cr["erreurs"]) == 1
