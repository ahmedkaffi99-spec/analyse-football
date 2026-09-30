import os
import json
import time
import csv
import io
import requests
import urllib3
from collections import deque
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# OddsPapi est intercepté par un boîtier réseau (Fortinet) qui re-signe son certificat
# avec une autorité non reconnue par notre magasin de confiance (constaté le 2026-07-25 —
# le certificat leaf est signé par 'O=Fortinet, OU=Certificate Authority', pas par une CA
# publique). Le reste de l'appareil (navigateur, autres apps) fait déjà confiance à cette
# interception ; on désactive donc la vérification UNIQUEMENT pour ce domaine précis (déjà
# intercepté de toute façon, donc aucune exposition supplémentaire), jamais pour les autres
# APIs (Telegram, Groq, API-Football, Serper — toutes vérifiées normalement, non affectées).
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from unidecode import unidecode
from tenacity import retry, stop_after_attempt, wait_fixed, wait_exponential

load_dotenv("envi.local")

# Vérification du certificat OddsPapi : ACTIVE par défaut (GitHub Actions, serveur, PC).
# ODDSPAPI_SSL_NON_VERIFIE=true seulement sur un réseau qui intercepte le certificat (boîtier
# Fortinet constaté sur l'ancien environnement Termux) — jamais pour les autres APIs.
VERIFIER_SSL_ODDSPAPI = os.getenv("ODDSPAPI_SSL_NON_VERIFIE", "").lower() not in ("1", "true", "oui")
if not VERIFIER_SSL_ODDSPAPI:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------
# SESSION PARTAGÉE avec retry automatique au niveau connexion (pas au niveau
# logique métier, qui garde ses propres @retry tenacity par-dessus). Absorbe les
# coupures/lenteurs réseau ponctuelles (timeout, connexion refusée, 429/502/503/
# 504) sans qu'on ait à réécrire une boucle de tentative à la main à chaque appel.
# Ajouté suite au constat du 2026-08-22 : ClubElo et TheSportsDB échouaient
# entièrement (0/30 équipes) alors qu'un simple test isolé passait — signe d'une
# instabilité réseau que 3 tentatives espacées de 3s n'absorbaient pas toujours.
# Ceci ne change rien pour API-Football (dont le 403 "quota journalier dépassé"
# n'est pas un problème réseau — aucun retry ne peut réparer un quota épuisé).
# ------------------------------------------------------------
_retry_reseau = Retry(
    total=4,
    backoff_factor=1.5,  # pauses ~1.5s, 3s, 6s, 12s entre les tentatives
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=_retry_reseau))
SESSION.mount("http://", HTTPAdapter(max_retries=_retry_reseau))

# Plan gratuit API-Football : 10 requêtes/minute (confirmé via /status le 2026-07-23).
# Avec jusqu'à 30 équipes (NB_MATCHS_MAX=15 matchs, 2 appels /leagues + /teams/statistics
# chacune) plus les 3 appels fixtures, une collecte complète dépasse largement ce quota si
# les appels partent sans pause — d'où les échecs "Aucune compétition trouvée après retries"
# observés en fin de run (le rate limit vide la réponse, ce qui ressemble à tort à une
# absence de données). Le rate limiter ci-dessous absorbe ça par des pauses, pas un échec.
API_FOOTBALL_QUOTA_PAR_MINUTE = 9  # marge de sécurité sous les 10/min réels
_horodatages_appels_api_football = deque()


def _respecter_rate_limit_api_football():
    maintenant = time.monotonic()
    while _horodatages_appels_api_football and maintenant - _horodatages_appels_api_football[0] > 60:
        _horodatages_appels_api_football.popleft()
    if len(_horodatages_appels_api_football) >= API_FOOTBALL_QUOTA_PAR_MINUTE:
        attente = 60 - (maintenant - _horodatages_appels_api_football[0]) + 0.5
        if attente > 0:
            time.sleep(attente)
    _horodatages_appels_api_football.append(time.monotonic())

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# ------------------------------------------------------------
# SÉLECTION MANUELLE — active ce mode si tu as déjà vérifié toi-même quels matchs
# ont des marchés ouverts sur 1xbet (évite de perdre des matchs sans marché après
# coup, comme observé le 22/08 : Premier League sélectionnée automatiquement mais
# 0 marché disponible sur 4 matchs sur 4). Quand SELECTION_MANUELLE_ACTIVE=True,
# la sélection automatique (selectionner_matchs_du_jour) est COMPLÈTEMENT
# ignorée — seule la liste MATCHS_MANUELS ci-dessous est utilisée, telle quelle.
# Remets False pour revenir à la sélection automatique par ligue.
#
# MATCHS_MANUELS_DATE = le jour (AAAA-MM-JJ) pour lequel la liste a été vérifiée. Un autre
# jour, la liste est périmée (constaté : le mode manuel resté actif aurait recherché les
# matchs du 22/08 un mois plus tard) — elle est alors ignorée au profit de la sélection
# automatique. Mets à jour la date EN MÊME TEMPS que la liste.
# ------------------------------------------------------------
SELECTION_MANUELLE_ACTIVE = True
MATCHS_MANUELS_DATE = "2026-10-13"

# Si SELECTION_MANUELLE_ACTIVE=True : la liste EXACTE de matchs à collecter, dans
# l'ordre. Si False : sert uniquement de filet de sécurité si la sélection
# automatique ne trouve rien du tout parmi les grandes ligues aujourd'hui.
# Noms d'équipes : peu importe l'orthographe exacte (fuzzy matching), mais reste
# proche du nom usuel pour un bon score de correspondance.
#
# Demande explicite du 29/09/2026 : matchs de Ligue des Champions choisis par l'utilisateur
# à partir de captures d'écran 1xBet, 13-14 octobre 2026 (12 matchs, doublons retirés).
# Limité à 10 le 30/09/2026 sur demande explicite ("entre 5 et 10 pas plus") — les 2 moins
# prioritaires (Bodo/Glimt-Dortmund, Villarreal-Napoli) retirés.
MATCHS_MANUELS = [
    ("Aston Villa", "Fenerbahce"),
    ("Roma", "Real Madrid"),
    ("Real Betis", "Porto"),
    ("Manchester City", "Paris Saint-Germain"),
    ("LASK Linz", "Liverpool"),
    ("Inter Milano", "Club Brugge"),
    ("Galatasaray", "Barcelona"),
    ("Viking", "Bayern Munich"),
    ("Atletico Madrid", "Manchester United"),
    ("Arsenal", "Lille OSC"),
]

# Grandes ligues européennes uniquement — MLS et Brasileirão volontairement exclus
# (leçon du développement initial, voir MEMOIRE.md : matching moins fiable, moins de
# marchés 1xbet dispo sur ces championnats). Ordre = ordre de priorité pour le tri.
LIGUES_MAJEURES = [
    2,    # UEFA Champions League
    3,    # UEFA Europa League
    39,   # Premier League (Angleterre)
    140,  # La Liga (Espagne)
    135,  # Serie A (Italie)
    78,   # Bundesliga (Allemagne)
    61,   # Ligue 1 (France)
    88,   # Eredivisie (Pays-Bas)
    94,   # Primeira Liga (Portugal)
]

# Même esprit que LIGUES_MAJEURES mais côté OddsPapi (tournamentName/categoryName) —
# nécessaire car OddsPapi a son propre système d'ID de tournoi, différent des league_id
# d'API-Football. Sert à prioriser, pas à exclure : le reste des matchs avec cotes réelles
# complète la sélection si pas assez de grandes compétitions ce jour-là (creux estival).
#
# IMPORTANT : un simple mot-clé sur le nom du tournoi ("premier league", "la liga"...) donne
# de FAUX POSITIFS — plein de pays ont une ligue locale nommée pareil (ex: Liban a sa propre
# "Premier League", constaté en pratique). D'où la vérification du PAYS (categoryName) en
# plus du nom, sauf pour les compétitions européennes dont le nom est sans ambiguïté.
COMPETITIONS_EUROPEENNES_UNIQUES = ("champions league", "europa league", "conference league")

LIGUES_DOMESTIQUES_MAJEURES = {
    "england": ("premier league",),
    "spain": ("la liga",),
    "italy": ("serie a",),
    "germany": ("bundesliga",),
    "france": ("ligue 1",),
    "netherlands": ("eredivisie",),
    "portugal": ("primeira liga", "liga portugal"),
}

# ------------------------------------------------------------
# FILTRE MULTI-LIGUES — ne collecte QUE les compétitions listées ici aujourd'hui
# (paire mot-clé tournoi + pays, sur le même principe que LIGUES_DOMESTIQUES_MAJEURES
# ci-dessus, pour éviter les faux positifs d'un autre pays ayant une ligue au même nom).
# Laisse la liste vide ([]) pour revenir au comportement normal (toutes les grandes
# ligues + repli sur le reste des matchs avec cotes réelles).
# ------------------------------------------------------------
FILTRE_LIGUES_UNIQUES = [
    ("ligue 1", "france"),
    ("premier league", "england"),
    ("serie a", "italy"),
    ("bundesliga", "germany"),
    ("la liga", "spain"),
]

