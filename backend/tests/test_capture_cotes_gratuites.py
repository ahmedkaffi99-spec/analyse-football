from app.database import SessionLocal
from app.models_historique import CoteGratuite
from app.services import capture_cotes_gratuites as cg

CSV = ("Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,PSH,PSD,PSA,P>2.5,P<2.5,AHh,PAHH,PAHA\n"
       "E0,08/11/2026,15:00,Arsenal,Chelsea,1.9,3.6,4.2,1.95,3.7,4.3,1.85,2.0,-0.5,1.9,2.0\n"
       "XX,08/11/2026,15:00,A,B,2,3,4,2,3,4,,,,,\n"
       "F1,09/11/2026,20:45,Lyon,Nice,,,,2.1,3.4,3.5,,,,,\n")


def test_lignes_depuis_csv_filtre_ligues_et_cotes_vides():
    lignes = cg.lignes_depuis_csv(CSV, "2026-11-04T00:00:00")
    assert {l["ligue"] for l in lignes} == {"E0", "F1"}
    assert sum(1 for l in lignes if l["domicile"] == "Lyon") == 3      # seules les cotes PS présentes
    ah = [l for l in lignes if l["marche"] == "ah"]
    assert ah and all(l["ligne"] == -0.5 for l in ah)


def test_capture_idempotente_par_instantane():
    with SessionLocal() as db:
        n, matchs = cg.capturer(db, CSV)
        assert matchs == 2 and n > 0
        total = db.query(CoteGratuite).count()
        assert total == n
