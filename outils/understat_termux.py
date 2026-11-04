#!/usr/bin/env python3
"""[VERROUILLÉ — voir autorisation_ecrite()] Collecte Understat pour Termux — Python standard UNIQUEMENT (aucun pip), base SQLite locale, provenance sur chaque ligne.
Usage :
  python understat_termux.py maj [saison]   # ligues + matchs terminés + tirs des matchs pas encore en base (max 15 pages/passage)
  python understat_termux.py etat           # ce qu'il y a en base
Courtoisie : 1 requête toutes les 4 s, cache des pages, jamais deux fois le même match, plafond par passage, User-Agent déclaré.
La base reste locale (understat.db) : rien n'est envoyé ailleurs. Les valeurs absentes restent NULL (jamais estimées)."""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://understat.com"
LIGUES = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1"]
DELAI_S = 4
MAX_PAGES_MATCH = 15
UA = "analyse-football-perso/1.0 (usage personnel, faible volume)"
DB = os.environ.get("UNDERSTAT_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "understat.db"))


def saison_courante(now=None):
    n = now or datetime.now()
    return n.year if n.month >= 7 else n.year - 1


def telecharger(url):
    time.sleep(DELAI_S)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def extraire(html, nom):
    """Understat embarque ses données dans `var nom = JSON.parse('...')` (échappements \\xNN) -> objet Python ou None."""
    m = re.search(r"var\s+" + re.escape(nom) + r"\s*=\s*JSON\.parse\('(.*?)'\)", html, re.S)
    if not m:
        return None
    brut = m.group(1).encode("utf-8").decode("unicode_escape")
    return json.loads(brut)


def init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS us_matchs(match_id TEXT PRIMARY KEY, ligue TEXT, saison INT, date TEXT, termine INT,
      dom_id TEXT, dom TEXT, ext_id TEXT, ext TEXT, buts_dom INT, buts_ext INT, xg_dom REAL, xg_ext REAL,
      p_dom REAL, p_nul REAL, p_ext REAL, source TEXT, url TEXT, collecte_le TEXT, hash_brut TEXT);
    CREATE TABLE IF NOT EXISTS us_tirs(tir_id TEXT PRIMARY KEY, match_id TEXT, minute INT, xg REAL, x REAL, y REAL,
      resultat TEXT, situation TEXT, type_tir TEXT, joueur TEXT, joueur_id TEXT, cote TEXT, passeur TEXT,
      source TEXT, url TEXT, collecte_le TEXT, hash_brut TEXT);
    CREATE TABLE IF NOT EXISTS us_equipes_saison(ligue TEXT, saison INT, equipe_id TEXT, equipe TEXT, matchs INT, victoires INT,
      nuls INT, defaites INT, buts INT, buts_enc INT, xg REAL, xga REAL, npxg REAL, npxga REAL, ppda REAL,
      source TEXT, url TEXT, collecte_le TEXT, hash_brut TEXT, PRIMARY KEY(ligue, saison, equipe_id));
    """)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def stocker_ligue(con, ligue, saison, html, url):
    h, maintenant = hashlib.sha256(html.encode()).hexdigest(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    dates, equipes = extraire(html, "datesData") or [], extraire(html, "teamsData") or {}
    for m in dates:
        buts, xg, fc = m.get("goals") or {}, m.get("xG") or {}, m.get("forecast") or {}
        con.execute("INSERT OR REPLACE INTO us_matchs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            str(m["id"]), ligue, saison, m.get("datetime"), 1 if m.get("isResult") else 0,
            (m.get("h") or {}).get("id"), (m.get("h") or {}).get("title"), (m.get("a") or {}).get("id"),
            (m.get("a") or {}).get("title"), _i(buts.get("h")), _i(buts.get("a")), _f(xg.get("h")), _f(xg.get("a")),
            _f(fc.get("w")), _f(fc.get("d")), _f(fc.get("l")), "understat.com", url, maintenant, h))
    for eid, t in equipes.items():
        hist = t.get("history") or []
        if not hist:
            continue
        s = lambda k: sum(_f(x.get(k)) or 0 for x in hist)
        ppda = [(_f((x.get("ppda") or {}).get("att")), _f((x.get("ppda") or {}).get("def"))) for x in hist]
        att, dff = sum(a or 0 for a, _ in ppda), sum(d or 0 for _, d in ppda)
        con.execute("INSERT OR REPLACE INTO us_equipes_saison VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            ligue, saison, str(eid), t.get("title"), len(hist), sum(1 for x in hist if x.get("result") == "w"),
            sum(1 for x in hist if x.get("result") == "d"), sum(1 for x in hist if x.get("result") == "l"),
            int(s("scored")), int(s("missed")), s("xG"), s("xGA"), s("npxG"), s("npxGA"),
            (att / dff) if dff else None, "understat.com", url, maintenant, h))
    con.commit()
    return len(dates)


def stocker_tirs(con, match_id, html, url):
    h, maintenant = hashlib.sha256(html.encode()).hexdigest(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    donnees = extraire(html, "shotsData") or {}
    n = 0
    for cote in ("h", "a"):
        for t in donnees.get(cote, []):
            con.execute("INSERT OR REPLACE INTO us_tirs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                str(t.get("id")), match_id, _i(t.get("minute")), _f(t.get("xG")), _f(t.get("X")), _f(t.get("Y")),
                t.get("result"), t.get("situation"), t.get("shotType"), t.get("player"), t.get("player_id"),
                t.get("h_a"), t.get("player_assisted"), "understat.com", url, maintenant, h))
            n += 1
    con.commit()
    return n


def maj(saison=None):
    saison = saison or saison_courante()
    con = sqlite3.connect(DB)
    init(con)
    for ligue in LIGUES:
        url = f"{BASE}/league/{ligue}/{saison}"
        try:
            n = stocker_ligue(con, ligue, saison, telecharger(url), url)
            print(f"[{ligue} {saison}] {n} matchs listés")
        except Exception as e:  # noqa: BLE001 — une ligue en échec ne doit pas bloquer les autres
            print(f"[{ligue}] ECHEC : {e}")
    a_faire = [r[0] for r in con.execute(
        "SELECT match_id FROM us_matchs WHERE termine=1 AND saison=? AND match_id NOT IN (SELECT DISTINCT match_id FROM us_tirs) "
        "ORDER BY date DESC LIMIT ?", (saison, MAX_PAGES_MATCH))]
    for mid in a_faire:
        url = f"{BASE}/match/{mid}"
        try:
            print(f"[match {mid}] {stocker_tirs(con, mid, telecharger(url), url)} tirs")
        except Exception as e:  # noqa: BLE001
            print(f"[match {mid}] ECHEC : {e}")
    etat(con)


def etat(con=None):
    con = con or sqlite3.connect(DB)
    init(con)
    for ligue, saison, n, t in con.execute("SELECT ligue, saison, count(*), sum(termine) FROM us_matchs GROUP BY 1,2 ORDER BY 2,1"):
        print(f"{ligue} {saison}: {n} matchs ({t} terminés)")
    print("tirs en base :", con.execute("SELECT count(*) FROM us_tirs").fetchone()[0],
          "| matchs terminés sans tirs :", con.execute(
              "SELECT count(*) FROM us_matchs WHERE termine=1 AND match_id NOT IN (SELECT DISTINCT match_id FROM us_tirs)").fetchone()[0])


def autorisation_ecrite():
    """VERROU (décision du 2026-11-04) : aucune collecte tant que la référence d'une confirmation écrite d'Understat n'est pas
    fournie dans UNDERSTAT_AUTORISATION_ECRITE (ex. date + objet de l'e-mail). L'e-mail informel de 2018 ne compte pas."""
    ref = (os.environ.get("UNDERSTAT_AUTORISATION_ECRITE") or "").strip()
    return ref if len(ref) >= 10 else None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "etat"
    if cmd == "maj":
        if not autorisation_ecrite():
            print("REFUS : collecte Understat désactivée tant qu'aucune confirmation écrite des conditions/droits n'est obtenue "
                  "(variable UNDERSTAT_AUTORISATION_ECRITE vide). Rien n'a été téléchargé.")
            sys.exit(2)
        maj(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    else:
        etat()
