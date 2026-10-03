"""
Agent 6 — VÉRIFICATION DES RÉSULTATS. Bibliothèque de fonctions pures (récupération des
scores/statistiques réels, jugement de chaque jambe gagnée/perdue/remboursée) appelée par
backend/app/services/verification.py (verifier_jambes), qui lit les jambes "en_attente" en
base Postgres/SQLite et persiste le verdict — ce module ne fait plus lui-même aucune
lecture/écriture de fichier ni d'envoi Telegram (ancien point d'entrée CLI, basé sur
ticket_du_jour.json, retiré le 03/10/2026 : remplacé par `python -m app.taches verifier`,
seul appelé par .github/workflows/verification-resultats.yml).

Ne rejuge JAMAIS un chiffre du ticket original (cote, marché, sélection) — les recopie
tels quels, ne fait que comparer au score/à la statistique réelle.
"""

import os
import re
import requests
import urllib3
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from unidecode import unidecode
from rapidfuzz import fuzz

# Voir collecte_donnees.py pour le détail : OddsPapi est intercepté par un boîtier réseau
# (Fortinet) qui re-signe son certificat avec une CA non reconnue — désactivé uniquement
# pour ce domaine précis (déjà intercepté de toute façon), jamais pour Telegram.

load_dotenv("envi.local")

# Vérification du certificat OddsPapi : ACTIVE par défaut (GitHub Actions, serveur, PC).
# ODDSPAPI_SSL_NON_VERIFIE=true seulement sur un réseau qui intercepte le certificat (boîtier
# Fortinet constaté sur l'ancien environnement Termux) — jamais pour les autres APIs.
VERIFIER_SSL_ODDSPAPI = os.getenv("ODDSPAPI_SSL_NON_VERIFIE", "").lower() not in ("1", "true", "oui")
if not VERIFIER_SSL_ODDSPAPI:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY")

# Corners/cartons/fautes/tirs/hors-jeux : OddsPapi /v4/scores ne renvoie QUE les buts —
# longtemps non vérifiables du tout (constaté le 03/10/2026 : 442 jambes sur 809, 55% de la
# base, "non_verifiable" pour cette seule raison). API-Football expose ces statistiques
# finales via /fixtures/statistics (même endpoint déjà utilisé par collecte_donnees.py pour
# les stats PRÉ-match, recuperer_stats_10_derniers_matchs) — réutilisé ici POST-match pour
# juger ces marchés au lieu de les abandonner. Catégorie -> nom du type de statistique
# API-Football (voir collecte_donnees._valeur_stat).
STAT_API_FOOTBALL_PAR_CATEGORIE = {
    "Total Corners": "Corner Kicks", "Handicap Corners": "Corner Kicks",
    "Total Cartons": "Yellow Cards", "Handicap Cartons": "Yellow Cards",
    "Total Cartons Équipe 1": "Yellow Cards", "Total Cartons Équipe 2": "Yellow Cards",
    "Total Fautes": "Fouls", "Handicap Fautes": "Fouls",
    "Total Tirs": "Total Shots", "Handicap Tirs": "Total Shots",
    "Total Tirs Cadrés": "Shots on Goal", "Handicap Tirs Cadrés": "Shots on Goal",
    "Total Hors-jeux": "Offsides", "Handicap Hors-jeux": "Offsides",
}

# Suivi EN DIRECT (demande explicite du 01/10/2026, pendant un match réel suivi manuellement
# par l'utilisateur : "on trouve pas un endpoint sur api football en match live") — statuts
# API-Football (fixture.status.short) considérés comme un match EN COURS, ni pas commencé
# ("NS") ni terminé ("FT"/"AET"/"PEN"/"PST"/"CANC"/"ABD"/"AWD"/"WO"/"TBD").
STATUTS_EN_DIRECT = ("1H", "HT", "2H", "ET", "BT", "P", "INT", "LIVE")