# Compétitions de SECOURS, utilisées seulement quand FILTRE_LIGUES_UNIQUES donne moins de
# NB_MATCHS_MIN matchs — typiquement pendant une trêve internationale, où les 5 grands
# championnats s'arrêtent (constaté le 2026-09-26 : 6 matchs seulement, tous de Serie A
# féminine). Même format (mot-clé du tournoi, pays ou None).
FILTRE_LIGUES_SECOURS = [
    ("nations league", None),
    ("champions league", None),
    ("europa league", None),
    ("conference league", None),
    ("world cup", None),
    ("africa cup of nations", None),
    ("eredivisie", "netherlands"),
    ("primeira liga", "portugal"),
    ("liga portugal", "portugal"),
    ("championship", "england"),
    ("ligue 2", "france"),
    ("serie b", "italy"),
    ("2. bundesliga", "germany"),
    ("segunda division", "spain"),   # 2e division seulement ("segunda" seul attrapait la 4e
    ("laliga 2", "spain"),           #  division, Segunda Federación — constaté le 2026-09-26)
    ("la liga 2", "spain"),
    ("super lig", "turkey"),
    ("pro league", "belgium"),
    ("premiership", "scotland"),
    ("botola", "morocco"),
]

# Football féminin : exclu de la sélection automatique (les filtres visent les championnats
# masculins ; "Serie A" laissait passer la Serie A féminine, dont les stats gratuites datent
# de 2022-2024). Détecté sur le nom du tournoi/pays, et sur les noms d'équipes API-Football
# ("Juventus W") au moment de la collecte.
MARQUEURS_FEMININ = ("women", "woman", "femin", "frauen", "femenin", "wsl", "liga f", "damallsvenskan")


def est_competition_feminine(*textes):
    texte = " ".join(unidecode(t or "").lower() for t in textes)
    return any(marqueur in texte for marqueur in MARQUEURS_FEMININ)


def est_equipe_feminine_api_football(nom):
    return unidecode(nom or "").strip().lower().endswith(" w")


NB_MATCHS_MIN = 8   # objectif minimum de jambes pour un coupon jugé complet
NB_MATCHS_MAX = 15  # plafond de matchs AVEC marchés — au-delà, la collecte devient trop lente/coûteuse en quota
# Nombre de candidats sondés : les cotes sont vérifiées EN PREMIER, un match sans marché 1xbet
# est écarté sans aucun autre appel (stats, Elo, presse). On sonde donc plus large que
# NB_MATCHS_MAX et on s'arrête dès que NB_MATCHS_MAX matchs exploitables sont trouvés
# (constaté le 2026-09-26 : 13 matchs sur 15 sans marché avaient consommé tout le quota).
NB_CANDIDATS_A_SONDER = 30
# Délai minimal avant le coup d'envoi : laisser le temps de lire le coupon et de parier.
MINUTES_MIN_AVANT_COUP_ENVOI = 45

SEUIL_MATCH_ACCEPTABLE = 80  # relevé de 60 à 80 après un faux positif (équipes réserve "II" matchées à tort)

# Un candidat contenant un de ces marqueurs, alors que la demande n'en contient aucun,
# est rejeté même si son score dépasse le seuil — évite de confondre l'équipe pro
# avec sa réserve/ses jeunes (ex: "New York City II" au lieu de "New York City FC").
INDICATEURS_EQUIPE_RESERVE = (" ii", " iii", " u18", " u19", " u20", " u21", " u23", " reserve", " reserves", " b team", " youth",
                              # Matchs VIRTUELS (Simulated Reality League, e-sport) : aucun marché 1xbet
                              # réel, et "England SRL vs Spain SRL" était apparié au vrai match
                              # (constaté le 2026-09-26 : 13 matchs sur 15 sans aucune cote)
                              " srl", " esports", " e-sports", " cyber", " virtual")


def contient_indicateur_reserve(nom):
    nom_normalise = f" {unidecode(nom).lower()} "
    return any(indicateur in nom_normalise for indicateur in INDICATEURS_EQUIPE_RESERVE)


def score_paire_equipes(home_cherche, away_cherche, home_candidat, away_candidat):
    """Score de correspondance d'un match = le PLUS FAIBLE des deux scores équipe par équipe.
    Comparer "home away" en une seule chaîne laissait une seule équipe commune suffire à
    dépasser le seuil (constaté : "SL Benfica vs CF Os Belenenses" apparié à 80% avec
    "Estrela vs CF Os Belenenses", "Malmo FF vs Hammarby IF" à 82% avec "IF Brommapojkarna
    vs Hammarby FF") — les stats de la mauvaise équipe étaient alors utilisées."""
    from rapidfuzz import fuzz

    def score(a, b):
        return fuzz.token_set_ratio(unidecode(a or "").lower(), unidecode(b or "").lower())

    return min(score(home_cherche, home_candidat), score(away_cherche, away_candidat))
SORTIE_JSON = "donnees_collectees.json"

MARKET_NAMES_CACHE = {}


# ============================================================
# API-FOOTBALL — 1 seul appel pour situer les 8 matchs
# ============================================================

MAX_TENTATIVES_SAISON = 3  # plafonne les appels /teams/statistics par équipe (quota API-Football limité)

# Le plan gratuit API-Football rejette catégoriquement /teams/statistics pour les saisons
# hors de cette fenêtre (constaté le 2026-07-23 : erreur "Free plans do not have access to
# this season, try from 2022 to 2024" sur 2025 ET 2026). Sans ce filtre, les 2 premières
# tentatives de chaque équipe (saisons 2026/2025) sont systématiquement perdues avant
# d'atteindre 2024 qui, lui, répond — ce qui épuise le quota par minute avant la fin de la
# collecte (constaté : 9/16 équipes seulement, échecs concentrés en fin de liste de matchs).
SAISON_MAX_PLAN_GRATUIT = 2024


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def _appel_leagues_api_football(team_id):
    _respecter_rate_limit_api_football()
    r = SESSION.get("https://v3.football.api-sports.io/leagues",
                      headers={"x-apisports-key": API_FOOTBALL_KEY}, params={"team": team_id}, timeout=15)
    entrees = r.json().get("response", [])
    if not entrees:
        # Une réponse vide sur /leagues pour une équipe pro connue est presque toujours un
        # hoquet transitoire de l'API (constaté en pratique), pas une vraie absence de données
        # — on déclenche un retry plutôt que d'abandonner tout de suite.
        raise ValueError("réponse /leagues vide")
    return entrees


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
def _appel_team_statistics(team_id, league_id, season):
    _respecter_rate_limit_api_football()
    r = SESSION.get("https://v3.football.api-sports.io/teams/statistics",
                      headers={"x-apisports-key": API_FOOTBALL_KEY},
                      params={"team": team_id, "league": league_id, "season": season}, timeout=15)
    return r.json().get("response", {})


# Stats d'équipe mises en cache pour la durée du run : une même équipe (ou le même match
# listé deux fois par OddsPapi) ne coûte qu'une seule série d'appels API-Football/TheSportsDB.
_cache_stats_equipes = {}


def stats_equipe_en_cache(cle, calcul):
    if cle not in _cache_stats_equipes:
        _cache_stats_equipes[cle] = calcul()
    return _cache_stats_equipes[cle]


def trouver_ligue_et_stats(team_id, nom_affichage):
    """Reproduit la logique validée manuellement (t.py/q.py) :
    1) /leagues?team=ID pour lister toutes les compétitions/saisons de l'équipe
    2) priorité aux championnats (League, pas Cup), triés de la saison la plus récente à la plus ancienne
    3) /teams/statistics jusqu'à trouver une saison avec des matchs joués (played > 0),
       plafonné à MAX_TENTATIVES_SAISON appels pour ne pas exploser le quota.
    Chaque appel réseau a son propre retry (voir _appel_leagues_api_football et
    _appel_team_statistics) — un hoquet réseau isolé ne doit plus faire perdre les stats
    d'une équipe qui EN A réellement (constaté : Benfica/Beşiktaş/Twente etc. répondaient
    correctement en retestant juste après un échec pendant une collecte réelle)."""
    try:
        entrees = _appel_leagues_api_football(team_id)
    except Exception as e:
        print(f"      ⚠️ Aucune compétition trouvée pour {nom_affichage} (ID {team_id}) après retries : {e}")
        return None

    # Priorité : championnats (League) avant coupes, puis saison la plus récente d'abord
    candidats = []
    for e in entrees:
        type_competition = e.get("league", {}).get("type", "")
        for saison in e.get("seasons", []):
            if saison.get("year", 0) > SAISON_MAX_PLAN_GRATUIT:
                continue  # inaccessible sur le plan gratuit — inutile de gaspiller une tentative dessus
            candidats.append((type_competition != "League", -saison.get("year", 0), e["league"], saison["year"]))
    candidats.sort(key=lambda c: (c[0], c[1]))  # championnats d'abord (False < True), puis année décroissante

    tentatives = 0
    for _, _, league, year in candidats:
        if tentatives >= MAX_TENTATIVES_SAISON:
            break
        tentatives += 1
        try:
            stats = _appel_team_statistics(team_id, league["id"], year)
        except Exception:
            continue
        if isinstance(stats, list) or not stats:
            continue
        joues = stats.get("fixtures", {}).get("played", {}).get("total", 0)
        if joues and joues > 0:
            print(f"      ✓ {nom_affichage} : [{league['id']}] {league['name']} — saison {year} "
                  f"({joues} matchs joués)")
            return {
                "league_id": league["id"], "league_name": league["name"], "league_type": league.get("type"),
                "season": year, "matchs_joues": joues,
                "buts_marques_domicile": stats.get("goals", {}).get("for", {}).get("average", {}).get("home"),
                "buts_marques_exterieur": stats.get("goals", {}).get("for", {}).get("average", {}).get("away"),
                "buts_encaisses_domicile": stats.get("goals", {}).get("against", {}).get("average", {}).get("home"),
                "buts_encaisses_exterieur": stats.get("goals", {}).get("against", {}).get("average", {}).get("away"),
                "forme": stats.get("form"),
            }
    print(f"      ⚠️ Aucune saison avec matchs joués trouvée pour {nom_affichage} après {tentatives} tentatives")
    return None


