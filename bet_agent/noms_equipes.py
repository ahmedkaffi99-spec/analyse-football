"""Normalisation et rapprochement des noms d'équipes entre sources (API-Football / OddsPapi / Football-Data). Rapprochement TRACÉ, jamais silencieux."""
import re

ALIAS = {"manchester united": "man united", "manchester city": "man city", "paris saint germain": "paris sg",
         "borussia monchengladbach": "m'gladbach", "atletico madrid": "ath madrid", "athletic club": "ath bilbao",
         "real betis": "betis", "real sociedad": "sociedad", "ac milan": "milan", "hellas verona": "verona",
         "borussia dortmund": "dortmund", "bayer leverkusen": "leverkusen", "eintracht frankfurt": "ein frankfurt",
         "newcastle united": "newcastle", "wolverhampton wanderers": "wolves", "tottenham hotspur": "tottenham",
         "west ham united": "west ham", "nottingham forest": "nott'm forest", "leeds united": "leeds",
         "brighton hove albion": "brighton", "olympique marseille": "marseille", "olympique lyonnais": "lyon",
         "stade rennais": "rennes", "as monaco": "monaco", "1 fc union berlin": "union berlin", "fsv mainz 05": "mainz",
         "vfl wolfsburg": "wolfsburg", "bayern munchen": "bayern munich", "fc koln": "fc koln",
         "1 fc heidenheim": "heidenheim", "sc freiburg": "freiburg", "tsg hoffenheim": "hoffenheim",
         "celta vigo": "celta", "rayo vallecano": "vallecano", "deportivo alaves": "alaves", "espanyol": "espanol"}


def norm(nom):
    from unidecode import unidecode
    n = re.sub(r"[^a-z0-9' ]", " ", unidecode(nom or "").lower())
    n = re.sub(r"\b(fc|afc|cf|sc|ssc|ac|as)\b", " ", n) if n.strip() not in ("ac milan", "as monaco") else n
    n = re.sub(r"\s+", " ", n).strip()
    return ALIAS.get(n, n)


def score_noms(a, b):
    from rapidfuzz import fuzz
    return fuzz.token_set_ratio(norm(a), norm(b))