def recuperer_fixtures_du_jour():
    """Fenêtre large (-1 à +2 jours) pour ne jamais rater un match à cheval sur minuit UTC,
    même logique de sécurité que collecte_donnees.py."""
    date_from = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    try:
        r = requests.get("https://api.oddspapi.io/v4/fixtures",
                          params={"apiKey": ODDSPAPI_KEY, "sportId": 10, "from": date_from, "to": date_to},
                          timeout=20, verify=VERIFIER_SSL_ODDSPAPI)
        if r.status_code != 200:
            # Un statut non-200 ici (ex: 429 quota OddsPapi épuisé) fait échouer le lookup pour
            # TOUTES les jambes en attente, qui apparaissent alors "pas_termine" même si les
            # matchs sont réellement finis — un print discret ici évite de confondre "quota
            # épuisé" avec "le match n'est pas fini" (constaté le 2026-09-26).
            print(f"⚠️ OddsPapi /v4/fixtures a répondu {r.status_code} ({r.text[:150]}) — "
                  f"impossible de vérifier les résultats à ce passage.")
            return {}
        return {fx["fixtureId"]: fx for fx in r.json()}
    except Exception as e:
        print(f"⚠️ Impossible de récupérer les fixtures OddsPapi : {e}")
        return {}


def recuperer_score(fixture_id):
    try:
        r = requests.get("https://api.oddspapi.io/v4/scores",
                          params={"apiKey": ODDSPAPI_KEY, "fixtureId": fixture_id}, timeout=15, verify=VERIFIER_SSL_ODDSPAPI)
        if r.status_code != 200:
            return None
        periodes = r.json().get("scores", {}).get("periods", {})
        finale = periodes.get("fulltime") or periodes.get("result")
        if not finale:
            return None
        return finale.get("participant1Score"), finale.get("participant2Score")
    except Exception as e:
        print(f"⚠️ Erreur récupération score {fixture_id} : {e}")
        return None


def home_est_participant1(home_nom, p1_nom, p2_nom):
    h = unidecode(home_nom or "").lower()
    score_p1 = fuzz.token_set_ratio(h, unidecode(p1_nom or "").lower())
    score_p2 = fuzz.token_set_ratio(h, unidecode(p2_nom or "").lower())
    return score_p1 >= score_p2


# ============================================================
# REPLI API-FOOTBALL — quand OddsPapi est indisponible (quota journalier épuisé, 429, panne),
# retrouve le match PAR NOM D'ÉQUIPE (comme la collecte) au lieu du fixture_id OddsPapi, sur
# un quota totalement séparé. Constaté le 2026-09-26 : le quota OddsPapi (250 requêtes/jour)
# épuisé bloquait toute vérification de résultat, alors que les matchs étaient bel et bien
# terminés (confirmé via l'historique 1xBet de l'utilisateur).
# ============================================================

def recuperer_fixtures_api_football_du_jour():
    import collecte_donnees as cd
    try:
        return cd.recuperer_fixtures_api_football()
    except Exception as e:
        print(f"⚠️ Repli API-Football impossible : {e}")
        return []


def trouver_fixture_api_football(home_nom, away_nom, fixtures_af, cd):
    """Fuzzy-match par nom d'équipe (cd.score_paire_equipes, même seuil que la collecte) —
    le fixture API-Football le plus proche, ou None si aucun n'est fiable."""
    meilleur, meilleur_score = None, 0
    for fx in fixtures_af:
        equipes = fx.get("teams") or {}
        score = cd.score_paire_equipes(home_nom, away_nom,
                                        (equipes.get("home") or {}).get("name"),
                                        (equipes.get("away") or {}).get("name"))
        if score > meilleur_score:
            meilleur, meilleur_score = fx, score
    return meilleur if meilleur and meilleur_score >= cd.SEUIL_MATCH_ACCEPTABLE else None


def trouver_score_api_football(home_nom, away_nom, fixtures_af, cd):
    """Renvoie (but_domicile, but_exterieur) — déjà dans le bon ordre — seulement si un match est
    trouvé ET terminé (statut 'FT' : temps réglementaire, pas de prolongation/tirs au but pour
    ces compétitions). None si aucun match fiable ou pas encore terminé."""
    meilleur = trouver_fixture_api_football(home_nom, away_nom, fixtures_af, cd)
    if not meilleur:
        return None
    if (meilleur.get("fixture") or {}).get("status", {}).get("short") != "FT":
        return None
    buts = meilleur.get("goals") or {}
    if buts.get("home") is None or buts.get("away") is None:
        return None
    return buts["home"], buts["away"]