# ============================================================
# STATS DÉTAILLÉES SUR LES 10 DERNIERS MATCHS — buts, corners, cartons, fautes (et plus),
# demande explicite de l'utilisateur (30/09/2026). Seule API-Football expose ces données
# match par match (endpoint /fixtures/statistics) ; TheSportsDB/Understat/ClubElo ne
# donnent au mieux que les buts. DÉSACTIVÉ PAR DÉFAUT (STATS_DETAILLEES_ACTIVE=False) :
# ~11 appels API-Football par équipe (1 liste + jusqu'à 10 statistiques par match), donc
# ~22 par match — beaucoup trop coûteux en quota pour tourner par défaut sur un plan
# gratuit à 10 req/min. À activer explicitement une fois le compte API-Football en état
# de supporter ce volume (plan payant, ou usage ponctuel plutôt qu'à chaque run).
# ============================================================

STATS_DETAILLEES_ACTIVE = False
NB_DERNIERS_MATCHS_DETAILLES = 10
NB_MATCHS_MIN_STATS_DETAILLEES = 3  # sous ce seuil, la moyenne est trop bruitée pour être fiable


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
def _appel_derniers_fixtures(team_id, n):
    _respecter_rate_limit_api_football()
    r = SESSION.get("https://v3.football.api-sports.io/fixtures",
                      headers={"x-apisports-key": API_FOOTBALL_KEY},
                      params={"team": team_id, "last": n, "status": "FT"}, timeout=15)
    return r.json().get("response", [])


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
def _appel_statistiques_fixture(fixture_id):
    _respecter_rate_limit_api_football()
    r = SESSION.get("https://v3.football.api-sports.io/fixtures/statistics",
                      headers={"x-apisports-key": API_FOOTBALL_KEY},
                      params={"fixture": fixture_id}, timeout=15)
    return r.json().get("response", [])


def _valeur_stat(bloc_stats, type_cherche):
    """bloc_stats = liste [{'type': 'Corner Kicks', 'value': 5}, ...] pour UNE équipe d'un
    match. API-Football renvoie parfois value=None (stat non suivie pour ce match/cette
    ligue) ou une chaîne avec '%' (Ball Possession, Passes %) — on nettoie dans les deux cas."""
    for item in bloc_stats or []:
        if item.get("type") == type_cherche:
            valeur = item.get("value")
            if valeur is None:
                return None
            if isinstance(valeur, str):
                valeur = valeur.replace("%", "").strip()
                if not valeur:
                    return None
            try:
                return float(valeur)
            except (TypeError, ValueError):
                return None
    return None


def recuperer_stats_10_derniers_matchs(team_id, nom_affichage):
    """15 métriques moyennées sur les NB_DERNIERS_MATCHS_DETAILLES (10) derniers matchs
    JOUÉS de l'équipe, toutes compétitions confondues (contrairement à trouver_ligue_et_
    stats, limité à UNE ligue/saison) : buts, corners, cartons, fautes, tirs, possession,
    hors-jeux, passes, clean sheets et forme (points par match). Renvoie None si moins de
    NB_MATCHS_MIN_STATS_DETAILLEES matchs ont des statistiques exploitables (échantillon
    trop faible, ou statistiques non suivies pour cette compétition/ce plan)."""
    try:
        fixtures = _appel_derniers_fixtures(team_id, NB_DERNIERS_MATCHS_DETAILLES)
    except Exception as e:
        print(f"      ⚠️ Derniers matchs introuvables pour {nom_affichage} (ID {team_id}) après retries : {e}")
        return None
    if not fixtures:
        return None

    buts_marques, buts_encaisses = [], []
    corners_pour, corners_contre = [], []
    cartons_jaunes, cartons_rouges = [], []
    fautes_commises, fautes_subies = [], []
    tirs_cadres, tirs_totaux = [], []
    possession, hors_jeux, passes_pct = [], [], []
    clean_sheets, points = 0, []

    for fx in fixtures:
        fixture_id = fx.get("fixture", {}).get("id")
        equipes = fx.get("teams", {})
        est_domicile = equipes.get("home", {}).get("id") == team_id
        buts = fx.get("goals", {})
        bp = buts.get("home") if est_domicile else buts.get("away")
        bc = buts.get("away") if est_domicile else buts.get("home")
        if bp is None or bc is None:
            continue
        buts_marques.append(bp)
        buts_encaisses.append(bc)
        if bc == 0:
            clean_sheets += 1
        gagnant = equipes.get("home", {}).get("winner") if est_domicile else equipes.get("away", {}).get("winner")
        points.append(3 if gagnant is True else (1 if gagnant is None else 0))

        try:
            stats_match = _appel_statistiques_fixture(fixture_id)
        except Exception:
            continue
        bloc = next((s.get("statistics") for s in stats_match if s.get("team", {}).get("id") == team_id), None)
        if not bloc:
            continue
        c = _valeur_stat(bloc, "Corner Kicks")
        if c is not None:
            corners_pour.append(c)
        cj = _valeur_stat(bloc, "Yellow Cards")
        if cj is not None:
            cartons_jaunes.append(cj)
        cr = _valeur_stat(bloc, "Red Cards")
        if cr is not None:
            cartons_rouges.append(cr)
        f = _valeur_stat(bloc, "Fouls")
        if f is not None:
            fautes_commises.append(f)
        tc = _valeur_stat(bloc, "Shots on Goal")
        if tc is not None:
            tirs_cadres.append(tc)
        tt = _valeur_stat(bloc, "Total Shots")
        if tt is not None:
            tirs_totaux.append(tt)
        pos = _valeur_stat(bloc, "Ball Possession")
        if pos is not None:
            possession.append(pos)
        hj = _valeur_stat(bloc, "Offsides")
        if hj is not None:
            hors_jeux.append(hj)
        pp = _valeur_stat(bloc, "Passes %")
        if pp is not None:
            passes_pct.append(pp)

        # Corners/fautes/cartons SUBIS (ou concédés) = ceux de l'adversaire sur ce match.
        bloc_adverse = next((s.get("statistics") for s in stats_match if s.get("team", {}).get("id") != team_id), None)
        if bloc_adverse:
            cc = _valeur_stat(bloc_adverse, "Corner Kicks")
            if cc is not None:
                corners_contre.append(cc)
            fs = _valeur_stat(bloc_adverse, "Fouls")
            if fs is not None:
                fautes_subies.append(fs)

    if len(buts_marques) < NB_MATCHS_MIN_STATS_DETAILLEES:
        print(f"      ⚠️ {nom_affichage} : seulement {len(buts_marques)} match(s) exploitable(s) sur "
              f"{NB_DERNIERS_MATCHS_DETAILLES} demandés (minimum {NB_MATCHS_MIN_STATS_DETAILLEES}) — ignoré.")
        return None

    def moyenne(liste):
        return round(sum(liste) / len(liste), 2) if liste else None

    resultat = {
        "source": "api_football_10_derniers_matchs",
        "matchs_avec_donnees": len(buts_marques),
        "buts_marques_moyenne": moyenne(buts_marques),
        "buts_encaisses_moyenne": moyenne(buts_encaisses),
        "corners_pour_moyenne": moyenne(corners_pour),
        "corners_contre_moyenne": moyenne(corners_contre),
        "cartons_jaunes_moyenne": moyenne(cartons_jaunes),
        "cartons_rouges_moyenne": moyenne(cartons_rouges),
        "fautes_commises_moyenne": moyenne(fautes_commises),
        "fautes_subies_moyenne": moyenne(fautes_subies),
        "tirs_cadres_moyenne": moyenne(tirs_cadres),
        "tirs_totaux_moyenne": moyenne(tirs_totaux),
        "possession_moyenne_pct": moyenne(possession),
        "hors_jeux_moyenne": moyenne(hors_jeux),
        "passes_reussies_pct_moyenne": moyenne(passes_pct),
        "clean_sheets_nombre": clean_sheets,
        "points_par_match_moyenne": moyenne(points),
    }
    print(f"      ✓ {nom_affichage} (API-Football, {len(buts_marques)}/{NB_DERNIERS_MATCHS_DETAILLES} derniers "
          f"matchs) : {resultat['buts_marques_moyenne']} buts marqués, {resultat['corners_pour_moyenne']} corners, "
          f"{resultat['cartons_jaunes_moyenne']} cartons jaunes, {resultat['fautes_commises_moyenne']} fautes "
          f"en moyenne")
    return resultat


