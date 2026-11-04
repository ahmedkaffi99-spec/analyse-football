import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import understat_termux as u


def js(obj):
    """Imite l'encodage d'Understat : JSON.parse('...') avec guillemets échappés en \\xNN."""
    return json.dumps(obj).replace('"', "\\x22").replace("{", "\\x7B").replace("}", "\\x7D")


LIGUE = ("<script>var datesData = JSON.parse('" + js([
    {"id": "100", "isResult": True, "h": {"id": "1", "title": "Arsenal"}, "a": {"id": "2", "title": "Chelsea"},
     "goals": {"h": "2", "a": "1"}, "xG": {"h": "1.8", "a": "0.9"}, "datetime": "2025-01-01 15:00:00",
     "forecast": {"w": "0.5", "d": "0.3", "l": "0.2"}}]) + "')</script>"
         "<script>var teamsData = JSON.parse('" + js({"1": {"title": "Arsenal", "history": [
             {"result": "w", "scored": 2, "missed": 1, "xG": "1.8", "xGA": "0.9", "npxG": "1.8", "npxGA": "0.9",
              "ppda": {"att": 100, "def": 10}}]}}) + "')</script>")
MATCH = "<script>var shotsData = JSON.parse('" + js({"h": [{"id": "9", "minute": "12", "xG": "0.4", "X": "0.9", "Y": "0.5",
                                                           "result": "Goal", "player": "Saka", "h_a": "h"}], "a": []}) + "')</script>"


def test_extraire_et_stocker(tmp_path, monkeypatch):
    con = sqlite3.connect(tmp_path / "t.db")
    u.init(con)
    assert u.stocker_ligue(con, "EPL", 2024, LIGUE, "https://x/league") == 1
    assert u.stocker_tirs(con, "100", MATCH, "https://x/match/100") == 1
    m = con.execute("select dom, buts_dom, xg_dom, source, hash_brut from us_matchs").fetchone()
    assert m[:3] == ("Arsenal", 2, 1.8) and m[3] == "understat.com" and len(m[4]) == 64
    assert con.execute("select xg, joueur from us_tirs").fetchone() == (0.4, "Saka")
    assert con.execute("select ppda from us_equipes_saison").fetchone()[0] == 10.0


def test_page_sans_donnees_donne_none():
    assert u.extraire("<html>erreur</html>", "datesData") is None


def test_saison_courante():
    from datetime import datetime
    assert u.saison_courante(datetime(2026, 11, 4)) == 2026 and u.saison_courante(datetime(2026, 3, 1)) == 2025


def test_verrou_autorisation(monkeypatch):
    monkeypatch.delenv("UNDERSTAT_AUTORISATION_ECRITE", raising=False)
    assert u.autorisation_ecrite() is None
    monkeypatch.setenv("UNDERSTAT_AUTORISATION_ECRITE", "court")
    assert u.autorisation_ecrite() is None
    monkeypatch.setenv("UNDERSTAT_AUTORISATION_ECRITE", "e-mail Understat 2026-11-20 objet: autorisation")
    assert u.autorisation_ecrite()