def recuperer_statistiques_finales_api_football(fixture_id_af, domicile):
    """Stats finales (corners, cartons jaunes, fautes, tirs, hors-jeux) d'un match TERMINÉ —
    seule source disponible pour ces marchés, OddsPapi /v4/scores ne renvoie que les buts.
    Renvoie (bloc_stats_domicile, bloc_stats_exterieur), chacun à passer à cd._valeur_stat
    pour extraire une statistique précise. None si indisponible (quota API-Football épuisé,
    panne, statistiques pas suivies pour ce match/cette ligue) — jamais inventé."""
    import collecte_donnees as cd
    try:
        blocs = cd._appel_statistiques_fixture(fixture_id_af)
    except Exception as e:
        print(f"⚠️ Stats finales API-Football indisponibles (fixture {fixture_id_af}) : {e}")
        return None
    if len(blocs) != 2:
        return None
    b0, b1 = blocs
    nom0 = unidecode(((b0.get("team") or {}).get("name") or "").lower())
    nom1 = unidecode(((b1.get("team") or {}).get("name") or "").lower())
    d = unidecode((domicile or "").lower())
    score0, score1 = fuzz.token_set_ratio(d, nom0), fuzz.token_set_ratio(d, nom1)
    bloc_dom, bloc_ext = (b0, b1) if score0 >= score1 else (b1, b0)
    return bloc_dom.get("statistics"), bloc_ext.get("statistics")


def grader_pick_stat(categorie, handicap, selection, valeur_domicile, valeur_exterieur):
    """Jugement des marchés corners/cartons/fautes/tirs/hors-jeux — mêmes règles que
    grader_pick (juger_total/juger_handicap), mais sur une statistique de fin de match
    (recuperer_statistiques_finales_api_football) au lieu des buts. None si la statistique
    est indisponible pour ce match (pas suivie par API-Football pour cette ligue — jamais
    inventée)."""
    if valeur_domicile is None or valeur_exterieur is None:
        return None
    if categorie in ("Total Cartons Équipe 1", "Total Cartons Équipe 2"):
        valeur = valeur_domicile if categorie.endswith("1") else valeur_exterieur
        return juger_total(handicap, selection, valeur)
    if categorie.startswith("Total"):
        return juger_total(handicap, selection, valeur_domicile + valeur_exterieur)
    if categorie.startswith("Handicap"):
        return juger_handicap(handicap, selection, valeur_domicile, valeur_exterieur) if handicap is not None else None
    return None


def trouver_etat_live_api_football(home_nom, away_nom, fixtures_af, cd):
    """Comme trouver_score_api_football, mais pour un match EN COURS (ni pas commencé, ni
    terminé) : renvoie (but_domicile, but_exterieur, minute_ecoulee, statut_court) si le match
    est trouvé ET en direct (voir STATUTS_EN_DIRECT), sinon None. minute_ecoulee peut être None
    (mi-temps, interruption...) — ne JUGE RIEN de définitif : un appelant peut évaluer "si ça
    finissait maintenant" (grader_pick) à titre INFORMATIF, jamais persisté comme résultat
    final tant que le match n'est pas réellement terminé."""
    meilleur, meilleur_score = None, 0
    for fx in fixtures_af:
        equipes = fx.get("teams") or {}
        score = cd.score_paire_equipes(home_nom, away_nom,
                                        (equipes.get("home") or {}).get("name"),
                                        (equipes.get("away") or {}).get("name"))
        if score > meilleur_score:
            meilleur, meilleur_score = fx, score
    if not meilleur or meilleur_score < cd.SEUIL_MATCH_ACCEPTABLE:
        return None
    statut = (meilleur.get("fixture") or {}).get("status") or {}
    court = statut.get("short")
    if court not in STATUTS_EN_DIRECT:
        return None
    buts = meilleur.get("goals") or {}
    if buts.get("home") is None or buts.get("away") is None:
        return None
    return buts["home"], buts["away"], statut.get("elapsed"), court


# ============================================================
# JUGEMENT DE CHAQUE JAMBE — même logique que evaluer_marches, mais appliquée
# au score réel final plutôt qu'à une probabilité Poisson.
# ============================================================

def juger_total(handicap, selection, total):
    """total déjà calculé par l'appelant (buts du match entier, d'UNE SEULE équipe, ou toute
    autre statistique comparable — corners, cartons... voir grader_pick_stat) — générique
    depuis le 03/10/2026, pour être réutilisable au-delà des buts."""
    if handicap is None or total is None:
        return None
    if abs(total - handicap) < 1e-9:
        return "push"
    est_over = "over" in selection.lower()
    gagne = (total > handicap) if est_over else (total < handicap)
    return "gagne" if gagne else "perdu"