# ============================================================
# UNDERSTAT — xG/xGA (buts attendus), source complémentaire pour les 5 grands
# championnats UNIQUEMENT (Ligue 1, Premier League, Serie A, Bundesliga, La Liga —
# Understat ne couvre pas les autres). Pas d'API officielle : les données sont
# intégrées dans le HTML de la page ligue sous forme de chaîne JS échappée
# (teamsData), décodée puis parsée en JSON. Une seule requête par LIGUE couvre
# TOUTES ses équipes (mise en cache pour la durée du run) — donc au pire 5
# requêtes au total, quota négligeable contrairement à API-Football.
#
# Le xG (expected goals) est le nombre de buts qu'une équipe "aurait dû" marquer
# vu la qualité de ses occasions — plus stable dans le temps que les buts réels,
# qui incluent la chance/malchance ponctuelle. C'est un signal complémentaire
# aux moyennes de buts d'API-Football, pas un remplacement : les deux sont
# conservés séparément dans la sortie JSON, à combiner dans l'analyse (Agent 4)
# comme jugé pertinent.
# ============================================================

UNDERSTAT_LIGUE_PAR_NOM = {
    "ligue 1": "Ligue_1",
    "premier league": "EPL",
    "serie a": "Serie_A",
    "bundesliga": "Bundesliga",
    "la liga": "La_liga",
}

# Understat identifie une saison par son année de DÉBUT (ex: saison 2025/2026 → 2025).
# Calculée automatiquement : la saison européenne démarre en juillet/août, donc de juillet
# à décembre c'est l'année en cours, de janvier à juin l'année précédente. (Auparavant
# fixée à la main à 2025 et oubliée au changement de saison 2026/2027.)
def saison_en_cours(date=None):
    date = date or datetime.now()
    return date.year if date.month >= 7 else date.year - 1


UNDERSTAT_SAISON = saison_en_cours()

_cache_understat_par_ligue = {}


@retry(stop=stop_after_attempt(3), wait=wait_fixed(3))
def _telecharger_page_understat(ligue_understat, saison):
    url = f"https://understat.com/league/{ligue_understat}/{saison}"
    r = SESSION.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text


def _extraire_teams_data_understat(html):
    """Le JSON teamsData est caché dans le HTML sous forme de chaîne JS échappée
    (JSON.parse('\\x7b...')) — on extrait la chaîne, on la décode (échappement JS
    \\xHH), puis on la parse comme du JSON normal."""
    import re
    match = re.search(r"var teamsData\s*=\s*JSON\.parse\('(.+?)'\)", html)
    if not match:
        return None
    chaine_echappee = match.group(1)
    decodee = chaine_echappee.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
    return json.loads(decodee)


def charger_teams_data_understat(ligue_understat):
    """Une requête par ligue par run, mise en cache — jamais plus de 5 requêtes
    Understat au total même si les 5 championnats sont tous traités."""
    if ligue_understat in _cache_understat_par_ligue:
        return _cache_understat_par_ligue[ligue_understat]
    try:
        html = _telecharger_page_understat(ligue_understat, UNDERSTAT_SAISON)
        teams_data = _extraire_teams_data_understat(html)
        if teams_data is None:
            # La page a répondu (200 OK, sinon l'exception ci-dessous aurait été levée) mais
            # le motif "var teamsData = JSON.parse(...)" attendu est introuvable dans le HTML
            # reçu — page de blocage anti-robot, structure de page changée, ou saison/ligue
            # invalide, plutôt qu'une vraie panne réseau (constaté le 29/09/2026 : aucune
            # erreur affichée, mais 0% de correspondance pour de grands clubs qui devraient
            # y être). Ce print rend le problème visible au lieu de le masquer en silence.
            print(f"      ⚠️ Understat ({ligue_understat}) : page reçue mais aucune donnée "
                  f"d'équipe extraite ({len(html)} caractères reçus) — page de blocage "
                  f"probable ou structure de page changée.")
    except Exception as e:
        print(f"      ⚠️ Understat indisponible pour {ligue_understat} après retries : {e}")
        teams_data = None
    _cache_understat_par_ligue[ligue_understat] = teams_data
    return teams_data


def trouver_stats_understat(nom_equipe, nom_ligue_detectee=None):
    """xG/xGA moyens par match sur la saison en cours. Cherche l'équipe dans les 5 grands
    championnats domestiques couverts par Understat (Ligue 1, Premier League, Serie A,
    Bundesliga, La Liga), quelle que soit la compétition du MATCH lui-même — demande
    explicite de l'utilisateur (30/09/2026) : un match de Ligue des Champions (ou toute
    autre coupe) oppose souvent deux équipes qui jouent chacune dans l'un de ces 5
    championnats le week-end ; les exclure faute de correspondance sur le nom de la
    compétition privait Understat de données pourtant disponibles (ex: Arsenal, Inter
    Milan, Villarreal — tous des grands clubs des 5 ligues couvertes — en Ligue des
    Champions). nom_ligue_detectee n'est plus utilisé (gardé pour compatibilité d'appel),
    la recherche se fait désormais dans les 5 ligues à chaque fois (au pire 5 requêtes
    Understat par run, déjà mises en cache — coût déjà annoncé comme le pire cas)."""
    from rapidfuzz import fuzz

    cible = unidecode(nom_equipe).lower()
    meilleur_score, meilleure_equipe, ligue_trouvee = 0, None, None
    for mot_cle, ligue_understat in UNDERSTAT_LIGUE_PAR_NOM.items():
        teams_data = charger_teams_data_understat(ligue_understat)
        if not teams_data:
            continue
        for equipe in teams_data.values():
            titre = equipe.get("title", "")
            score = fuzz.token_set_ratio(cible, unidecode(titre).lower())
            if score > meilleur_score:
                meilleur_score, meilleure_equipe, ligue_trouvee = score, equipe, ligue_understat

    if meilleur_score < SEUIL_MATCH_ACCEPTABLE or not meilleure_equipe:
        print(f"      ⚠️ {nom_equipe} introuvable sur Understat (5 grands championnats, "
              f"meilleur score {meilleur_score:.0f}%)")
        return None
    ligue_understat = ligue_trouvee

    historique = meilleure_equipe.get("history", [])
    if not historique:
        return None

    matchs_joues = len(historique)
    xg_total = sum(float(m.get("xG", 0)) for m in historique)
    xga_total = sum(float(m.get("xGA", 0)) for m in historique)
    xg_moyen = round(xg_total / matchs_joues, 2)
    xga_moyen = round(xga_total / matchs_joues, 2)

    # Forme récente (10 derniers matchs, demande explicite du 30/09/2026, ajustée de 5 à 10) —
    # la moyenne saison entière peut masquer un
    # changement de forme récent (bonne/mauvaise série). "history" est dans l'ordre
    # chronologique de disputes des matchs (ordre natif Understat), donc les 10 derniers
    # éléments = les 10 derniers matchs joués. Champ complémentaire, ne remplace pas la
    # moyenne saison (déjà utilisée ailleurs par calculer_xg_depuis_understat).
    dix_derniers = historique[-10:]
    xg_moyen_recent = round(sum(float(m.get("xG", 0)) for m in dix_derniers) / len(dix_derniers), 2)
    xga_moyen_recent = round(sum(float(m.get("xGA", 0)) for m in dix_derniers) / len(dix_derniers), 2)

    print(f"      ✓ {meilleure_equipe.get('title')} (Understat, score {meilleur_score:.0f}%) : "
          f"xG {xg_moyen} / xGA {xga_moyen} par match sur {matchs_joues} matchs "
          f"({len(dix_derniers)} derniers : xG {xg_moyen_recent} / xGA {xga_moyen_recent})")

    return {
        "source": "understat_xg",
        "matchs_joues": matchs_joues,
        "xg_moyen_par_match": xg_moyen,
        "xga_moyen_par_match": xga_moyen,
        "xg_moyen_10_derniers": xg_moyen_recent,
        "xga_moyen_10_derniers": xga_moyen_recent,
    }


# ============================================================
# CLUBELO — rating Elo par équipe, TOUTES ligues confondues (pas limité aux 5
# grandes, contrairement à Understat). Une seule requête pour TOUTE la journée
# (Elo de tous les clubs au monde à la date du jour), mise en cache — donc 1
# seul appel réseau total pour tout le run, quel que soit le nombre de matchs.
# Endpoint public, gratuit, sans clé requise.
#
# Le rating Elo capture la force perçue d'une équipe sur le long terme (ajusté
# match par match selon les résultats et l'adversaire) — signal indépendant des
# buts/xG déjà collectés, utile pour recouper plutôt que remplacer.
# ============================================================

_cache_clubelo = None

# Score de similarité plus permissif que SEUIL_MATCH_ACCEPTABLE (80) : ClubElo
# utilise souvent des noms abrégés/fusionnés (ex: "ManCity", "Paris" pour PSG),
# ce qui fait naturellement baisser le score même sur une bonne correspondance.
SEUIL_MATCH_CLUBELO = 70


