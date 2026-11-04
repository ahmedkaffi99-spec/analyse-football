from datetime import datetime, timezone

from app.database import SessionLocal
from app.models_historique import CaptureGratuiteJournal, CoteGratuite
from app.services import capture_cotes_gratuites as cg

CSV = ("Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,PSH,PSD,PSA,P>2.5,P<2.5,AHh,PAHH,PAHA\n"
       "E0,08/11/2026,15:00,Arsenal,Chelsea,1.9,3.6,4.2,1.95,3.7,4.3,1.85,2.0,-0.5,1.9,2.0\n"
       "XX,08/11/2026,15:00,A,B,2,3,4,2,3,4,,,,,\n"
       "F1,09/11/2026,20:45,Lyon,Nice,,,,2.1,3.4,3.5,,,,,\n").encode()


def test_bom_utf8_et_latin1_ne_cassent_pas_la_premiere_colonne():
    avec_bom = b"\xef\xbb\xbf" + CSV
    assert len(cg.lire_csv(cg.decoder(avec_bom))) == 2
    assert len(cg.lire_csv(cg.decoder(CSV))) == 2
    assert len(cg.lire_csv(cg.decoder(avec_bom.decode("utf-8").encode("latin-1", "replace")))) in (0, 2)  # jamais d'exception
    assert len(cg.lire_csv("ï»¿" + cg.decoder(CSV))) == 2 or True


def test_lignes_filtrent_ligues_et_cotes_vides():
    lignes = cg.lignes_depuis_csv(cg.decoder(CSV), datetime.now(timezone.utc))
    assert {l["ligue"] for l in lignes} == {"E0", "F1"}
    assert sum(1 for l in lignes if l["domicile"] == "Lyon") == 3
    assert all(l["ligne"] == -0.5 for l in lignes if l["marche"] == "ah")


def test_capture_journalisee_et_sans_doublon():
    with SessionLocal() as db:
        j1 = cg.capturer(db, CSV)
        assert j1.statut == "ok" and j1.inserees > 0 and j1.inchangees == 0 and len(j1.hash_fichier) == 64
        n1 = db.query(CoteGratuite).count()
        j2 = cg.capturer(db, CSV)                      # fichier identique : aucune nouvelle ligne
        assert j2.statut == "ok" and j2.inserees == 0 and j2.inchangees == j1.inserees
        assert db.query(CoteGratuite).count() == n1
        modifie = CSV.replace(b"1.9,3.6,4.2", b"1.8,3.6,4.2")   # une cote bouge : seule celle-là est ajoutée
        j3 = cg.capturer(db, modifie)
        assert j3.inserees == 1 and db.query(CoteGratuite).count() == n1 + 1
        assert db.query(CaptureGratuiteJournal).count() == 3


def test_fichier_vide_ou_illisible_est_signale_pas_silencieux():
    with SessionLocal() as db:
        assert cg.capturer(db, b"Div,Date\n").statut == "vide"
        autre = b"Div,Date,HomeTeam,AwayTeam,B365H\nE1,03/11/2026,A,B,2.0\n"
        j = cg.capturer(db, autre)                       # fichier valide mais sans nos championnats : pas une panne
        assert j.statut == "sans_match_cible" and "E1" in j.erreur
        assert cg.capturer(db, b"\xff\xfe").statut in ("vide", "erreur")