def juger_btts(selection, home_g, away_g):
    sel = selection.lower()
    both = home_g > 0 and away_g > 0
    oui = sel in ("yes", "oui")
    return "gagne" if both == oui else "perdu"


def juger_double_chance(selection, home_g, away_g):
    sel_norm = re.sub(r"[^a-z0-9]", "", selection.lower())
    if sel_norm == "1x":
        return "gagne" if home_g >= away_g else "perdu"
    if sel_norm in ("x2", "2x"):
        return "gagne" if away_g >= home_g else "perdu"
    return None


def juger_draw_no_bet(selection, home_g, away_g):
    if home_g == away_g:
        return "push"
    sel = selection.lower()
    home_pick = sel in ("home", "1")
    home_win = home_g > away_g
    return "gagne" if home_win == home_pick else "perdu"


def juger_handicap(handicap, selection, home_g, away_g):
    """Reproduit exactement la convention de proba_handicap_couvert : pour 'home', la marge
    est (buts domicile - buts extérieur) + handicap ; pour 'away', c'est l'inverse avec le
    handicap opposé — voir evaluer_marches et expliquer_marche dans analyser_et_envoyer.py."""
    sel = selection.lower()
    if sel in ("home", "1"):
        marge = (home_g - away_g) + handicap
    elif sel in ("away", "2"):
        marge = (away_g - home_g) - handicap
    else:
        return None
    if abs(marge) < 1e-9:
        return "push"
    return "gagne" if marge > 0 else "perdu"


def juger_pair_impair(selection, home_g, away_g):
    total = home_g + away_g
    sel = selection.lower()
    pair = (total % 2 == 0)
    if sel == "odd":
        return "gagne" if not pair else "perdu"
    if sel == "even":
        return "gagne" if pair else "perdu"
    return None


def juger_clean_sheet(categorie, selection, home_g, away_g):
    est_equipe1 = categorie.endswith("1")
    adverse_g = away_g if est_equipe1 else home_g
    oui = selection.lower() in ("yes", "oui")
    clean = (adverse_g == 0)
    return "gagne" if clean == oui else "perdu"


def juger_win_to_nil(categorie, selection, home_g, away_g):
    est_equipe1 = categorie.endswith("1")
    if est_equipe1:
        wtn = away_g == 0 and home_g > 0
    else:
        wtn = home_g == 0 and away_g > 0
    oui = selection.lower() in ("yes", "oui")
    return "gagne" if wtn == oui else "perdu"


def grader_pick(pick, home_g, away_g):
    categorie = pick["categorie"]
    selection = pick["selection"]
    handicap = pick.get("handicap")

    if categorie in ("Total", "Total Équipe 1", "Total Équipe 2"):
        total = {"Total": home_g + away_g, "Total Équipe 1": home_g, "Total Équipe 2": away_g}[categorie]
        return juger_total(handicap, selection, total)
    if categorie in STAT_API_FOOTBALL_PAR_CATEGORIE:
        # Corners/cartons/fautes/tirs/hors-jeux : jugés par grader_pick_stat (statistiques
        # finales API-Football), jamais ici (grader_pick ne reçoit que des buts).
        return None
    if categorie == "BTTS":
        return juger_btts(selection, home_g, away_g)
    if categorie == "Double Chance":
        return juger_double_chance(selection, home_g, away_g)
    if categorie == "Draw No Bet":
        return juger_draw_no_bet(selection, home_g, away_g)
    if categorie in ("Handicap", "Handicap Européen", "Handicap Asiatique"):
        # "Handicap" : lignes entières/demi du marché OddsPapi "Asian Handicap" (onglet
        # "Handicap" sur 1xBet, voir analyser_et_envoyer._evaluer_marches_brut, 01/10/2026).
        # "Handicap Asiatique"/"Handicap Européen" : compatibilité avec les tickets persistés
        # avant ce renommage — même logique de jugement dans tous les cas.
        return juger_handicap(handicap, selection, home_g, away_g) if handicap is not None else None
    if categorie == "Pair/Impair":
        return juger_pair_impair(selection, home_g, away_g)
    if categorie in ("Clean Sheet Équipe 1", "Clean Sheet Équipe 2"):
        return juger_clean_sheet(categorie, selection, home_g, away_g)
    if categorie in ("Win To Nil Équipe 1", "Win To Nil Équipe 2"):
        return juger_win_to_nil(categorie, selection, home_g, away_g)
    return None