@retry(stop=stop_after_attempt(1), wait=wait_fixed(0))
def _telecharger_clubelo_du_jour():
    # Constaté à plusieurs reprises (2026-09-29/30, runs GitHub Actions) : api.clubelo.com
    # n'est PAS lent, il est injoignable depuis les IP GitHub Actions — chaque tentative
    # épuise tout son timeout avant d'échouer. Avec l'ancien réglage (2 tentatives tenacity
    # x 4 sous-tentatives urllib3 de SESSION x 2 URLs x 25s), un run perdait jusqu'à 5-6
    # MINUTES rien que pour ce seul appel, systématiquement en échec. Comme retenter ne
    # change rien à un serveur injoignable : 1 seule tentative, timeout court, et une
    # requests.get() nue (pas SESSION) pour éviter que les retries réseau globaux de
    # SESSION ne fassent gonfler ce délai en plus de celui de tenacity.
    date_du_jour = datetime.now().strftime("%Y-%m-%d")
    # HTTPS d'abord, HTTP en secours (constaté le 2026-09-26 sur GitHub Actions : échec en HTTP).
    derniere_erreur = None
    for url in (f"https://api.clubelo.com/{date_du_jour}", f"http://api.clubelo.com/{date_du_jour}"):
        try:
            r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (analyse-football)"})
            r.raise_for_status()
            if r.text.startswith("Rank,Club"):
                return r.text
            derniere_erreur = ValueError(f"réponse inattendue de {url} : {r.text[:80]!r}")
        except Exception as e:
            derniere_erreur = e
    raise derniere_erreur


def charger_clubelo():
    """Une seule requête pour tout le run, mise en cache en mémoire."""
    global _cache_clubelo
    if _cache_clubelo is not None:
        return _cache_clubelo
    try:
        texte_csv = _telecharger_clubelo_du_jour()
        _cache_clubelo = list(csv.DictReader(io.StringIO(texte_csv)))
        print(f"   ✓ ClubElo chargé : {len(_cache_clubelo)} clubs (classement Elo du jour)")
    except Exception as e:
        print(f"   ⚠️ ClubElo indisponible après retries : {e}")
        _cache_clubelo = []
    return _cache_clubelo


def trouver_elo(nom_equipe):
    from rapidfuzz import fuzz

    clubs = charger_clubelo()
    if not clubs:
        return None

    cible = unidecode(nom_equipe).lower()
    meilleur_score, meilleur_club = 0, None
    for club in clubs:
        score = fuzz.token_set_ratio(cible, unidecode(club.get("Club", "")).lower())
        if score > meilleur_score:
            meilleur_score, meilleur_club = score, club

    if meilleur_score < SEUIL_MATCH_CLUBELO or not meilleur_club:
        print(f"      ⚠️ {nom_equipe} introuvable sur ClubElo (meilleur score {meilleur_score:.0f}%)")
        return None

    try:
        elo = round(float(meilleur_club.get("Elo", 0)), 1)
    except (TypeError, ValueError):
        return None

    print(f"      ✓ {meilleur_club.get('Club')} (ClubElo, score {meilleur_score:.0f}%) : Elo {elo}")
    return {
        "source": "clubelo",
        "club_elo_nom": meilleur_club.get("Club"),
        "elo": elo,
        "pays": meilleur_club.get("Country"),
    }


# ============================================================
# CLASSEMENT — via API-Football (/standings), demande explicite du 30/09/2026 : tout
# consolidé sur API-Football (déjà payant pour les stats détaillées 15 métriques),
# remplace football-data.org. Réutilise le league_id/season déjà résolus par
# trouver_ligue_et_stats pour la même équipe — pas d'appel réseau supplémentaire pour
# retrouver la compétition, juste /standings sur celle déjà connue.
#
# Une seule requête par (league_id, season) par run, mise en cache.
# ============================================================

_cache_classement_api_football = {}


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
def _appel_standings_api_football(league_id, season):
    _respecter_rate_limit_api_football()
    r = SESSION.get("https://v3.football.api-sports.io/standings",
                      headers={"x-apisports-key": API_FOOTBALL_KEY},
                      params={"league": league_id, "season": season}, timeout=15)
    return r.json().get("response", [])


def charger_classement_api_football(league_id, season):
    cle = (league_id, season)
    if cle in _cache_classement_api_football:
        return _cache_classement_api_football[cle]
    try:
        reponse = _appel_standings_api_football(league_id, season)
        groupes = reponse[0]["league"]["standings"] if reponse else []
        table = [ligne for groupe in groupes for ligne in groupe]
    except Exception as e:
        print(f"      ⚠️ Classement API-Football indisponible pour ligue {league_id}/{season} après retries : {e}")
        table = None
    _cache_classement_api_football[cle] = table
    return table


def trouver_classement(team_id, league_id, season, nom_affichage):
    # Pas de classement possible sans compétition résolue (ex : équipe sans stats
    # trouvées par trouver_ligue_et_stats), ou pour une phase à élimination directe sans
    # tableau de classement (ex : 8es de finale de Ligue des Champions).
    if not league_id or not season:
        return None
    table = charger_classement_api_football(league_id, season)
    if not table:
        return None

    ligne = next((l for l in table if l.get("team", {}).get("id") == team_id), None)
    if not ligne:
        print(f"      ⚠️ {nom_affichage} introuvable au classement API-Football (ligue {league_id}/{season})")
        return None

    tous = ligne.get("all", {})
    print(f"      ✓ {nom_affichage} (API-Football, classement) : {ligne.get('rank')}e, "
          f"{ligne.get('points')} pts, forme {ligne.get('form')}")

    return {
        "source": "api_football_classement",
        "position": ligne.get("rank"),
        "points": ligne.get("points"),
        "matchs_joues": tous.get("played"),
        "buts_marques": tous.get("goals", {}).get("for"),
        "buts_encaisses": tous.get("goals", {}).get("against"),
        "difference_buts": ligne.get("goalsDiff"),
        "forme_recente": ligne.get("form"),  # ex: "WWDLW" sur les derniers matchs
    }


def recuperer_fixtures_api_football():
    """Interroge hier/aujourd'hui/demain (3 appels) pour éviter qu'un match ne disparaisse
    de la liste à cause d'un décalage de fuseau horaire entre l'heure locale et l'API."""
    fixtures = []
    for delta_jours in (-1, 0, 1):
        date_cible = (datetime.now() + timedelta(days=delta_jours)).strftime("%Y-%m-%d")
        try:
            url = "https://v3.football.api-sports.io/fixtures"
            headers = {"x-apisports-key": API_FOOTBALL_KEY}
            params = {"date": date_cible}
            _respecter_rate_limit_api_football()
            r = SESSION.get(url, headers=headers, params=params, timeout=15)
            data = r.json()
            erreurs = data.get("errors")
            if erreurs:
                # API-Football renvoie souvent HTTP 200 même quota dépassé — seul le champ
                # "errors" (non vide) le révèle ; sans ce contrôle, un quota épuisé donnait
                # silencieusement "0 matchs", indiscernable d'un vrai jour sans match
                # (constaté le 2026-09-26, lors du repli de vérification des résultats).
                print(f"⚠️ API-Football erreur ({date_cible}) : {erreurs}")
                continue
            fixtures.extend(data.get("response", []))
        except Exception as e:
            print(f"⚠️ API-Football erreur ({date_cible}) : {e}")
    print(f"   → {len(fixtures)} matchs API-Football (hier/aujourd'hui/demain confondus)")
    return fixtures


def assez_tot_avant_coup_envoi(depart_iso, maintenant=None):
    """Faux si le match commence dans moins de MINUTES_MIN_AVANT_COUP_ENVOI minutes (ou est
    déjà commencé). Une heure illisible ou absente n'exclut pas le match."""
    if not depart_iso:
        return True
    try:
        depart = datetime.fromisoformat(str(depart_iso).replace("Z", "+00:00"))
    except ValueError:
        return True
    if depart.tzinfo is None:
        depart = depart.replace(tzinfo=timezone.utc)
    maintenant = maintenant or datetime.now(timezone.utc)
    return depart - maintenant >= timedelta(minutes=MINUTES_MIN_AVANT_COUP_ENVOI)


