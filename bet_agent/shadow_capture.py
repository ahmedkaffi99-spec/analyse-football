"""Phase SHADOW OddsPapi vs API-Football, 5 grands championnats (demande explicite du
09/10/2026, suite au test manuel à 3 matchs — écarts 5-25%, fraîcheur non mesurée).

RÈGLES ABSOLUES (reprises de la demande) :
- Ne supprime pas OddsPapi, ne remplace aucune source de production.
- AUCUNE fonction de ce fichier n'est importée par un module de production
  (collecte_donnees.py, analyser_et_envoyer.py, runs.py...) — ce module ne peut donc jamais,
  même indirectement, changer la sélection ou le coupon Telegram.
- Importer ce fichier ne déclenche AUCUN appel réseau : seules les fonctions capturer_*
  en font, et seulement quand on les appelle explicitement.
- Normalisation STRICTE : seule une correspondance EXPLICITE (MAPPING_API_FOOTBALL,
  CATEGORIES_ODDSPAPI) associe un marché/une sélection brute à une catégorie canonique —
  jamais un rapprochement par ressemblance de nom. Un marché non reconnu reste "non_mappe",
  jamais deviné.

Bookmaker : 1xBet uniquement, des deux côtés (OddsPapi filtré sur "1xbet" — voir
collecte_donnees.recuperer_marches_pour_fixture ; API-Football filtré sur le bookmaker
id=11 "1xBet", confirmé par le test réel du 09/10/2026, voir diagnostic_odds_api_football.py)."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
import os

load_dotenv("envi.local")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_BOOKMAKER_1XBET = 11  # confirmé par appel réel le 09/10/2026, jamais supposé

# 5 grands championnats européens (mêmes identifiants qu'ailleurs dans le projet, voir
# collecte_donnees.LIGUES_MAJEURES et lister_matchs_periode.py).
CINQ_GRANDS_CHAMPIONNATS = {
    39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1",
}


def maintenant_utc():
    return datetime.now(timezone.utc)


# ============================================================
# IDENTITÉS CANONIQUES DE MARCHÉ — jamais devinées par ressemblance de nom.
# ============================================================

CATEGORIES_ODDSPAPI = {
    "Full Time Result": "1X2",
    "Double Chance Full Time": "DOUBLE_CHANCE",
    "Asian Handicap": "HANDICAP_ASIATIQUE",
    "European Handicap": "HANDICAP_EUROPEEN",
    "Over Under Full Time": "BUTS_TOTAL",
    "Over Under Team 1": "BUTS_EQUIPE_DOM",
    "Over Under Team 2": "BUTS_EQUIPE_EXT",
    "Both Teams To Score": "BTTS",
    "Corners - Over Under Full Time": "CORNERS_TOTAL",
    "Yellow Cards - Over Under Full Time": "CARTONS_TOTAL",
    "Shots - Over Under Full Time": "TIRS_TOTAL",
}

# nom de pari API-Football EXACT (voir le test réel du 09/10/2026) -> catégorie canonique.
# Pas d'entrée pour HANDICAP_EUROPEEN : confirmé par le test réel du 09/10/2026 (3 matchs)
# qu'API-Football n'expose AUCUN pari de handicap à 3 voies pour 1xBet — volontairement
# laissé sans correspondance, jamais assimilé à l'Asian Handicap (demande explicite du
# 10/10/2026 : "ne pas considérer l'Asian Handicap comme équivalent à l'European Handicap").
MAPPING_API_FOOTBALL = {
    "Match Winner": "1X2",
    "Double Chance": "DOUBLE_CHANCE",
    "Asian Handicap": "HANDICAP_ASIATIQUE",
    "Goals Over/Under": "BUTS_TOTAL",
    "Total - Home": "BUTS_EQUIPE_DOM",
    "Total - Away": "BUTS_EQUIPE_EXT",
    "Both Teams Score": "BTTS",
    "Corners Over Under": "CORNERS_TOTAL",
    "Yellow Over/Under": "CARTONS_TOTAL",
    "Total Shots": "TIRS_TOTAL",
}

_RE_LIGNE = re.compile(r"([+-]?\d+(?:\.\d+)?)")


def _normaliser_selection_api_football(categorie, valeur_brute):
    """(selection_canonique, ligne) ou (None, None) si non reconnu — jamais deviné."""
    if categorie == "1X2":
        return {"Home": "1", "Draw": "X", "Away": "2"}.get(valeur_brute), None
    if categorie == "DOUBLE_CHANCE":
        return {"Home/Draw": "1X", "Home/Away": "12", "Draw/Away": "2X"}.get(valeur_brute), None
    if categorie == "HANDICAP_ASIATIQUE":
        m = re.match(r"^(Home|Away)\s+([+-]?\d+(?:\.\d+)?)$", valeur_brute)
        if not m:
            return None, None
        return ("1" if m.group(1) == "Home" else "2"), float(m.group(2))
    if categorie in ("BUTS_TOTAL", "BUTS_EQUIPE_DOM", "BUTS_EQUIPE_EXT", "CORNERS_TOTAL",
                     "CARTONS_TOTAL", "TIRS_TOTAL"):
        m = re.match(r"^(Over|Under)\s+(\d+(?:\.\d+)?)$", valeur_brute)
        if not m:
            return None, None
        return m.group(1), float(m.group(2))
    if categorie == "BTTS":
        return ({"Yes": "Yes", "No": "No"}).get(valeur_brute), None
    return None, None


# ============================================================
# STRUCTURES DE CAPTURE — un enregistrement par (fournisseur, match, marché, sélection).
# ============================================================

@dataclass
class Cotation:
    fixture_id_oddspapi: str | None
    fixture_id_api_football: int | None
    championnat: str
    domicile: str
    exterieur: str
    bookmaker: str
    fournisseur: str            # "oddspapi" | "api_football"
    recu_le_utc: datetime        # mesuré par ce code, jamais fourni par le fournisseur
    maj_api_utc: str | None      # horodatage de mise à jour donné par l'API, si fourni (brut)
    marche: str                  # catégorie CANONIQUE (ou "non_mappe")
    marche_brut: str             # nom exact tel que renvoyé par le fournisseur — jamais perdu
    selection: str
    ligne: float | None
    cote: float
    marche_id: str | None = None


@dataclass
class RequeteShadow:
    fournisseur: str
    fixture_id: object
    statut_http: int | None
    erreur: str | None
    nb_marches_recus: int
    recu_le_utc: datetime = field(default_factory=maintenant_utc)


# ============================================================
# CAPTURE API-FOOTBALL (1 appel /odds par match) — RÉSEAU, jamais appelé implicitement.
# ============================================================

def capturer_api_football(fixture_id_api_football, championnat, domicile, exterieur):
    """1 appel réel GET /odds?fixture=&bookmaker=11. Renvoie (requete: RequeteShadow,
    cotations: [Cotation]). Un marché/valeur non reconnu par MAPPING_API_FOOTBALL est
    IGNORÉ (jamais inventé) — compté séparément si besoin via nb_marches_recus (brut) vs
    len(cotations) (mappées)."""
    recu_le = maintenant_utc()
    try:
        r = requests.get(f"{API_FOOTBALL_BASE}/odds",
                         headers={"x-apisports-key": API_FOOTBALL_KEY or ""},
                         params={"fixture": fixture_id_api_football, "bookmaker": API_FOOTBALL_BOOKMAKER_1XBET},
                         timeout=20)
    except Exception as e:
        return RequeteShadow("api_football", fixture_id_api_football, None, str(e), 0, recu_le), []

    try:
        data = r.json()
    except ValueError:
        return RequeteShadow("api_football", fixture_id_api_football, r.status_code, "réponse non-JSON", 0, recu_le), []

    if data.get("errors"):
        return RequeteShadow("api_football", fixture_id_api_football, r.status_code, str(data["errors"]), 0, recu_le), []

    reponses = data.get("response", [])
    if not reponses:
        return RequeteShadow("api_football", fixture_id_api_football, r.status_code, "réponse vide", 0, recu_le), []

    cotations = []
    nb_marches_brut = 0
    for rep in reponses:
        maj_api = rep.get("update")
        bookmaker_1xbet = next((bm for bm in rep.get("bookmakers", [])
                                if bm.get("id") == API_FOOTBALL_BOOKMAKER_1XBET), None)
        if not bookmaker_1xbet:
            continue
        for bet in bookmaker_1xbet.get("bets", []):
            nb_marches_brut += 1
            nom_pari = bet.get("name")
            categorie = MAPPING_API_FOOTBALL.get(nom_pari, "non_mappe")
            for v in bet.get("values", []):
                valeur_brute, cote_brute = v.get("value"), v.get("odd")
                if categorie == "non_mappe":
                    continue  # jamais deviné — ignoré, pas inventé
                selection, ligne = _normaliser_selection_api_football(categorie, valeur_brute)
                if selection is None:
                    continue
                try:
                    cote = float(cote_brute)
                except (TypeError, ValueError):
                    continue
                cotations.append(Cotation(
                    fixture_id_oddspapi=None, fixture_id_api_football=fixture_id_api_football,
                    championnat=championnat, domicile=domicile, exterieur=exterieur,
                    bookmaker="1xBet", fournisseur="api_football", recu_le_utc=recu_le,
                    maj_api_utc=maj_api, marche=categorie, marche_brut=nom_pari,
                    selection=selection, ligne=ligne, cote=cote, marche_id=str(bet.get("id"))))

    requete = RequeteShadow("api_football", fixture_id_api_football, r.status_code, None, nb_marches_brut, recu_le)
    return requete, cotations


# ============================================================
# CAPTURE ODDSPAPI — réutilise collecte_donnees.recuperer_marches_pour_fixture (même
# fonction que la production, pour ne jamais dupliquer la logique d'appel/retry/quota) ;
# NE L'IMPORTE PAS EN HAUT DU FICHIER pour que le simple import de shadow_capture.py ne
# tire jamais le module de production tant que cette fonction n'est pas appelée.
# ============================================================

def capturer_oddspapi(fixture_id_oddspapi, championnat, domicile, exterieur):
    """1 appel réel (via collecte_donnees.recuperer_marches_pour_fixture, même code que la
    production) — jamais de duplication de la logique d'appel/retry/quota OddsPapi. ATTENTION :
    cette fonction RETENTE jusqu'à 5 fois en cas d'erreur réseau générique (même @retry que la
    production, voir cd._telecharger_odds_oddspapi) — à éviter pour un test à budget de
    requêtes strict (voir capturer_oddspapi_sans_retry ci-dessous)."""
    import collecte_donnees as cd

    recu_le = maintenant_utc()
    try:
        tous_marches = cd.recuperer_marches_pour_fixture(fixture_id_oddspapi)
    except Exception as e:
        return RequeteShadow("oddspapi", fixture_id_oddspapi, None, str(e), 0, recu_le), []

    if not tous_marches:
        return RequeteShadow("oddspapi", fixture_id_oddspapi, None, "aucun marché 1xbet", 0, recu_le), []

    cotations = []
    for m in tous_marches:
        categorie = CATEGORIES_ODDSPAPI.get(m["marche"], "non_mappe")
        if categorie == "non_mappe":
            continue
        for s in m["selections"]:
            cotations.append(Cotation(
                fixture_id_oddspapi=fixture_id_oddspapi, fixture_id_api_football=None,
                championnat=championnat, domicile=domicile, exterieur=exterieur,
                bookmaker="1xBet", fournisseur="oddspapi", recu_le_utc=recu_le, maj_api_utc=None,
                marche=categorie, marche_brut=m["marche"], selection=s["selection"],
                ligne=m.get("handicap"), cote=float(s["cote"]), marche_id=str(m.get("marche_id"))))

    requete = RequeteShadow("oddspapi", fixture_id_oddspapi, 200, None, len(tous_marches), recu_le)
    return requete, cotations


def capturer_oddspapi_sans_retry(fixture_id_oddspapi, championnat, domicile, exterieur):
    """Comme capturer_oddspapi, mais EXACTEMENT 1 tentative HTTP (aucun retry tenacity) —
    demande explicite du 10/10/2026 : budget de requêtes strict, jamais dépassé même en cas
    d'erreur HTTP 429. Duplique volontairement le parsing minimal de
    cd.recuperer_marches_pour_fixture (qui passe par cd._telecharger_odds_oddspapi, décorée
    @retry(5 tentatives) — incompatible avec un budget strict) ; réutilise cd.get_market_names()
    tel quel (déjà une seule tentative, pas de @retry, mis en cache après le premier appel —
    c'est le "1x /v4/markets" du budget annoncé)."""
    import collecte_donnees as cd

    recu_le = maintenant_utc()
    try:
        r = cd.SESSION_ODDSPAPI.get(
            "https://api.oddspapi.io/v4/odds",
            params={"apiKey": cd.ODDSPAPI_KEY, "fixtureId": fixture_id_oddspapi,
                   "bookmakers": "1xbet", "oddsFormat": "decimal"},
            timeout=(5, 20), verify=cd.VERIFIER_SSL_ODDSPAPI)
    except Exception as e:
        return RequeteShadow("oddspapi", fixture_id_oddspapi, None, str(e), 0, recu_le), []

    if r.status_code != 200:
        return RequeteShadow("oddspapi", fixture_id_oddspapi, r.status_code, r.text[:200], 0, recu_le), []

    try:
        data = r.json()
    except ValueError:
        return RequeteShadow("oddspapi", fixture_id_oddspapi, r.status_code, "réponse non-JSON", 0, recu_le), []

    noms_marches = cd.get_market_names()  # 1 appel réel la 1re fois seulement, puis en cache
    cotations, nb_marches_brut = [], 0
    for event in (data if isinstance(data, list) else [data]):
        markets = (event.get("bookmakerOdds") or {}).get("1xbet", {}).get("markets", {})
        nb_marches_brut += len(markets)
        for market_id, market_data in markets.items():
            info = noms_marches.get(str(market_id), {})
            nom_marche_brut = info.get("name", f"Marché {market_id}")
            categorie = CATEGORIES_ODDSPAPI.get(nom_marche_brut, "non_mappe")
            if categorie == "non_mappe":
                continue
            handicap = info.get("handicap")
            outcomes_noms = info.get("outcomes", {})
            for outcome_id, outcome_data in (market_data.get("outcomes") or {}).items():
                prix = (outcome_data.get("players") or {}).get("0", {}).get("price")
                if not prix:
                    continue
                selection = outcomes_noms.get(str(outcome_id), f"Option {outcome_id}")
                cotations.append(Cotation(
                    fixture_id_oddspapi=fixture_id_oddspapi, fixture_id_api_football=None,
                    championnat=championnat, domicile=domicile, exterieur=exterieur,
                    bookmaker="1xBet", fournisseur="oddspapi", recu_le_utc=recu_le, maj_api_utc=None,
                    marche=categorie, marche_brut=nom_marche_brut, selection=selection,
                    ligne=handicap, cote=float(prix), marche_id=str(market_id)))

    requete = RequeteShadow("oddspapi", fixture_id_oddspapi, r.status_code, None, nb_marches_brut, recu_le)
    return requete, cotations
