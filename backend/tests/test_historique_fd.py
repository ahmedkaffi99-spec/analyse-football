from datetime import date

from app.database import SessionLocal
from app.models_historique import FdMatch
from app.services import historique_fd as hf

ENTETE = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,Referee,HS,AS,HC,AC,HY,AY,PSH,PSD,PSA,PSCH,PSCD,PSCA,"
          "B365>2.5,B365<2.5,B365C>2.5,B365C<2.5,AHh,AHCh,B365AHH,B365AHA,B365CAHH,B365CAHA")
CSV = (ENTETE + "\nE0,10/08/2024,12:30,Arsenal,Chelsea,2,1,H,1,0,X Y,12,8,6,3,1,2,2.0,3.5,3.8,1.95,3.6,4.0,1.9,1.95,1.85,2.0,-0.5,-0.75,1.9,2.0,1.95,1.95\n"
       "E0,11/08/2024,15:00,Fulham,Leeds,,,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"          # pas de score : ignoré
       "E0,12/08/2024,15:00,Ipswich,Wolves,0,0,D,0,0,,,,,,,,2.5,3.2,2.9,,,,,,,,,,,,,\n").encode()


def test_parse_cotes_stats_et_ignore_matchs_sans_score():
    ls = hf.lignes(hf.decoder(CSV), "E0", "2425")
    assert len(ls) == 2
    a = ls[0]
    assert a["buts_dom"] == 2 and a["stats"]["HS"] == 12 and a["stats"]["HC"] == 6
    c = a["cotes"]
    assert c["pin_1x2_ouv"] == [2.0, 3.5, 3.8] and c["pin_1x2_clo"] == [1.95, 3.6, 4.0]
    assert c["b365_ou25_clo"] == [1.85, 2.0] and c["ah_ligne_clo"] == -0.75 and c["b365_ah_clo"] == [1.95, 1.95]
    assert ls[1]["cotes"] == {"pin_1x2_ouv": [2.5, 3.2, 2.9]}          # valeurs absentes : clé absente, rien d'inventé


def test_import_insert_only_idempotent_et_qualite():
    with SessionLocal() as db:
        assert hf.importer_fichier(db, "E0", "2425", CSV, "u") == (2, 0, 2)
        assert hf.importer_fichier(db, "E0", "2425", CSV, "u") == (0, 2, 2)      # relance : rien de nouveau, rien de modifié
        assert db.query(FdMatch).count() == 2
        q = hf.rapport_qualite(db)[0]
        assert q["matchs"] == 2 and q["pin_1x2_cloture_%"] == 50 and q["tirs_%"] == 50 and q["dates_hors_saison"] == 0
        assert 0 < q["marge_pin_moy_%"] < 10


def test_fichier_manquant_est_rapporte():
    def casse(saison, ligue):
        raise OSError("404")
    with SessionLocal() as db:
        cr = hf.importer(db, ["2425"], ["E0"], telecharge=casse)
        assert cr["fichiers"] == 0 and len(cr["echecs"]) == 1


def test_saison_courante():
    from datetime import date as d
    assert hf.saison_courante(d(2026, 11, 4)) == "2627" and hf.saison_courante(d(2027, 3, 1)) == "2627" and hf.saison_courante(d(2026, 6, 30)) == "2526"