def selectionner_matchs_du_jour(fixtures_oddspapi):
    """Sélectionne entre NB_MATCHS_MIN et NB_MATCHS_MAX matchs DIRECTEMENT depuis la liste
    de fixtures OddsPapi déjà récupérée (aucun appel réseau supplémentaire) — la découverte
    ne dépend plus d'API-Football (quota quotidien limité, et ses league_id ne couvrent que
    la saison régulière : 0 résultat pendant les creux estivaux). API-Football garde son
    rôle : enrichir avec les vraies stats historiques quand son quota le permet (voir
    trouver_ligue_et_stats), jamais pour décider quels matchs jouer aujourd'hui.

    Priorité aux grandes compétitions (COMPETITIONS_PRIORITAIRES) ; complète avec les autres
    matchs ayant des cotes réelles (hasOdds=true) si pas assez de grandes compétitions ce
    jour-là. Exclut toujours les équipes réserve/jeunes/amateurs repérables."""
    candidats_bruts = [
        fx for fx in fixtures_oddspapi
        if fx.get("hasOdds")
        and fx.get("statusName") == "Pre-Game"
        and assez_tot_avant_coup_envoi(fx.get("startTime"))
        and not contient_indicateur_reserve(fx.get("participant1Name", ""))
        and not contient_indicateur_reserve(fx.get("participant2Name", ""))
        and not est_competition_feminine(fx.get("tournamentName"), fx.get("categoryName"))
    ]

    # Dédoublonnage par paire d'équipes — OddsPapi renvoie parfois deux fois le même vrai
    # match (constaté en pratique), jamais vérifié avant faute de quoi le même match pourrait
    # être compté deux fois dans le ticket final.
    vus = set()
    candidats = []
    for fx in candidats_bruts:
        cle = (fx.get("participant1Name"), fx.get("participant2Name"))
        if cle in vus:
            continue
        vus.add(cle)
        candidats.append(fx)

    # Filtre multi-ligues (ex: les 5 grands championnats seulement aujourd'hui) — appliqué
    # AVANT le tri prioritaires/reste pour que le repli ne réintroduise pas d'autres ligues.
    if FILTRE_LIGUES_UNIQUES:
        avant = len(candidats)

        def correspond_au_filtre(fx, filtre):
            nom_tournoi = (fx.get("tournamentName") or "").lower()
            pays = (fx.get("categoryName") or "").lower()
            return any(
                mot_cle_ligue in nom_tournoi and (pays_attendu is None or pays_attendu in pays)
                for mot_cle_ligue, pays_attendu in filtre
            )

        tous_candidats = candidats
        candidats = [fx for fx in tous_candidats if correspond_au_filtre(fx, FILTRE_LIGUES_UNIQUES)]
        noms_filtre = ", ".join(f"{lg} ({p})" if p else lg for lg, p in FILTRE_LIGUES_UNIQUES)
        print(f"   🎯 Filtre multi-ligues actif : {noms_filtre} — {len(candidats)}/{avant} candidats retenus")

        if len(candidats) < NB_MATCHS_MIN and FILTRE_LIGUES_SECOURS:
            deja = {id(fx) for fx in candidats}
            secours = [fx for fx in tous_candidats
                       if id(fx) not in deja and correspond_au_filtre(fx, FILTRE_LIGUES_SECOURS)]
            candidats = candidats + secours
            print(f"   🛟 Moins de {NB_MATCHS_MIN} matchs dans les grands championnats (trêve internationale ?) — "
                  f"{len(secours)} match(s) ajouté(s) depuis les compétitions de secours "
                  f"(Ligue des nations, coupes d'Europe, 2es divisions...).")

        if not candidats and avant > 0:
            # Diagnostic : le filtre n'a RIEN retenu alors que des matchs existaient avant
            # filtrage — signe quasi certain que le nom de tournoi/pays attendu ne correspond
            # pas à ce qu'OddsPapi renvoie réellement (ex: "EPL" au lieu de "Premier League").
            # On affiche les (tournoi, pays) réels vus, triés par fréquence, pour corriger
            # FILTRE_LIGUES_UNIQUES avec les vraies valeurs plutôt que deviner.
            from collections import Counter
            paires_vues = Counter(
                (fx.get("tournamentName") or "?", fx.get("categoryName") or "?")
                for fx in candidats_bruts
            )
            print(f"   🔍 Aucun candidat ne correspond — voici les {min(20, len(paires_vues))} "
                  f"tournoi(s)/pays réellement vus par OddsPapi aujourd'hui (les plus fréquents) :")
            for (tournoi, pays), nb in paires_vues.most_common(20):
                print(f"      • \"{tournoi}\" — pays: \"{pays}\" ({nb} match(s))")
            print("   → Compare ces valeurs EXACTES à FILTRE_LIGUES_UNIQUES en haut du fichier "
                  "et corrige les mots-clés si besoin.")

    def est_prioritaire(fx):
        nom_tournoi = (fx.get("tournamentName") or "").lower()
        pays = (fx.get("categoryName") or "").lower()
        if any(mot_cle in nom_tournoi for mot_cle in COMPETITIONS_EUROPEENNES_UNIQUES):
            return True
        return any(mot_cle in nom_tournoi for mot_cle in LIGUES_DOMESTIQUES_MAJEURES.get(pays, ()))

    prioritaires = sorted((fx for fx in candidats if est_prioritaire(fx)), key=lambda fx: fx.get("startTime", ""))
    reste = sorted((fx for fx in candidats if not est_prioritaire(fx)), key=lambda fx: fx.get("startTime", ""))

    selection = (prioritaires + reste)[:NB_CANDIDATS_A_SONDER]
    nb_prioritaires_retenus = sum(1 for fx in selection if est_prioritaire(fx))

    matchs = [(fx["participant1Name"], fx["participant2Name"]) for fx in selection]
    if matchs:
        print(f"   ✓ {len(matchs)} match(s) sélectionné(s) avec cotes réelles "
              f"({nb_prioritaires_retenus} grande(s) compétition(s) prioritaire(s), sur {len(candidats)} candidats au total) :")
        for h, a in matchs:
            print(f"      • {h} vs {a}")
        if len(matchs) < NB_MATCHS_MIN:
            print(f"   ⚠️ Seulement {len(matchs)} match(s) trouvé(s) avec cotes réelles (objectif minimum : {NB_MATCHS_MIN}).")
    else:
        print("   ⚠️ Aucun match avec cotes réelles trouvé sur OddsPapi — repli sur MATCHS_MANUELS s'il date d'aujourd'hui")
    return matchs


def trouver_fixture_api_football(home_cherche, away_cherche, tous_fixtures):
    cible_contient_reserve = contient_indicateur_reserve(home_cherche) or contient_indicateur_reserve(away_cherche)
    meilleur_score, meilleur_fx = 0, None
    for fx in tous_fixtures:
        home_api = fx.get("teams", {}).get("home", {}).get("name", "")
        away_api = fx.get("teams", {}).get("away", {}).get("name", "")
        # Rejet immédiat : candidat "réserve/jeunes" alors que la demande ne l'est pas
        if not cible_contient_reserve and (contient_indicateur_reserve(home_api) or contient_indicateur_reserve(away_api)):
            continue
        score = score_paire_equipes(home_cherche, away_cherche, home_api, away_api)
        if score > meilleur_score:
            meilleur_score, meilleur_fx = score, fx
    if meilleur_score >= SEUIL_MATCH_ACCEPTABLE:
        return meilleur_fx, meilleur_score
    return None, meilleur_score


# ============================================================
# ODDSPAPI — 1 appel fixtures + 1 appel odds par match trouvé
# ============================================================

def verifier_quota_oddspapi():
    try:
        r = SESSION.get("https://api.oddspapi.io/v4/sports", params={"apiKey": ODDSPAPI_KEY}, timeout=(5, 10), verify=VERIFIER_SSL_ODDSPAPI)
        if r.status_code == 401:
            print("   ❌ Clé OddsPapi invalide (401) — vérifie ODDSPAPI_KEY dans envi.local")
            return False
        if r.status_code == 429:
            print(f"   ❌ Quota OddsPapi déjà épuisé — {r.text[:200]}")
            return False
        if r.status_code != 200:
            print(f"   ⚠️ OddsPapi statut inattendu au check préalable : {r.status_code}")
            return False
        return True
    except Exception as e:
        print(f"   ⚠️ Impossible de vérifier OddsPapi : {e}")
        return False


# Fenêtre de collecte normale : aujourd'hui + 2 jours. DATE_CIBLE_DEBUT/DATE_CIBLE_FIN
# (AAAA-MM-JJ) permettent de viser une période différente pour un run ponctuel — ex: demande
# explicite de l'utilisateur du 29/09/2026 de préparer un coupon pour le 10-12 octobre plutôt
# que le jour même, pendant la trêve internationale où aucun grand championnat ne joue.
DATE_CIBLE_DEBUT = os.getenv("DATE_CIBLE_DEBUT")
DATE_CIBLE_FIN = os.getenv("DATE_CIBLE_FIN")


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=5, max=30))
def _telecharger_fixtures_oddspapi():
    if DATE_CIBLE_DEBUT and DATE_CIBLE_FIN:
        date_from = f"{DATE_CIBLE_DEBUT}T00:00:00Z"
        date_to = f"{DATE_CIBLE_FIN}T00:00:00Z"
    else:
        date_from = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
        date_to = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    url = "https://api.oddspapi.io/v4/fixtures"
    params = {"apiKey": ODDSPAPI_KEY, "sportId": 10, "from": date_from, "to": date_to}
    r = SESSION.get(url, params=params, timeout=(5, 20), verify=VERIFIER_SSL_ODDSPAPI)
    if r.status_code == 429:
        print(f"   ⚠️ OddsPapi fixtures 429 — corps: {r.text[:200]}")
        raise ValueError("429 rate limited / quota exceeded")
    if r.status_code == 401:
        print(f"   ❌ OddsPapi fixtures 401 — clé invalide : {r.text[:200]}")
        return []
    if r.status_code != 200:
        print(f"   ⚠️ OddsPapi fixtures status {r.status_code} — corps: {r.text[:200]}")
        return []
    fixtures = r.json()
    return fixtures if isinstance(fixtures, list) else []


def trouver_fixture_oddspapi(home_cherche, away_cherche, fixtures_oddspapi):
    cible_contient_reserve = contient_indicateur_reserve(home_cherche) or contient_indicateur_reserve(away_cherche)
    meilleur_score, meilleur_fx = 0, None
    for fx in fixtures_oddspapi:
        p1 = fx.get("participant1Name", "")
        p2 = fx.get("participant2Name", "")
        if not cible_contient_reserve and (contient_indicateur_reserve(p1) or contient_indicateur_reserve(p2)):
            continue
        score = score_paire_equipes(home_cherche, away_cherche, p1, p2)
        if score > meilleur_score:
            meilleur_score, meilleur_fx = score, fx
    if meilleur_score >= SEUIL_MATCH_ACCEPTABLE:
        return meilleur_fx, meilleur_score
    return None, meilleur_score


def get_market_names():
    global MARKET_NAMES_CACHE
    if MARKET_NAMES_CACHE:
        return MARKET_NAMES_CACHE
    try:
        r = SESSION.get("https://api.oddspapi.io/v4/markets", params={"apiKey": ODDSPAPI_KEY}, timeout=(5, 15), verify=VERIFIER_SSL_ODDSPAPI)
        data = r.json()
        for m in data:
            if m.get("sportId") == 10:
                outcomes_map = {str(o["outcomeId"]): o["outcomeName"] for o in m.get("outcomes", [])}
                MARKET_NAMES_CACHE[str(m["marketId"])] = {
                    "name": m.get("marketName"), "type": m.get("marketType"),
                    "handicap": m.get("handicap"), "period": m.get("period"), "outcomes": outcomes_map
                }
    except Exception as e:
        print(f"⚠️ Erreur récupération noms de marchés : {e}")
    return MARKET_NAMES_CACHE


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def _telecharger_odds_oddspapi(fixture_id):
    url_odds = "https://api.oddspapi.io/v4/odds"
    params_odds = {"apiKey": ODDSPAPI_KEY, "fixtureId": fixture_id, "bookmakers": "1xbet", "oddsFormat": "decimal"}
    r2 = SESSION.get(url_odds, params=params_odds, timeout=(5, 20), verify=VERIFIER_SSL_ODDSPAPI)
    if r2.status_code == 429:
        raise ValueError("429 rate limited")
    if r2.status_code != 200:
        print(f"      ⚠️ OddsPapi odds status {r2.status_code} — corps: {r2.text[:200]}")
        return None
    return r2.json()


def recuperer_marches_pour_fixture(fixture_id):
    """Récupère TOUS les marchés 1xbet SAUF le 1X2, avec le vocabulaire brut
    (noms de marché et de sélection tels que fournis par OddsPapi, sans simplification)."""
    try:
        data = _telecharger_odds_oddspapi(fixture_id)
    except Exception as e:
        print(f"      ⚠️ OddsPapi odds indisponible après retries : {e}")
        return None
    if not data:
        return None

    noms_marches = get_market_names()
    tous_marches = []
    for event in (data if isinstance(data, list) else [data]):
        bookmaker_odds = event.get("bookmakerOdds", {}).get("1xbet", {})
        markets = bookmaker_odds.get("markets", {})
        for market_id, market_data in markets.items():
            info_marche = noms_marches.get(str(market_id), {})
            marche_type = info_marche.get("type", "")

            # On exclut uniquement le 1X2 — tout le reste est gardé, en détail
            if marche_type == "1x2" or info_marche.get("name") == "Full Time Result":
                continue

            nom_marche_brut = info_marche.get("name", f"Marché {market_id}")
            handicap = info_marche.get("handicap")
            periode = info_marche.get("period")
            outcomes_noms = info_marche.get("outcomes", {})
            outcomes_data = market_data.get("outcomes", {})

            selections = []
            for outcome_id, outcome_data in outcomes_data.items():
                players = outcome_data.get("players", {})
                prix = players.get("0", {}).get("price")
                outcome_brut = outcomes_noms.get(str(outcome_id), f"Option {outcome_id}")
                if prix:
                    # Vocabulaire brut conservé tel quel, aucune traduction/simplification
                    selections.append({"selection": outcome_brut, "cote": prix})

            if selections:
                tous_marches.append({
                    "marche_id": market_id,
                    "marche": nom_marche_brut,
                    "handicap": handicap,
                    "periode": periode,
                    "selections": selections,
                })
    return tous_marches if tous_marches else None


# ============================================================
# SERPER — contexte web brut (forme, blessures, preview) — 1 appel par match
# ============================================================

@retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
def _appel_serper(query):
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    r = SESSION.post(url, json={"q": query}, headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"      ⚠️ Serper status {r.status_code}")
        return None
    return r.json()


def collecter_contexte_serper(home, away):
    if not SERPER_API_KEY:
        return None
    query = f"{home} vs {away} preview blessures forme"
    try:
        data = _appel_serper(query)
    except Exception as e:
        print(f"      ⚠️ Serper indisponible après retries : {e}")
        return None
    if not data:
        return None
    resultats = data.get("organic", [])[:5]
    return {
        "query": query,
        "resultats": [
            {"titre": item.get("title"), "extrait": item.get("snippet"), "lien": item.get("link")}
            for item in resultats
        ],
    }


# ============================================================
# COLLECTE — pas de calcul, juste API-Football + OddsPapi + Serper bruts
# ============================================================

def collecter_donnees():
    print(f"🚀 Collecte de données brutes pour {NB_MATCHS_MIN} à {NB_MATCHS_MAX} matchs "
          f"(API-Football + stats historiques + OddsPapi + Serper)...")

    print("   → Vérification préalable de la clé OddsPapi (1 appel léger)...")
    if not verifier_quota_oddspapi():
        print("   ⚠️ OddsPapi indisponible — les matchs seront collectés sans cotes")

    print("   → Récupération de la liste des fixtures OddsPapi (1 seul appel)...")
    try:
        fixtures_oddspapi = _telecharger_fixtures_oddspapi()
        print(f"   ✓ {len(fixtures_oddspapi)} fixtures OddsPapi chargées")
    except Exception as e:
        print(f"   ⚠️ OddsPapi fixtures indisponible après retries : {e}")
        fixtures_oddspapi = []
    # Comparée à la date cible du run (DATE_CIBLE_DEBUT) quand elle est fournie, sinon à
    # aujourd'hui — sans ça, une sélection manuelle préparée pour une période future (ex: un
    # run lancé le 29/09 pour des matchs du 13/10) serait toujours jugée "périmée", puisque
    # "aujourd'hui" ne correspondrait jamais à la date de la liste avant le jour J lui-même.
    date_reference = DATE_CIBLE_DEBUT or datetime.now().strftime("%Y-%m-%d")
    liste_manuelle_du_jour = MATCHS_MANUELS_DATE == date_reference
    if SELECTION_MANUELLE_ACTIVE and not liste_manuelle_du_jour:
        print(f"   ⚠️ Sélection manuelle active mais MATCHS_MANUELS date du {MATCHS_MANUELS_DATE} "
              f"(périmée) — ignorée, bascule sur la sélection automatique.")
    # Mode manuel RÉELLEMENT utilisé ce jour-là : une liste périmée ne désactive pas les règles
    # de la sélection automatique (arrêt à NB_MATCHS_MAX, exclusion féminines / sans cotes).
    mode_manuel = SELECTION_MANUELLE_ACTIVE and liste_manuelle_du_jour
    if mode_manuel:
        print(f"   🎯 Sélection manuelle active — {len(MATCHS_MANUELS)} match(s) fournis directement, "
              f"sélection automatique par ligue ignorée.")
        matchs_a_traiter = MATCHS_MANUELS
    else:
        print("   → Sélection des matchs du jour (source OddsPapi, indépendante du quota API-Football)...")
        matchs_a_traiter = selectionner_matchs_du_jour(fixtures_oddspapi)
        if not matchs_a_traiter and liste_manuelle_du_jour:
            matchs_a_traiter = MATCHS_MANUELS

    tous_fixtures_af = recuperer_fixtures_api_football()

    resultats = []

    for home_demande, away_demande in matchs_a_traiter:
        if not mode_manuel and sum(1 for r in resultats if r["oddspapi"]["tous_marches"]) >= NB_MATCHS_MAX:
            print(f"   ✓ {NB_MATCHS_MAX} matchs avec marchés trouvés — sondage des candidats restants arrêté.")
            break
        print(f"   → Collecte : {home_demande} vs {away_demande}")

        # --- API-Football : identité, ligue, saison, date ---
        fx_af, score_af = trouver_fixture_api_football(home_demande, away_demande, tous_fixtures_af)
        donnees_af = None
        if fx_af:
            donnees_af = {
                "home_name": fx_af.get("teams", {}).get("home", {}).get("name"),
                "away_name": fx_af.get("teams", {}).get("away", {}).get("name"),
                "home_id": fx_af.get("teams", {}).get("home", {}).get("id"),
                "away_id": fx_af.get("teams", {}).get("away", {}).get("id"),
                "league_id": fx_af.get("league", {}).get("id"),
                "league_name": fx_af.get("league", {}).get("name"),
                "season": fx_af.get("league", {}).get("season"),
                "fixture_date": fx_af.get("fixture", {}).get("date"),
                "fixture_id_api_football": fx_af.get("fixture", {}).get("id"),
                "score_matching": score_af,
            }
            print(f"      ✓ API-Football trouvé (score {score_af:.0f}%) : {donnees_af['home_name']} vs {donnees_af['away_name']}")
        else:
            print(f"      ⚠️ Aucune correspondance API-Football (meilleur score : {score_af:.0f}%)")

        if not mode_manuel and donnees_af and (
                est_equipe_feminine_api_football(donnees_af["home_name"])
                or est_equipe_feminine_api_football(donnees_af["away_name"])):
            print(f"      ⏭️ Match féminin ({donnees_af['home_name']} vs {donnees_af['away_name']}) — ignoré.")
            continue

        # --- OddsPapi : cotes réelles 1xbet, tous marchés ---
        fx_op, score_op = trouver_fixture_oddspapi(home_demande, away_demande, fixtures_oddspapi)
        tous_marches = None
        fixture_id_oddspapi = None
        if fx_op:
            fixture_id_oddspapi = fx_op.get("fixtureId")
            print(f"      ✓ OddsPapi trouvé (score {score_op:.0f}%) : "
                  f"{fx_op.get('participant1Name')} vs {fx_op.get('participant2Name')}")
            tous_marches = recuperer_marches_pour_fixture(fixture_id_oddspapi)
            if tous_marches:
                print(f"      ✓ {len(tous_marches)} marchés 1xbet collectés")
            else:
                print(f"      ⚠️ Aucun marché disponible pour ce fixture")
        else:
            print(f"      ⚠️ Aucune correspondance OddsPapi (meilleur score : {score_op:.0f}%)")

        if not tous_marches and not mode_manuel:
            print("      ⏭️ Aucun marché exploitable — match écarté sans autre appel (stats, Elo, presse).")
            continue

        # --- Serper : contexte web brut — utilise le nom OddsPapi (100% de match sur les 8)
        # si dispo, sinon le nom d'origine demandé. Ne dépend plus d'API-Football.
        contexte_web = None
        nom_home_pour_recherche = fx_op.get("participant1Name") if fx_op else home_demande
        nom_away_pour_recherche = fx_op.get("participant2Name") if fx_op else away_demande
        print(f"      → Collecte contexte web (Serper)...")
        contexte_web = collecter_contexte_serper(nom_home_pour_recherche, nom_away_pour_recherche)
        if contexte_web:
            print(f"      ✓ {len(contexte_web['resultats'])} résultats Serper collectés")
        else:
            print(f"      ⚠️ Aucun contexte Serper disponible")

        # --- Statistiques historiques : API-Football (saison, domicile/extérieur séparés).
        # Repli TheSportsDB retiré (demande explicite du 30/09/2026 : tout consolidé sur
        # API-Football) — sans stats API-Football, le match repose sur l'estimation par
        # les cotes plus loin dans le pipeline.
        nom_home_stats = donnees_af["home_name"] if donnees_af else home_demande
        nom_away_stats = donnees_af["away_name"] if donnees_af else away_demande

        stats_home, stats_away = None, None
        if donnees_af and donnees_af.get("home_id"):
            print(f"      → Recherche stats historiques {nom_home_stats} (API-Football)...")
            stats_home = stats_equipe_en_cache(("api_football", donnees_af["home_id"]),
                                               lambda: trouver_ligue_et_stats(donnees_af["home_id"], nom_home_stats))

        if donnees_af and donnees_af.get("away_id"):
            print(f"      → Recherche stats historiques {nom_away_stats} (API-Football)...")
            stats_away = stats_equipe_en_cache(("api_football", donnees_af["away_id"]),
                                               lambda: trouver_ligue_et_stats(donnees_af["away_id"], nom_away_stats))

        # --- Stats détaillées (10 derniers matchs) : buts, corners, cartons, fautes, tirs,
        # possession, hors-jeux, passes, clean sheets, forme — 15 métriques, demande
        # explicite du 30/09/2026. Désactivé par défaut (STATS_DETAILLEES_ACTIVE, coût en
        # quota API-Football élevé) — voir recuperer_stats_10_derniers_matchs.
        stats_detaillees_home, stats_detaillees_away = None, None
        if STATS_DETAILLEES_ACTIVE and donnees_af and donnees_af.get("home_id"):
            print(f"      → Recherche stats détaillées {nom_home_stats} (10 derniers matchs, API-Football)...")
            stats_detaillees_home = stats_equipe_en_cache(
                ("api_football_10_matchs", donnees_af["home_id"]),
                lambda: recuperer_stats_10_derniers_matchs(donnees_af["home_id"], nom_home_stats))
        if STATS_DETAILLEES_ACTIVE and donnees_af and donnees_af.get("away_id"):
            print(f"      → Recherche stats détaillées {nom_away_stats} (10 derniers matchs, API-Football)...")
            stats_detaillees_away = stats_equipe_en_cache(
                ("api_football_10_matchs", donnees_af["away_id"]),
                lambda: recuperer_stats_10_derniers_matchs(donnees_af["away_id"], nom_away_stats))

        # --- Understat : xG/xGA complémentaires, cherché dans les 5 grands championnats
        # domestiques quel que soit la compétition du match (voir trouver_stats_understat) —
        # ne dépend plus d'API-Football (donnees_af), dont le quota/compte peut être
        # indisponible sans rapport avec la couverture réelle d'Understat. N'écrase jamais
        # stats_home/stats_away, s'ajoute à côté dans la sortie JSON.
        print(f"      → Recherche xG/xGA {nom_home_stats} (Understat)...")
        understat_home = trouver_stats_understat(nom_home_stats)
        print(f"      → Recherche xG/xGA {nom_away_stats} (Understat)...")
        understat_away = trouver_stats_understat(nom_away_stats)

        # --- ClubElo : rating de force, toutes ligues (1 seule requête pour tout
        # le run, déjà en cache après le premier match traité).
        print(f"      → Recherche rating Elo {nom_home_stats} (ClubElo)...")
        elo_home = trouver_elo(nom_home_stats)
        print(f"      → Recherche rating Elo {nom_away_stats} (ClubElo)...")
        elo_away = trouver_elo(nom_away_stats)

        # --- Classement : API-Football (/standings), réutilise le league_id/season déjà
        # résolus par trouver_ligue_et_stats ci-dessus — pas d'appel réseau supplémentaire
        # pour retrouver la compétition. Renvoie None sans erreur si stats_home/away n'a
        # rien trouvé, ou si la compétition n'a pas de tableau de classement (ex : phase à
        # élimination directe de Ligue des Champions).
        classement_home, classement_away = None, None
        if donnees_af and donnees_af.get("home_id") and stats_home:
            print(f"      → Recherche classement {nom_home_stats} (API-Football)...")
            classement_home = trouver_classement(donnees_af["home_id"], stats_home.get("league_id"),
                                                  stats_home.get("season"), nom_home_stats)
        if donnees_af and donnees_af.get("away_id") and stats_away:
            print(f"      → Recherche classement {nom_away_stats} (API-Football)...")
            classement_away = trouver_classement(donnees_af["away_id"], stats_away.get("league_id"),
                                                  stats_away.get("season"), nom_away_stats)

        resultats.append({
            "match_demande": {"home": home_demande, "away": away_demande},
            "api_football": donnees_af,
            "oddspapi": {
                "fixture_id": fixture_id_oddspapi,
                "score_matching": score_op,
                "tous_marches": tous_marches,
            },
            "serper": contexte_web,
            "stats_historiques": {"home": stats_home, "away": stats_away},
            "stats_detaillees_10_matchs": {"home": stats_detaillees_home, "away": stats_detaillees_away},
            "understat_xg": {"home": understat_home, "away": understat_away},
            "clubelo": {"home": elo_home, "away": elo_away},
            "classement": {"home": classement_home, "away": classement_away},
        })

    sortie = {
        "date_collecte": datetime.now().isoformat(),
        "nb_matchs_demandes": len(resultats),
        "nb_matchs_avec_marches": sum(1 for r in resultats if r["oddspapi"]["tous_marches"]),
        "nb_marches_total": sum(len(r["oddspapi"]["tous_marches"] or []) for r in resultats),
        "nb_equipes_avec_stats": sum(
            1 for r in resultats for cote in ("home", "away") if r["stats_historiques"][cote]
        ),
        "nb_equipes_avec_stats_detaillees": sum(
            1 for r in resultats for cote in ("home", "away") if r["stats_detaillees_10_matchs"][cote]
        ),
        "nb_equipes_avec_xg": sum(
            1 for r in resultats for cote in ("home", "away") if r["understat_xg"][cote]
        ),
        "nb_equipes_avec_elo": sum(
            1 for r in resultats for cote in ("home", "away") if r["clubelo"][cote]
        ),
        "nb_equipes_avec_classement": sum(
            1 for r in resultats for cote in ("home", "away") if r["classement"][cote]
        ),
        "matchs": resultats,
    }

    with open(SORTIE_JSON, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Données sauvegardées dans {SORTIE_JSON}")
    print(f"   ✓ {sortie['nb_matchs_avec_marches']}/{sortie['nb_matchs_demandes']} matchs avec marchés 1xbet collectés")
    print(f"   ✓ {sortie['nb_marches_total']} marchés au total (1X2 exclu, tout le reste en détail)")
    print(f"   ✓ {sortie['nb_equipes_avec_stats']}/{len(resultats) * 2} équipes avec stats historiques trouvées")
    if STATS_DETAILLEES_ACTIVE:
        print(f"   ✓ {sortie['nb_equipes_avec_stats_detaillees']}/{len(resultats) * 2} équipes avec stats "
              f"détaillées (10 derniers matchs, 15 métriques) trouvées")
    print(f"   ✓ {sortie['nb_equipes_avec_xg']}/{len(resultats) * 2} équipes avec xG/xGA Understat trouvées "
          f"(5 grands championnats uniquement)")
    print(f"   ✓ {sortie['nb_equipes_avec_elo']}/{len(resultats) * 2} équipes avec rating ClubElo trouvées")
    print(f"   ✓ {sortie['nb_equipes_avec_classement']}/{len(resultats) * 2} équipes avec classement "
          f"API-Football trouvées")


if __name__ == "__main__":
    collecter_donnees()


