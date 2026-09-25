"""
Reprend le pipeline là où collecte_donnees.py s'est arrêté : lit donnees_collectees.json,
calcule xG + probabilités Poisson + edge réel sur TOUS les marchés bruts collectés
(vocabulaire 1xbet, pas simplifié), fait rédiger le ticket par un LLM (cascade
Groq -> Gemini -> OpenRouter), puis envoie sur Telegram.

Ne retraite QUE les matchs pour lesquels collecte_donnees.py a trouvé des marchés
(les matchs déjà live/sans marché sont ignorés).

INTERDICTION : toute sélection "12" (double chance domicile-ou-extérieur) est bannie,
comme convenu. Le marché 1X2 n'existe de toute façon plus dans les données collectées.
"""

import os
import re
import json
import math
import time
import random
import requests
import urllib3

# Voir collecte_donnees.py pour le détail : OddsPapi est intercepté par un boîtier réseau
# (Fortinet) qui re-signe son certificat avec une CA non reconnue — désactivé uniquement
# pour ce domaine précis (déjà intercepté de toute façon), jamais pour Telegram/Groq/Gemini.
from datetime import datetime, timedelta
from dotenv import load_dotenv
from unidecode import unidecode
from tenacity import retry, stop_after_attempt, wait_fixed

load_dotenv("envi.local")

# Vérification du certificat OddsPapi : ACTIVE par défaut (GitHub Actions, serveur, PC).
# ODDSPAPI_SSL_NON_VERIFIE=true seulement sur un réseau qui intercepte le certificat (boîtier
# Fortinet constaté sur l'ancien environnement Termux) — jamais pour les autres APIs.
VERIFIER_SSL_ODDSPAPI = os.getenv("ODDSPAPI_SSL_NON_VERIFIE", "").lower() not in ("1", "true", "oui")
if not VERIFIER_SSL_ODDSPAPI:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ENTREE_JSON = "donnees_collectees.json"
TICKET_DU_JOUR_JSON = "ticket_du_jour.json"
SEUIL_EDGE = 5.0  # % — n'accepte un marché que si l'edge calculé dépasse ce seuil
EDGE_MAX_PLAUSIBLE = 25.0  # % — resserré de 60 à 25 : même un vrai edge dépasse rarement ce niveau
                            # de façon fiable sur un bookmaker professionnel comme 1xbet
PROBA_MIN_FORTE = 60.0  # % — un marché n'est retenu que si le modèle lui donne AU MOINS
                         # cette probabilité de gagner (pas seulement un edge positif) : objectif
                         # "coupon smart" avec des jambes individuellement fortes, pas juste
                         # statistiquement avantageuses sur le papier

# 3 coupons à 8 jambes chacun, composés sur LA MÊME collecte de données et le MÊME pool de
# candidats (un seul appel à collecter_donnees, un seul calcul Agent 3 par match) — ce qui
# change entre les 3, c'est UNIQUEMENT la fourchette de cote totale visée, obtenue en
# choisissant quelles jambes du pool combiner (pas 3 calculs différents du même chiffre).
EDGE_MIN_POOL = 2.0    # % — plancher d'edge pour qu'un marché entre dans le pool de candidats
# Volontairement bas (pas 50%+) : constaté en pratique (2026-07-24 et 25) que le COUPON 3
# (cible cote 50-100) ratait systématiquement sa cible faute de jambes à cote suffisamment
# haute dans le pool — un plancher de proba trop strict exclut justement les paris plus
# risqués (cote plus haute) dont ce profil a besoin. La recherche de combinaison
# (selectionner_combo_cote_cible) privilégie de toute façon la probabilité la plus forte
# PARMI les combos qui atteignent la cible — les Coupons 1/2 (cibles basses) n'utiliseront
# ces jambes plus risquées que si nécessaire pour respecter leur propre cible.
PROBA_MIN_POOL = 30.0  # % — plancher de probabilité pour qu'un marché entre dans le pool de candidats
NB_CANDIDATS_PAR_MATCH = 10  # plafond de sécurité — en pratique = le meilleur candidat de chaque catégorie de marché trouvée pour le match (~13 catégories possibles au total)

PROFILS_COUPON = [
    {"cle": "profil1", "nom": "🛡️ COUPON 1 (cote 5–10)", "cote_min": 5.0, "cote_max": 10.0, "nb_jambes": 8},
    {"cle": "profil2", "nom": "⚖️ COUPON 2 (cote 10–50)", "cote_min": 10.0, "cote_max": 50.0, "nb_jambes": 8},
    {"cle": "profil3", "nom": "🔥 COUPON 3 (cote 50–100)", "cote_min": 50.0, "cote_max": 100.0, "nb_jambes": 8},
]
SELECTION_INTERDITE = "12"  # double chance domicile-ou-extérieur, bannie par consigne

OPENROUTER_MODELS = ["openrouter/free", "cohere/north-mini-code:free", "poolside/laguna-xs-2.1:free"]


# ============================================================
# EXPECTED GOALS — reconstruits en pur Python depuis les cotes déjà collectées,
# aucun appel API supplémentaire (Understat/API-Football ne sont plus utilisés ici)
# ============================================================

def calculer_xg_depuis_stats(stats_home, stats_away):
    """Calcule mu_home/mu_away à partir des vraies stats historiques (buts marqués/encaissés,
    domicile/extérieur), quand les deux équipes en disposent. Méthode standard :
    mu_home = moyenne(buts marqués à domicile par l'équipe domicile, buts encaissés à
    l'extérieur par l'équipe extérieure) — et symétriquement pour mu_away."""
    if not stats_home or not stats_away:
        return None
    bm_dom = stats_home.get("buts_marques_domicile")
    be_dom = stats_home.get("buts_encaisses_domicile")
    bm_ext = stats_away.get("buts_marques_exterieur")
    be_ext = stats_away.get("buts_encaisses_exterieur")
    if None in (bm_dom, be_dom, bm_ext, be_ext):
        return None
    try:
        mu_home = (float(bm_dom) + float(be_ext)) / 2
        mu_away = (float(bm_ext) + float(be_dom)) / 2
    except (TypeError, ValueError):
        return None
    return round(max(0.15, mu_home), 2), round(max(0.15, mu_away), 2)


NB_MATCHS_MIN_UNDERSTAT = 3  # en début de saison, sous ce seuil la moyenne xG est trop bruitée


def calculer_xg_depuis_understat(us_home, us_away):
    """Buts attendus depuis les xG/xGA Understat de la SAISON EN COURS (5 grands championnats
    uniquement). Prioritaire sur les stats API-Football, qui sur le plan gratuit ne donnent
    que la saison 2024 (deux saisons de retard, et rien pour les promus). Même méthode que
    calculer_xg_depuis_stats : mu_home = moyenne(xG de l'équipe domicile, xGA de l'équipe
    extérieure), et symétriquement. Understat ne sépare pas domicile/extérieur."""
    if not us_home or not us_away:
        return None
    if min(us_home.get("matchs_joues") or 0, us_away.get("matchs_joues") or 0) < NB_MATCHS_MIN_UNDERSTAT:
        return None
    try:
        mu_home = (float(us_home["xg_moyen_par_match"]) + float(us_away["xga_moyen_par_match"])) / 2
        mu_away = (float(us_away["xg_moyen_par_match"]) + float(us_home["xga_moyen_par_match"])) / 2
    except (KeyError, TypeError, ValueError):
        return None
    return round(max(0.15, mu_home), 2), round(max(0.15, mu_away), 2)


def _est_ligne_quart(x):
    r = x * 4
    return abs(r - round(r)) < 1e-6 and (round(r) % 2 != 0)


def estimer_ligne_equilibree(marches, mots_cles_categorie, exclure_team=True):
    """Cherche, parmi les marchés Total correspondant à une catégorie donnée (buts/corners/
    cartons — identifiée par mots-clés dans le nom du marché), la ligne dont les cotes
    Plus de/Moins de sont les plus proches l'une de l'autre (donc la plus 'juste' selon le
    marché). Retourne cette ligne (l'estimation de la valeur moyenne attendue), ou None si
    rien trouvé. Réutilisée pour buts, corners et cartons — même logique, catégorie différente."""
    meilleure_ligne, meilleur_ecart = None, float("inf")
    for m in marches:
        nom = (m.get("marche") or "").lower()
        if not any(mc in nom for mc in mots_cles_categorie):
            continue
        if exclure_team and ("team 1" in nom or "team 2" in nom or "team1" in nom or "team2" in nom):
            continue
        selections_m = m.get("selections", [])
        a_over = any("over" in s["selection"].lower() for s in selections_m)
        a_under = any("under" in s["selection"].lower() for s in selections_m)
        if not (a_over and a_under):
            continue
        handicap = m.get("handicap")
        if handicap is None:
            continue
        cote_over = next((s["cote"] for s in m["selections"] if "over" in s["selection"].lower()), None)
        cote_under = next((s["cote"] for s in m["selections"] if "under" in s["selection"].lower()), None)
        if cote_over and cote_under:
            ecart = abs(cote_over - cote_under)
            if ecart < meilleur_ecart:
                meilleur_ecart, meilleure_ligne = ecart, handicap
    return meilleure_ligne


def estimer_expected_goals_depuis_marches(marches):
    """
    Reconstruit mu_home/mu_away sans aucune API externe :
    - la ligne 'Total' la plus équilibrée (cotes Over/Under les plus proches) donne
      l'estimation du nombre de buts total attendu (mu_total) — c'est la ligne que
      le marché considère comme la plus proche de 50/50, donc la plus proche de la
      vraie espérance.
    - la ligne 'Handicap Asiatique' la plus équilibrée donne l'écart de force attendu
      entre les deux équipes (mu_diff).
    mu_home et mu_away sont ensuite dérivés de mu_total et mu_diff.
    """
    meilleur_total_line, meilleur_ecart_total = None, float("inf")
    for m in marches:
        nom = (m.get("marche") or "").lower()
        # IMPORTANT : exclure les totaux par équipe (Team 1/Team 2), sinon on confond
        # le total d'UNE équipe avec le total du MATCH complet — bug qui a produit
        # des xG absurdes (0.15) et des edges à 400%+ lors du premier essai.
        if "team 1" in nom or "team 2" in nom or "team1" in nom or "team2" in nom:
            continue
        # IMPORTANT : exclure les marchés Corners/Cartons — ce sont des statistiques
        # différentes des buts, les mélanger fausserait complètement l'estimation.
        if "corner" in nom or "card" in nom or "booking" in nom:
            continue
        cote_over = next((s["cote"] for s in m["selections"] if "over" in s["selection"].lower()), None)
        cote_under = next((s["cote"] for s in m["selections"] if "under" in s["selection"].lower()), None)
        if cote_over and cote_under:
            handicap = m.get("handicap")
            if handicap is None:
                continue
            ecart = abs(cote_over - cote_under)
            if ecart < meilleur_ecart_total:
                meilleur_ecart_total, meilleur_total_line = ecart, handicap

    mu_total = meilleur_total_line if meilleur_total_line is not None else 2.5
    # Garde-fou : une ligne de match plausible se situe presque toujours entre 0.5 et 6.5 buts.
    # En dehors, c'est le signe qu'une mauvaise ligne a été captée — on retombe sur 2.5 (neutre).
    if not (0.5 <= mu_total <= 6.5):
        mu_total = 2.5

    meilleur_hcp, meilleur_ecart_hcp = None, float("inf")
    for m in marches:
        nom = (m.get("marche") or "").lower()
        if "corner" in nom or "card" in nom or "booking" in nom:
            continue
        if "handicap" in nom:
            handicap = m.get("handicap")
            if handicap is None:
                continue
            cote_home = next((s["cote"] for s in m["selections"]
                               if "home" in s["selection"].lower() or s["selection"] in ("1",)), None)
            cote_away = next((s["cote"] for s in m["selections"]
                               if "away" in s["selection"].lower() or s["selection"] in ("2",)), None)
            if cote_home and cote_away:
                ecart = abs(cote_home - cote_away)
                if ecart < meilleur_ecart_hcp:
                    meilleur_ecart_hcp, meilleur_hcp = ecart, handicap

    mu_diff = -meilleur_hcp if meilleur_hcp is not None else 0.0  # handicap négatif = domicile favori
    # Garde-fou physique : l'écart entre les deux équipes ne peut pas dépasser le total
    # (sinon on obtiendrait un xG négatif pour l'équipe la plus faible) — on plafonne à 90% du total.
    mu_diff = max(-mu_total * 0.9, min(mu_total * 0.9, mu_diff))

    mu_home = max(0.15, round((mu_total + mu_diff) / 2, 2))
    mu_away = max(0.15, round((mu_total - mu_diff) / 2, 2))
    return mu_home, mu_away, mu_total, (meilleur_total_line is not None), (meilleur_hcp is not None)


# ============================================================
# POISSON — probabilités de base
# ============================================================

def poisson_p(lmbda, k):
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def poisson_cdf(mu, k):
    return sum(poisson_p(mu, i) for i in range(k + 1))


def proba_1x2(mu_home, mu_away, max_buts=25):
    p_home = p_draw = p_away = 0.0
    for i in range(max_buts):
        for j in range(max_buts):
            p = poisson_p(mu_home, i) * poisson_p(mu_away, j)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def proba_over(ligne, mu_total, max_buts=25):
    """Probabilité de gagner un pari 'Plus de' à la ligne donnée. Gère les lignes quart
    (.25/.75) de la même façon que proba_handicap_couvert : ce sont deux demi-mises sur
    des lignes adjacentes, avec push (remboursement) possible sur la moitié entière —
    pas un simple 'plus/moins' binaire (même bug que celui corrigé sur le handicap)."""
    def gain_et_push(l):
        p_gain, p_push = 0.0, 0.0
        for k in range(max_buts):
            p = poisson_p(mu_total, k)
            if k > l:
                p_gain += p
            elif abs(k - l) < 1e-9:
                p_push += p
        return p_gain, p_push

    r = ligne * 4
    est_ligne_quart = abs(r - round(r)) < 1e-6 and (round(r) % 2 != 0)
    if not est_ligne_quart:
        p_gain, p_push = gain_et_push(ligne)
        return p_gain + p_push * 0.5

    p_gain_bas, p_push_bas = gain_et_push(ligne - 0.25)
    p_gain_haut, p_push_haut = gain_et_push(ligne + 0.25)
    proba_bas = p_gain_bas + p_push_bas * 0.5
    proba_haut = p_gain_haut + p_push_haut * 0.5
    return (proba_bas + proba_haut) / 2


def proba_btts(mu_home, mu_away):
    p_home_0 = poisson_p(mu_home, 0)
    p_away_0 = poisson_p(mu_away, 0)
    return 1 - p_home_0 - p_away_0 + (p_home_0 * p_away_0)


def proba_total_impair(mu, max_buts=25):
    return sum(poisson_p(mu, k) for k in range(1, max_buts, 2))


def proba_clean_sheet(mu_adverse):
    """Probabilité qu'une équipe garde sa cage inviolée = probabilité que l'ADVERSAIRE marque 0."""
    return poisson_p(mu_adverse, 0)


def proba_win_to_nil(mu_equipe, mu_adverse):
    """Probabilité qu'une équipe gagne SANS encaisser : l'adversaire marque 0 ET l'équipe marque >=1."""
    return poisson_p(mu_adverse, 0) * (1 - poisson_p(mu_equipe, 0))


def _gain_et_push_sur_ligne_demie(mu_home, mu_away, h, max_buts=25):
    """Pour une ligne handicap qui est un multiple de 0.5 (pas de quart), calcule
    (probabilité de gain plein, probabilité de push/remboursement)."""
    p_gain, p_push = 0.0, 0.0
    for i in range(max_buts):
        for j in range(max_buts):
            marge = (i - j) + h
            p = poisson_p(mu_home, i) * poisson_p(mu_away, j)
            if marge > 0:
                p_gain += p
            elif abs(marge) < 1e-9:
                p_push += p
    return p_gain, p_push


def proba_handicap_couvert(mu_home, mu_away, handicap_home, max_buts=25):
    """Probabilité de gain sur un handicap asiatique donné pour 'home'.
    Gère correctement les lignes quart (.25/.75) : en réalité, ce sont DEUX demi-mises
    sur deux lignes adjacentes (ex: 1.25 = moitié sur 1.0, moitié sur 1.5), avec un
    remboursement partiel (push) possible sur la moitié entière/demie — ce n'est PAS
    un simple 'gagne ou perd' comme le calcul précédent le supposait à tort (ce qui
    gonflait artificiellement l'edge calculé sur ces lignes)."""
    r = handicap_home * 4
    est_ligne_quart = abs(r - round(r)) < 1e-6 and (round(r) % 2 != 0)

    if not est_ligne_quart:
        p_gain, p_push = _gain_et_push_sur_ligne_demie(mu_home, mu_away, handicap_home, max_buts)
        # Sur une ligne pleine, un push rembourse la mise (ni gain ni perte) — pour comparer
        # équitablement à une cote décimale classique, on traite un push comme un gain neutre
        # à 0 profit : proba effective de "ne pas perdre" utilisée pour l'edge.
        return p_gain + p_push * 0.5  # approximation standard : la moitié "neutre" d'un push

    h_bas = handicap_home - 0.25
    h_haut = handicap_home + 0.25
    p_gain_bas, p_push_bas = _gain_et_push_sur_ligne_demie(mu_home, mu_away, h_bas, max_buts)
    p_gain_haut, p_push_haut = _gain_et_push_sur_ligne_demie(mu_home, mu_away, h_haut, max_buts)
    # Moyenne des deux moitiés de mise, chaque push comptant comme un demi-gain neutre
    proba_bas = p_gain_bas + p_push_bas * 0.5
    proba_haut = p_gain_haut + p_push_haut * 0.5
    return (proba_bas + proba_haut) / 2


def calc_edge(proba_modele, cote):
    if not cote or cote <= 1:
        return None
    proba_implicite = 1 / cote
    return (proba_modele - proba_implicite) / proba_implicite * 100


# ============================================================
# ÉVALUATION DE CHAQUE MARCHÉ BRUT (vocabulaire 1xbet, pas simplifié)
# ============================================================

def candidat_valide(edge, proba):
    """Un marché n'est retenu que s'il a À LA FOIS un edge plausible ET une probabilité
    de gain forte (PROBA_MIN_FORTE) — un edge élevé sur un pari à 30% de chances de gagner
    n'est pas un pari 'smart' pour un coupon combiné, même s'il est mathématiquement +EV."""
    return bool(edge) and SEUIL_EDGE < edge <= EDGE_MAX_PLAUSIBLE and proba * 100 >= PROBA_MIN_FORTE


def evaluer_marches(marches, mu_home, mu_away, mu_corners=None, mu_cartons=None):
    """Parcourt tous les marchés bruts collectés et calcule un edge réel pour ceux
    qu'on sait modéliser (Total buts/corners/cartons, BTTS, Handicap Asiatique,
    Double Chance, Draw No Bet). mu_corners/mu_cartons sont optionnels — si absents,
    les marchés Corners/Cartons sont simplement ignorés (pas de donnée = pas de pari).

    Les lignes 'quart' (.25/.75) sont exclues de la sélection finale : vérifié en pratique
    que ces lignes n'existent pas toujours comme option cliquable réelle sur 1xbet, même
    quand OddsPapi les renvoie. Elles restent utilisées ailleurs (estimer_expected_goals_
    depuis_marches) uniquement pour ESTIMER mu, jamais pour être proposées comme pari."""
    p_home, p_draw, p_away = proba_1x2(mu_home, mu_away)
    mu_total_buts = mu_home + mu_away
    candidats = []

    for marche in marches:
        nom = (marche.get("marche") or "").lower()
        handicap = marche.get("handicap")
        selections = marche.get("selections", [])

        # --- Total (Over/Under) — buts (match/équipe1/équipe2), corners, ou cartons ---
        _a_over = any("over" in s["selection"].lower() for s in selections)
        _a_under = any("under" in s["selection"].lower() for s in selections)
        if _a_over and _a_under:
            if handicap is None:
                continue
            if _est_ligne_quart(handicap):
                continue  # ligne .25/.75 non fiable comme option réelle sur 1xbet

            est_team1 = "team 1" in nom or "team1" in nom
            est_team2 = "team 2" in nom or "team2" in nom
            est_corner = "corner" in nom
            est_carton = "card" in nom or "booking" in nom

            if (est_corner or est_carton) and (est_team1 or est_team2):
                # Marché "Total Corners/Cards Team 1/2" : seule la ligne globale du
                # match est estimée (mu_corners/mu_cartons), aucun mu par équipe
                # n'est calculé — on n'invente pas ce chiffre, on ignore ce marché
                # plutôt que de l'évaluer à tort contre le total du match entier
                # (c'est exactement la confusion Team1/Team2-vs-total interdite).
                continue
            elif est_corner:
                if mu_corners is None:
                    continue  # pas de donnée corners pour ce match, on ignore ce marché
                mu_cible = mu_corners
                categorie = "Total Corners"
            elif est_carton:
                if mu_cartons is None:
                    continue
                mu_cible = mu_cartons
                categorie = "Total Cartons"
            elif est_team1:
                mu_cible = mu_home  # total de buts de l'équipe domicile SEULE
                categorie = "Total Équipe 1"
            elif est_team2:
                mu_cible = mu_away  # total de buts de l'équipe extérieure SEULE
                categorie = "Total Équipe 2"
            else:
                mu_cible = mu_total_buts  # total de buts du match (les deux équipes)
                categorie = "Total"

            proba_over_calc = proba_over(handicap, mu_cible)
            for s in selections:
                sel = s["selection"].lower()
                if "over" in sel:
                    edge = calc_edge(proba_over_calc, s["cote"])
                    if candidat_valide(edge, proba_over_calc):
                        candidats.append(_candidat(marche["marche"], handicap, s, proba_over_calc, edge, categorie))
                elif "under" in sel:
                    edge = calc_edge(1 - proba_over_calc, s["cote"])
                    if candidat_valide(edge, 1 - proba_over_calc):
                        candidats.append(_candidat(marche["marche"], handicap, s, 1 - proba_over_calc, edge, categorie))

        # --- Both Teams To Score ---
        elif "both teams to score" in nom or "btts" in nom:
            p_yes = proba_btts(mu_home, mu_away)
            for s in selections:
                sel = s["selection"].lower()
                if "yes" in sel or sel == "oui":
                    edge = calc_edge(p_yes, s["cote"])
                    if candidat_valide(edge, p_yes):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_yes, edge, "BTTS"))
                elif "no" in sel or sel == "non":
                    edge = calc_edge(1 - p_yes, s["cote"])
                    if candidat_valide(edge, 1 - p_yes):
                        candidats.append(_candidat(marche["marche"], handicap, s, 1 - p_yes, edge, "BTTS"))

        # --- Double Chance (12 banni) ---
        elif "double chance" in nom:
            for s in selections:
                sel_brut = s["selection"]
                sel_norm = re.sub(r"[^a-z0-9]", "", sel_brut.lower())
                if sel_norm in ("12",):
                    continue  # INTERDIT — jamais cette sélection, quel que soit l'edge
                if sel_norm in ("1x",):
                    proba = p_home + p_draw
                elif sel_norm in ("x2", "2x"):
                    proba = p_draw + p_away
                else:
                    continue
                edge = calc_edge(proba, s["cote"])
                if candidat_valide(edge, proba):
                    candidats.append(_candidat(marche["marche"], handicap, s, proba, edge, "Double Chance"))

        # --- Draw No Bet ---
        elif "draw no bet" in nom:
            total_sans_nul = p_home + p_away
            if total_sans_nul <= 0:
                continue
            p_home_dnb = p_home / total_sans_nul
            p_away_dnb = p_away / total_sans_nul
            for s in selections:
                sel = s["selection"].lower()
                if "home" in sel or sel == "1":
                    edge = calc_edge(p_home_dnb, s["cote"])
                    if candidat_valide(edge, p_home_dnb):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_home_dnb, edge, "Draw No Bet"))
                elif "away" in sel or sel == "2":
                    edge = calc_edge(p_away_dnb, s["cote"])
                    if candidat_valide(edge, p_away_dnb):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_away_dnb, edge, "Draw No Bet"))

        # --- Asian Handicap ---
        elif "asian handicap" in nom and "corner" not in nom and "card" not in nom and "booking" not in nom:
            if handicap is None:
                continue
            if _est_ligne_quart(handicap):
                continue  # ligne .25/.75 non fiable comme option réelle sur 1xbet
            for s in selections:
                sel = s["selection"].lower()
                if "home" in sel or sel == "1":
                    proba = proba_handicap_couvert(mu_home, mu_away, handicap)
                elif "away" in sel or sel == "2":
                    proba = proba_handicap_couvert(mu_away, mu_home, -handicap)
                else:
                    continue
                edge = calc_edge(proba, s["cote"])
                if candidat_valide(edge, proba):
                    candidats.append(_candidat(marche["marche"], handicap, s, proba, edge, "Handicap Asiatique"))

        # --- Odd/Even (Pair/Impair) — nombre total de buts du match ---
        elif "odd even" in nom and "team" not in nom:
            p_impair = proba_total_impair(mu_total_buts)
            p_pair = 1 - p_impair
            for s in selections:
                sel = s["selection"].lower()
                if sel == "odd":
                    edge = calc_edge(p_impair, s["cote"])
                    if candidat_valide(edge, p_impair):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_impair, edge, "Pair/Impair"))
                elif sel == "even":
                    edge = calc_edge(p_pair, s["cote"])
                    if candidat_valide(edge, p_pair):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_pair, edge, "Pair/Impair"))

        # --- Clean Sheet — l'équipe ne prend aucun but ---
        elif "clean sheet" in nom:
            est_team1 = "team 1" in nom or "team1" in nom
            mu_adverse = mu_away if est_team1 else mu_home
            p_clean = proba_clean_sheet(mu_adverse)
            categorie = f"Clean Sheet Équipe {1 if est_team1 else 2}"
            for s in selections:
                sel = s["selection"].lower()
                if sel in ("yes", "oui"):
                    edge = calc_edge(p_clean, s["cote"])
                    if candidat_valide(edge, p_clean):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_clean, edge, categorie))
                elif sel in ("no", "non"):
                    edge = calc_edge(1 - p_clean, s["cote"])
                    if candidat_valide(edge, 1 - p_clean):
                        candidats.append(_candidat(marche["marche"], handicap, s, 1 - p_clean, edge, categorie))

        # --- Win To Nil — l'équipe gagne SANS encaisser ---
        elif "win to nil" in nom:
            est_team1 = "team 1" in nom or "team1" in nom
            if est_team1:
                p_wtn = proba_win_to_nil(mu_home, mu_away)
            else:
                p_wtn = proba_win_to_nil(mu_away, mu_home)
            categorie = f"Win To Nil Équipe {1 if est_team1 else 2}"
            for s in selections:
                sel = s["selection"].lower()
                if sel in ("yes", "oui"):
                    edge = calc_edge(p_wtn, s["cote"])
                    if candidat_valide(edge, p_wtn):
                        candidats.append(_candidat(marche["marche"], handicap, s, p_wtn, edge, categorie))
                elif sel in ("no", "non"):
                    edge = calc_edge(1 - p_wtn, s["cote"])
                    if candidat_valide(edge, 1 - p_wtn):
                        candidats.append(_candidat(marche["marche"], handicap, s, 1 - p_wtn, edge, categorie))

    # Tri par PROBABILITÉ d'abord (pas par edge) : objectif coupon combiné à forte
    # probabilité de gagner — parmi TOUS les marchés qui signalent une opportunité
    # valable (edge + proba déjà filtrés par candidat_valide), on privilégie celui
    # dont le modèle est le plus confiant, l'edge ne sert qu'à départager les égalités.
    return sorted(candidats, key=lambda c: (c["proba_modele_pct"], c["edge_pct"]), reverse=True)


def expliquer_marche(categorie, selection_brute, handicap):
    """Traduit une catégorie déjà connue avec certitude (calculée plus haut par le code,
    JAMAIS devinée depuis le texte brut du marché) en un guide pédagogique + l'onglet 1xbet
    correspondant. Fait exprès de bien SÉPARER 'Total' (match entier) de 'Total Équipe 1/2'
    (une seule équipe) — c'est la confusion que le LLM faisait en improvisant ce texte lui-même."""
    sel = (selection_brute or "").lower()

    if categorie in ("Total", "Total Équipe 1", "Total Équipe 2", "Total Corners", "Total Cartons"):
        sens = "inférieur" if "under" in sel else "supérieur"
        objet_par_categorie = {
            "Total": ("le nombre total de buts du match", "onglet Total (buts du match entier)"),
            "Total Équipe 1": ("le nombre de buts marqués par l'ÉQUIPE 1 (domicile) SEULE — pas le match entier",
                                "onglet Total équipe 1 / Total buts équipe domicile"),
            "Total Équipe 2": ("le nombre de buts marqués par l'ÉQUIPE 2 (extérieure) SEULE — pas le match entier",
                                "onglet Total équipe 2 / Total buts équipe extérieure"),
            "Total Corners": ("le nombre total de corners du match", "onglet Corners / Total corners"),
            "Total Cartons": ("le nombre total de cartons (jaunes + rouges) du match", "onglet Cartons / Total cartons"),
        }
        objet, onglet = objet_par_categorie[categorie]
        return f"{objet} doit être {sens} à {handicap}", onglet

    if categorie == "BTTS":
        oui = sel in ("yes", "oui")
        guide = ("les deux équipes doivent marquer au moins un but chacune" if oui
                 else "au moins une des deux équipes ne doit PAS marquer")
        return guide, "onglet Les deux équipes marquent (BTTS)"

    if categorie == "Double Chance":
        sel_norm = re.sub(r"[^a-z0-9]", "", sel)
        if sel_norm == "1x":
            guide = "le match doit se terminer par une victoire à domicile OU un match nul"
        elif sel_norm in ("x2", "2x"):
            guide = "le match doit se terminer par un match nul OU une victoire à l'extérieur"
        else:
            guide = f"double chance : {selection_brute}"
        return guide, "onglet Double Chance"

    if categorie == "Draw No Bet":
        cote_txt = "domicile" if sel in ("home", "1") else "extérieure"
        return (f"l'équipe {cote_txt} doit gagner (en cas de match nul, la mise est intégralement remboursée)",
                "onglet Nul remboursé (Draw No Bet)")

    if categorie == "Pair/Impair":
        if sel == "odd":
            return "le nombre total de buts du match doit être IMPAIR (1, 3, 5, ...)", "onglet Pair/Impair (Odd/Even)"
        return "le nombre total de buts du match doit être PAIR (0, 2, 4, ...)", "onglet Pair/Impair (Odd/Even)"

    if categorie in ("Clean Sheet Équipe 1", "Clean Sheet Équipe 2"):
        num = "1" if categorie.endswith("1") else "2"
        cote_txt = "domicile" if num == "1" else "extérieure"
        oui = sel in ("yes", "oui")
        guide = (f"l'équipe {num} ({cote_txt}) ne doit encaisser AUCUN but sur tout le match" if oui
                 else f"l'équipe {num} ({cote_txt}) doit encaisser au moins un but")
        return guide, f"onglet Clean Sheet équipe {num}"

    if categorie in ("Win To Nil Équipe 1", "Win To Nil Équipe 2"):
        num = "1" if categorie.endswith("1") else "2"
        cote_txt = "domicile" if num == "1" else "extérieure"
        oui = sel in ("yes", "oui")
        guide = (f"l'équipe {num} ({cote_txt}) doit GAGNER le match ET l'adversaire ne doit marquer aucun but"
                 if oui else
                 f"soit l'équipe {num} ({cote_txt}) ne gagne pas, soit l'adversaire marque au moins un but")
        return guide, f"onglet Win to Nil équipe {num}"

    if categorie == "Handicap Asiatique":
        if sel in ("home", "1"):
            cote_txt, h_effectif = "domicile", handicap
        elif sel in ("away", "2"):
            cote_txt, h_effectif = "extérieure", -handicap
        else:
            return f"handicap asiatique : {selection_brute}", "onglet Handicap Asiatique"
        if h_effectif >= 0:
            guide = f"l'équipe {cote_txt} part avec un avantage fictif de {h_effectif} but(s)"
        else:
            guide = f"l'équipe {cote_txt} part avec un désavantage fictif de {abs(h_effectif)} but(s)"
        return guide, "onglet Handicap Asiatique"

    return None, None


def _candidat(nom_marche, handicap, selection, proba, edge, categorie):
    # La ligne (handicap) est intégrée AU NOM du marché — pas laissée comme détail séparé
    # que le LLM pourrait oublier de reprendre dans le ticket final.
    nom_avec_ligne = f"{nom_marche} ({handicap})" if handicap is not None else nom_marche
    guide, onglet = expliquer_marche(categorie, selection["selection"], handicap)
    return {
        "categorie": categorie,
        "marche": nom_avec_ligne,
        "handicap": handicap,
        "selection": selection["selection"],
        "cote": selection["cote"],
        "proba_modele_pct": round(proba * 100, 1),
        "edge_pct": round(edge, 1),
        "guide": guide,
        "onglet": onglet,
    }


# ============================================================
# LLM — cascade Groq -> Gemini -> OpenRouter (rédaction uniquement)
# ============================================================

@retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
def _appel_groq_brut(prompt, max_tokens):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": prompt}], "max_tokens": min(max_tokens, 2000)}
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    data = r.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise ValueError(f"Groq contenu vide — {data}")
    return content.strip()


def appel_groq(prompt, max_tokens):
    if not GROQ_API_KEY:
        return None
    try:
        c = _appel_groq_brut(prompt, max_tokens)
        print("   ✓ Réponse via Groq")
        return c
    except Exception as e:
        print(f"   ⚠️ Groq échoué : {e}")
        return None


@retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
def _appel_gemini_brut(prompt, max_tokens):
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {"Authorization": f"Bearer {GEMINI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "gemini-2.5-flash-lite", "messages": [{"role": "user", "content": prompt}], "max_tokens": min(max_tokens, 4000)}
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    data = r.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise ValueError(f"Gemini contenu vide — {data}")
    return content.strip()


def appel_gemini(prompt, max_tokens):
    if not GEMINI_API_KEY:
        return None
    try:
        c = _appel_gemini_brut(prompt, max_tokens)
        print("   ✓ Réponse via Gemini")
        return c
    except Exception as e:
        print(f"   ⚠️ Gemini échoué : {e}")
        return None


def appel_openrouter(prompt, max_tokens=2000):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    for modele in OPENROUTER_MODELS:
        for tentative in range(2):
            try:
                payload = {"model": modele, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
                r = requests.post(url, headers=headers, json=payload, timeout=120)
                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    print(f"   ✓ Réponse via {modele}")
                    return content.strip()
            except Exception:
                pass
            time.sleep(3)
    raise ValueError("Tous les modèles OpenRouter ont échoué")


def appel_llm(prompt, max_tokens=3000):
    c = appel_groq(prompt, max_tokens)
    if c:
        return c
    c = appel_gemini(prompt, max_tokens)
    if c:
        return c
    print("   → Bascule sur OpenRouter...")
    return appel_openrouter(prompt, max_tokens)


def verifier_pas_de_12(texte):
    if re.search(r"(?<![\d.])12(?![\d.\w])", texte):
        return False
    return True


# ============================================================
# TELEGRAM
# ============================================================

def notifier_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("✅ Message Telegram envoyé !")
            return True
        if r.status_code == 400 and "can't parse entities" in r.text:
            # Le texte rédigé par le LLM contient un '_' ou '*' non fermé qui casse le
            # Markdown (constaté : profil 2/3 perdu pour "Can't find end of the entity") —
            # on renvoie le même message en texte brut plutôt que de le perdre.
            print(f"   ⚠️ Markdown rejeté par Telegram ({r.text[:120]}) — renvoi en texte brut...")
            payload.pop("parse_mode")
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                print("✅ Message Telegram envoyé (texte brut) !")
                return True
        print(f"❌ Erreur Telegram : {r.text}")
        return False
    except Exception as e:
        print(f"❌ Erreur connexion Telegram : {e}")
        return False


# ============================================================
# ARCHITECTURE — les 3 piliers (Données / Calcul / IA) se répartissent ainsi :
#   Agent 1 & 2 (pilier DONNÉES)   -> déjà faits par collecte_donnees.py, lus ici en entrée
#   Agent 3      (pilier CALCUL)   -> agent3_calcul_pool_candidats() + generer_trois_coupons()
#   Agent 4      (pilier IA)       -> agent4_ia_analyse_pronostic_redaction() — 3 tâches internes,
#                                      appelée une fois par profil via agent4_rediger_trois_coupons()
#   Agent 5      (livraison)       -> agent5_envoyer_trois_coupons()
# ============================================================

def _construire_donnees_prompt(selections_finales):
    donnees_prompt = ""
    for s in selections_finales:
        pick = s["pick"]
        donnees_prompt += (
            f"\n{s['match']} : marché \"{pick['marche']}\", sélection \"{pick['selection']}\" "
            f"@ {pick['cote']}, probabilité modèle {pick['proba_modele_pct']}%, "
            f"edge {pick['edge_pct']}%\n"
            f"  Guide déjà rédigé (à recopier tel quel) : {pick['guide']}\n"
            f"  Onglet déjà déterminé (à recopier tel quel) : {pick['onglet']}\n"
        )
    return donnees_prompt


CONSIGNES_COMMUNES_IA = (
    "RÈGLES ABSOLUES, valables pour toute la suite : n'invente et ne modifie JAMAIS un chiffre "
    "(cote, probabilité, edge, ligne) — recopie-les exactement tels que donnés. "
    "INTERDICTION ABSOLUE de la sélection '12' (double chance domicile-ou-extérieur). "
    "GARDE le nom du marché EXACTEMENT tel que donné, Y COMPRIS la ligne entre parenthèses "
    "(ex: 'Total (2)', 'Handicap Asiatique (0.75)') — c'est ce qui permet de retrouver la bonne "
    "case sur 1xbet, ne la retire ni ne la déplace jamais. Fais bien la différence entre un marché "
    "'Total' (buts/corners/cartons du MATCH ENTIER) et 'Total Équipe 1'/'Total Équipe 2' (UNE SEULE "
    "équipe) — ce sont deux paris différents, ne les confonds jamais et ne raccourcis jamais "
    "'Équipe 1'/'Équipe 2' en 'Full Time'. N'INVENTE JAMAIS le 'Guide' pédagogique ni l'onglet où "
    "parier : ils sont déjà rédigés et fournis avec chaque sélection ci-dessous, recopie-les MOT POUR "
    "MOT — ne les reformule pas, ne les résume pas, ne les remplace pas par ta propre explication."
)


def _tache_analyse(donnees_prompt, nb_matchs):
    """Tâche IA 1/3 — explique pourquoi chaque pick a un edge positif."""
    prompt = (
        f"System: Tu es un analyste sportif pédagogue. Réponds UNIQUEMENT en français.\n"
        f"{CONSIGNES_COMMUNES_IA}\n\n"
        f"Voici {nb_matchs} sélections déjà calculées par un modèle mathématique (Poisson) "
        f":\n{donnees_prompt}\n"
        f"Pour CHAQUE match, écris 1-2 phrases d'analyse en langage simple expliquant pourquoi cette "
        f"sélection a un edge positif (utilise le chiffre d'edge et de probabilité donnés). "
        f"Reste factuel, pas de jargon technique non expliqué. Format : une section par match, "
        f"commençant par le nom du match."
    )
    print("   🧠 [Tâche 1/3] Analyse des sélections...")
    return appel_llm(prompt, max_tokens=2000) or ""


def _tache_pronostic(donnees_prompt, analyse_texte):
    """Tâche IA 2/3 — confirme le choix final et note un niveau de confiance."""
    prompt = (
        f"System: Tu es un pronostiqueur rigoureux. Réponds UNIQUEMENT en français.\n"
        f"{CONSIGNES_COMMUNES_IA}\n\n"
        f"Voici les sélections avec leurs chiffres :\n{donnees_prompt}\n"
        f"Voici l'analyse déjà rédigée :\n{analyse_texte}\n\n"
        f"Pour CHAQUE match, confirme le pronostic final (reprends exactement le marché, la sélection "
        f"et la cote donnés) et ajoute un niveau de confiance simple : Faible / Moyen / Élevé, basé "
        f"sur l'edge (édge <10% = Faible, 10-20% = Moyen, >20% = Élevé). Une ligne par match : "
        f"'Match : Marché - Sélection @ Cote — Confiance : niveau'."
    )
    print("   🎯 [Tâche 2/3] Pronostic final...")
    return appel_llm(prompt, max_tokens=2000) or ""


def _reponse_ticket_valide(texte, nb_jambes_attendues):
    """Garde-fou anti-réponse inutilisable : constaté en pratique qu'un modèle gratuit
    (OpenRouter) peut renvoyer un texte court hors-sujet (ex: 'User Safety: safe') qui
    passait le seul contrôle existant (verifier_pas_de_12) faute de vérifier que le texte
    contient RÉELLEMENT les jambes attendues — envoyé tel quel sur Telegram avant ce
    correctif. Exige au moins nb_jambes_attendues blocs '⚽' et une longueur minimale
    plausible (un vrai ticket avec guide/onglet fait largement plus de 50 caractères)."""
    if not texte or len(texte.strip()) < 50:
        return False
    if texte.count("⚽") < nb_jambes_attendues:
        return False
    return True


def _tache_redaction(donnees_prompt, pronostic_texte, nb_jambes_attendues):
    """Tâche IA 3/3 — rédige le ticket pédagogique final, avec retry anti-'12' et
    anti-réponse-vide/hors-sujet (voir _reponse_ticket_valide)."""
    prompt = (
        f"System: Tu es un rédacteur qui explique les paris sportifs à un DÉBUTANT complet sur 1xbet. "
        f"Réponds UNIQUEMENT en français.\n"
        f"{CONSIGNES_COMMUNES_IA}\n\n"
        f"Sélections avec chiffres exacts :\n{donnees_prompt}\n"
        f"Pronostic confirmé avec niveau de confiance :\n{pronostic_texte}\n\n"
        f"Rédige le ticket final pour Telegram, un bloc par match, avec ce format EXACT :\n"
        f"'⚽ Match\\n"
        f"   🎯 Marché : Sélection @ Cote (edge X% · Confiance : niveau)\\n"
        f"   📖 Guide : [recopie ICI, MOT POUR MOT, le 'Guide déjà rédigé' fourni plus haut pour cette "
        f"sélection précise — ne l'invente pas, ne le résume pas, ne le change pas]\\n"
        f"   📍 Où parier : [recopie ICI, MOT POUR MOT, l''Onglet déjà déterminé' fourni plus haut pour "
        f"cette sélection précise — ne l'invente pas]'\n"
        f"Ligne vide entre chaque bloc match. Ne calcule et n'affiche AUCUNE cote totale ni probabilité "
        f"combinée — ces chiffres sont ajoutés séparément après ton texte, PAR CODE PYTHON, pas par toi. "
        f"AUCUN texte d'intro ni de conclusion en dehors de ce format."
    )
    print("   ✍️ [Tâche 3/3] Rédaction pédagogique du ticket...")
    for tentative in range(3):
        try:
            candidat = appel_llm(prompt, max_tokens=3000)
        except Exception as e:
            print(f"      ⚠️ Tentative {tentative + 1}/3 échouée : {e}")
            time.sleep(5)
            continue
        if not _reponse_ticket_valide(candidat, nb_jambes_attendues):
            print(f"      ⚠️ Tentative {tentative + 1}/3 : réponse invalide/hors-sujet du LLM "
                  f"(attendu {nb_jambes_attendues} jambes '⚽', reçu {candidat.count('⚽') if candidat else 0}) : "
                  f"{candidat[:80] if candidat else '(vide)'!r} — nouvel essai...")
            time.sleep(5)
            continue
        if verifier_pas_de_12(candidat):
            return candidat
        print(f"      ⚠️ Tentative {tentative + 1}/3 : sélection '12' détectée, nouvel essai...")
        time.sleep(5)
    return None


def agent4_ia_analyse_pronostic_redaction(selections_finales):
    """AGENT 4 — IA. Responsabilité unique : transformer les chiffres déjà calculés (Agent 3)
    en un texte pédagogique. Ne recalcule JAMAIS un edge, une cote ou une probabilité —
    ne fait que raisonner et rédiger à partir de ce qu'on lui donne. 3 tâches chaînées :
    analyse -> pronostic -> rédaction pédagogique finale."""
    donnees_prompt = _construire_donnees_prompt(selections_finales)

    analyse_texte = _tache_analyse(donnees_prompt, len(selections_finales))
    time.sleep(6)
    pronostic_texte = _tache_pronostic(donnees_prompt, analyse_texte)
    time.sleep(6)
    ticket_texte = _tache_redaction(donnees_prompt, pronostic_texte, len(selections_finales))

    return ticket_texte


def calculer_stats_combine(selections_finales):
    """Calcule la cote totale ET la probabilité combinée réelle du ticket (produit des
    probabilités modèle de chaque jambe) — en pur Python, jamais laissé au LLM. C'est ce
    chiffre, pas la somme des edges individuels, qui dit honnêtement la vraie chance de
    gagner le combiné EN ENTIER (toutes les jambes en même temps)."""
    cote_totale = 1.0
    proba_combinee = 1.0
    for s in selections_finales:
        cote_totale *= s["pick"]["cote"]
        proba_combinee *= s["pick"]["proba_modele_pct"] / 100
    return round(cote_totale, 2), round(proba_combinee * 100, 1)


def verifier_fraicheur_matchs(matchs_exploitables):
    """Filet de sécurité fraîcheur : la sélection initiale (collecte_donnees.py) ne garde
    que les matchs 'Pre-Game' avec cotes actives, mais un match peut démarrer ou se
    terminer entre la collecte et l'envoi si trop de temps s'écoule (constaté en pratique
    le 2026-07-25 : plusieurs heures d'écart lors de tests manuels ont rendu 5 matchs sur 9
    déjà terminés au moment de l'envoi). Revérifie le statut RÉEL juste avant utilisation et
    retire tout match qui n'est plus 'Pre-Game' avec cotes actives."""
    if not matchs_exploitables:
        return matchs_exploitables

    date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    try:
        r = requests.get("https://api.oddspapi.io/v4/fixtures",
                          params={"apiKey": ODDSPAPI_KEY, "sportId": 10, "from": date_from, "to": date_to},
                          timeout=20, verify=VERIFIER_SSL_ODDSPAPI)
        fixtures_actuelles = {fx["fixtureId"]: fx for fx in r.json()} if r.status_code == 200 else {}
    except Exception as e:
        print(f"   ⚠️ Impossible de revérifier la fraîcheur des matchs ({e}) — poursuite sans ce filtre.")
        return matchs_exploitables

    encore_valables = []
    for m in matchs_exploitables:
        fid = m["oddspapi"]["fixture_id"]
        fx = fixtures_actuelles.get(fid)
        if fx and fx.get("statusName") == "Pre-Game" and fx.get("hasOdds"):
            encore_valables.append(m)
        else:
            demande = m["match_demande"]
            statut = fx.get("statusName") if fx else "introuvable"
            print(f"   ⚠️ {demande['home']} vs {demande['away']} n'est plus pariable "
                  f"(statut actuel : {statut}) — retiré avant construction des coupons.")

    if len(encore_valables) < len(matchs_exploitables):
        print(f"   → {len(matchs_exploitables) - len(encore_valables)} match(s) retiré(s) pour fraîcheur, "
              f"{len(encore_valables)} restant(s).")
    return encore_valables


def agent3_calcul_pool_candidats(donnees):
    """AGENT 3 — variante 'pool' : comme agent3_calcul_mathematique, mais garde jusqu'à
    NB_CANDIDATS_PAR_MATCH candidats distincts PAR MATCH (pas seulement le meilleur) —
    nécessaire pour composer ensuite 3 coupons ciblant des fourchettes de cote totale
    différentes à partir du même pool. Renvoie {nom_match: [candidat, ...]}."""
    global SEUIL_EDGE, PROBA_MIN_FORTE
    SEUIL_EDGE, PROBA_MIN_FORTE = EDGE_MIN_POOL, PROBA_MIN_POOL

    matchs_exploitables = [m for m in donnees["matchs"] if m["oddspapi"]["tous_marches"]]
    matchs_exploitables = verifier_fraicheur_matchs(matchs_exploitables)
    print(f"   → {len(matchs_exploitables)} matchs avec marchés collectés à analyser "
          f"(pool commun : edge≥{EDGE_MIN_POOL}% · proba≥{PROBA_MIN_POOL}%)")

    pool = {}
    for m in matchs_exploitables:
        af = m["api_football"]
        home_demande = m["match_demande"]["home"]
        away_demande = m["match_demande"]["away"]
        marches = m["oddspapi"]["tous_marches"]
        home_nom = af["home_name"] if af else home_demande
        away_nom = af["away_name"] if af else away_demande
        print(f"   → Calcul : {home_nom} vs {away_nom}")

        stats_hist = m.get("stats_historiques") or {}
        understat = m.get("understat_xg") or {}
        xg_understat = calculer_xg_depuis_understat(understat.get("home"), understat.get("away"))
        xg_stats = calculer_xg_depuis_stats(stats_hist.get("home"), stats_hist.get("away"))
        if xg_understat:
            home_xg, away_xg = xg_understat
            print(f"      ✓ Buts attendus depuis les xG Understat de la saison en cours : {home_xg} / {away_xg}")
        elif xg_stats:
            home_xg, away_xg = xg_stats
            saisons = sorted({str(st.get("season")) for st in (stats_hist.get("home"), stats_hist.get("away"))
                              if st.get("season")})
            print(f"      ✓ Buts attendus depuis les VRAIES stats historiques : {home_xg} / {away_xg}")
            if saisons:
                print(f"      ⚠️ Stats de la saison {', '.join(saisons)} (plan gratuit API-Football) — "
                      f"pas la saison en cours, à prendre avec prudence")
        else:
            home_xg, away_xg, _, _, _ = estimer_expected_goals_depuis_marches(marches)
            print(f"      → Stats indisponibles, repli sur estimation depuis les cotes : {home_xg} / {away_xg}")

        mu_corners = estimer_ligne_equilibree(marches, ["corner"])
        mu_cartons = estimer_ligne_equilibree(marches, ["card", "booking"])

        candidats = evaluer_marches(marches, home_xg, away_xg, mu_corners, mu_cartons)
        print(f"      → {len(marches)} marchés bruts scannés, {len(candidats)} candidat(s) valable(s)")
        if not candidats:
            continue

        # Diversité de marché : garde le MEILLEUR candidat de CHAQUE catégorie trouvée pour
        # ce match (BTTS, Handicap Asiatique, Double Chance, Pair/Impair, Clean Sheet, Win to
        # Nil, Total...) — pas seulement les N plus probables tous confondus. evaluer_marches
        # trie déjà par probabilité décroissante, donc le premier candidat rencontré par
        # catégorie est le meilleur de cette catégorie. Sans ça, le pool est dominé par les
        # marchés Total (souvent les plus probables) et les coupons finaux ne proposent jamais
        # de BTTS/Handicap/etc. même quand ils sont valables.
        meilleur_par_categorie = {}
        for c in candidats:
            if c["categorie"] not in meilleur_par_categorie:
                meilleur_par_categorie[c["categorie"]] = c
        candidats_diversifies = list(meilleur_par_categorie.values())[:NB_CANDIDATS_PAR_MATCH]

        nom_match = f"{home_nom} vs {away_nom}"
        pool[nom_match] = [
            {
                "match": nom_match, "home_nom": home_nom, "away_nom": away_nom,
                "fixture_id_oddspapi": m["oddspapi"]["fixture_id"], "pick": c,
            }
            for c in candidats_diversifies
        ]
        print(f"      → {len(candidats_diversifies)} catégorie(s) de marché distincte(s) retenue(s) "
              f"pour ce match : {', '.join(c['categorie'] for c in candidats_diversifies)}")
    return pool


def _produit_cotes(jambes):
    produit = 1.0
    for j in jambes:
        produit *= j["pick"]["cote"]
    return produit


def selectionner_combo_cote_cible(pool_par_match, nb_jambes, cote_min, cote_max, essais=4000):
    """Recherche aléatoire PONDÉRÉE (Monte Carlo) : compose nb_jambes sélections — une par
    match distinct si assez de matchs, sinon complète avec un 2e marché du même match —
    dont le produit des cotes tombe dans [cote_min, cote_max].

    Le tirage par match est pondéré vers les candidats dont la cote individuelle se
    rapproche de la cote 'par jambe' typiquement nécessaire pour atteindre CETTE cible
    (moyenne géométrique de la fourchette, répartie sur nb_jambes) — un tirage purement
    uniforme (essayé d'abord) devient de moins en moins fiable à mesure que le pool
    grandit : plus de candidats = plus de combinaisons possibles = moins de chances de
    tomber sur la bonne par pur hasard (constaté en pratique le 2026-07-25 : un Coupon
    'sûr' à cible basse ratait sa cible une fois le pool élargi pour aider le Coupon
    'audacieux'). Reste un tirage aléatoire (pas glouton/déterministe), juste orienté.

    Critères de choix final, dans l'ordre :
    1) tombe dans la cible de cote (sinon la plus proche si pas assez de matchs ce jour-là),
    2) le PLUS de catégories de marché DISTINCTES possible (BTTS, Handicap, Double Chance,
       Pair/Impair, Clean Sheet...) — sans ce critère, la recherche converge presque toujours
       vers des combinaisons de pur Total Over/Under (souvent les plus probables individuel-
       lement), constaté en pratique,
    3) la probabilité moyenne la plus forte, à diversité égale.
    Jamais None tant qu'il y a au moins nb_jambes candidats au total, jamais un chiffre
    inventé — uniquement un choix parmi des candidats déjà calculés en pur Python."""
    matchs = list(pool_par_match.keys())
    tous_candidats = [c for candidats in pool_par_match.values() for c in candidats]
    if len(tous_candidats) < nb_jambes:
        return None

    # Cote "par jambe" typiquement nécessaire pour atteindre le milieu de la cible en
    # nb_jambes multiplications (moyenne géométrique de la fourchette, répartie en nb_jambes
    # facteurs égaux) — sert uniquement à PONDÉRER le tirage, jamais à choisir directement.
    cote_par_jambe_visee = ((cote_min * cote_max) ** 0.5) ** (1 / nb_jambes)

    def poids_candidat(c):
        ecart_log = abs(math.log(c["pick"]["cote"]) - math.log(cote_par_jambe_visee))
        return 1.0 / (1.0 + ecart_log)

    poids_par_match = {m: [poids_candidat(c) for c in candidats] for m, candidats in pool_par_match.items()}
    poids_tous = [poids_candidat(c) for c in tous_candidats]

    def tirage_avec_repetition_possible():
        """Autorise plusieurs jambes du même match — nécessaire quand aucune combinaison
        sur des matchs 100% distincts ne peut atteindre la cible (constaté en pratique :
        avec seulement des matchs à cote élevée disponibles, le minimum atteignable sur
        nb_jambes matchs distincts peut dépasser la cible basse d'un profil 'sûr')."""
        combo = []
        restants, poids_restants = list(tous_candidats), list(poids_tous)
        for _ in range(nb_jambes):
            if not restants:
                restants, poids_restants = list(tous_candidats), list(poids_tous)
            choix = random.choices(range(len(restants)), weights=poids_restants, k=1)[0]
            combo.append(restants.pop(choix))
            poids_restants.pop(choix)
        return combo

    meilleure_combo, meilleur_score = None, None
    for essai in range(essais):
        # Alterne : moitié des essais forcent la diversité maximale de matchs (quand assez
        # de matchs distincts existent), l'autre moitié autorise la répétition — le score
        # ci-dessous choisit ensuite objectivement le meilleur résultat des deux approches,
        # jamais un chiffre inventé, juste une exploration plus large des combinaisons
        # RÉELLEMENT possibles avec les candidats déjà calculés.
        if len(matchs) >= nb_jambes and essai % 2 == 0:
            combo = [
                random.choices(pool_par_match[m], weights=poids_par_match[m], k=1)[0]
                for m in random.sample(matchs, nb_jambes)
            ]
        else:
            combo = tirage_avec_repetition_possible()

        cote = _produit_cotes(combo)
        dans_cible = cote_min <= cote <= cote_max
        proba_moyenne = sum(c["pick"]["proba_modele_pct"] for c in combo) / len(combo)
        nb_matchs_distincts = len({c["match"] for c in combo})
        nb_categories_distinctes = len({c["pick"]["categorie"] for c in combo})
        ecart = 0.0 if dans_cible else min(abs(cote - cote_min), abs(cote - cote_max))
        # Priorité : 1) cote dans la cible (ou la plus proche), 2) diversité de matchs
        # (moins de corrélation entre jambes), 3) diversité de catégories, 4) probabilité
        # moyenne. La diversité de matchs passe AVANT celle des catégories : le risque de
        # corréler deux paris sur le MÊME match est plus grave que de manquer de variété
        # dans les TYPES de pari.
        score = (dans_cible, -ecart, nb_matchs_distincts, nb_categories_distinctes, proba_moyenne)
        if meilleur_score is None or score > meilleur_score:
            meilleur_score, meilleure_combo = score, combo

    return meilleure_combo


def generer_trois_coupons(donnees):
    """Compose les 3 coupons (PROFILS_COUPON) à partir d'UN SEUL pool de candidats calculé
    une fois par Agent 3 (agent3_calcul_pool_candidats) — un seul calcul Poisson/edge par
    match, trois compositions différentes en aval selon la fourchette de cote visée."""
    pool = agent3_calcul_pool_candidats(donnees)
    nb_candidats_total = sum(len(v) for v in pool.values())
    print(f"\n   📦 Pool commun : {nb_candidats_total} candidat(s) sur {len(pool)} match(s) distinct(s)")

    resultats = []
    for profil in PROFILS_COUPON:
        combo = selectionner_combo_cote_cible(pool, profil["nb_jambes"], profil["cote_min"], profil["cote_max"])
        if combo is None:
            print(f"   ⚠️ [{profil['nom']}] pas assez de candidats disponibles pour {profil['nb_jambes']} jambes "
                  f"({nb_candidats_total} au total) — profil vide aujourd'hui.")
            resultats.append({"profil": profil, "selections": []})
            continue
        cote_reelle = _produit_cotes(combo)
        dans_cible = profil["cote_min"] <= cote_reelle <= profil["cote_max"]
        etat_txt = "" if dans_cible else "  ⚠️ HORS CIBLE (pas assez de matchs pour mieux ce jour-là), meilleur compromis gardé"
        print(f"   {'✓' if dans_cible else '⚠️'} [{profil['nom']}] {len(combo)} jambes, cote totale réelle "
              f"{cote_reelle:.2f} (cible {profil['cote_min']}-{profil['cote_max']}){etat_txt}")
        resultats.append({"profil": profil, "selections": combo})
    return resultats


def agent4_rediger_trois_coupons(resultats_profils):
    """AGENT 4 — IA, une rédaction par profil (même Agent 3, trois lectures). Renvoie une
    section de texte par profil, y compris ceux sans sélection valable (phrase honnête
    plutôt qu'un profil silencieusement omis du message final)."""
    sections = []
    for item in resultats_profils:
        profil, selections = item["profil"], item["selections"]
        if not selections:
            sections.append(f"{profil['nom']}\n_Aucune sélection ne remplit les critères de ce profil aujourd'hui._")
            continue
        print(f"\n🤖 [AGENT 4 — {profil['nom']}] rédaction...")
        ticket_texte = agent4_ia_analyse_pronostic_redaction(selections)
        if not ticket_texte:
            sections.append(f"{profil['nom']}\n_Échec de la rédaction IA pour ce profil — réessaiera au prochain cycle._")
            continue
        cote_totale, proba_combinee = calculer_stats_combine(selections)
        nb_matchs_distincts = len({s["match"] for s in selections})
        avertissement_correlation = ""
        if nb_matchs_distincts < len(selections):
            # Plusieurs jambes sur le MÊME match ne sont pas statistiquement indépendantes
            # (ex: "Total Under" et "Handicap domicile" du même match sont corrélés) — la
            # probabilité combinée (produit des probas individuelles) suppose l'indépendance
            # et devient donc optimiste dans ce cas. Toujours signalé, jamais caché.
            avertissement_correlation = (
                f"\n⚠️ _{len(selections)} jambes sur seulement {nb_matchs_distincts} matchs distincts "
                f"(pas assez de matchs disponibles aujourd'hui) — plusieurs paris viennent du même "
                f"match, donc la probabilité combinée ci-dessous est optimiste (jambes corrélées, "
                f"pas indépendantes)._"
            )
        sections.append(
            f"{profil['nom']} — {len(selections)} jambes sur {nb_matchs_distincts} match{'s' if nb_matchs_distincts > 1 else ''}\n\n"
            f"{ticket_texte}\n\n"
            f"💰 Cote totale : *{cote_totale}* · 🎲 Probabilité combinée réelle : *{proba_combinee}%*"
            f"{avertissement_correlation}"
        )
        time.sleep(6)
    return sections


TELEGRAM_LIMITE_CARACTERES = 4096  # limite dure de l'API Telegram par message


def agent5_envoyer_trois_coupons(sections):
    """AGENT 5 — LIVRAISON. Envoie CHAQUE profil dans son PROPRE message Telegram —
    jamais un seul message avec les 3 (avec 8 jambes détaillées par profil, le texte
    dépasse presque toujours la limite dure de 4096 caractères de Telegram, constaté en
    pratique : 'Bad Request: message is too long'). Vérifie le succès RÉEL de chaque envoi
    (notifier_telegram renvoie False en cas d'échec) plutôt que de supposer que ça a marché.
    Renvoie True seulement si TOUS les messages sont partis."""
    date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
    entete = f"🎯 *TICKETS DU JOUR — {date_str}*\nedge réel calculé par Poisson · 1xBet\n━━━━━━━━━━━━━━━━━━━━\n\n"
    pied = (
        f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ _Analyse automatisée à titre indicatif — vérifie toujours les cotes en direct sur 1xBet avant de parier._"
    )

    tout_envoye = True
    for i, section in enumerate(sections, start=1):
        message = entete + section + pied
        if len(message) > TELEGRAM_LIMITE_CARACTERES:
            # Filet de sécurité : coupe proprement plutôt que de laisser Telegram rejeter
            # tout le message — perd le pied de page mais garde le contenu utile (le pari).
            coupe = TELEGRAM_LIMITE_CARACTERES - len("\n\n_[message tronqué — trop long pour Telegram]_")
            message = message[:coupe] + "\n\n_[message tronqué — trop long pour Telegram]_"
            print(f"   ⚠️ Profil {i}/{len(sections)} tronqué ({len(entete) + len(section) + len(pied)} caractères, limite {TELEGRAM_LIMITE_CARACTERES})")
        print(f"   📤 Envoi Telegram profil {i}/{len(sections)}...")
        ok = notifier_telegram(message)
        tout_envoye = tout_envoye and ok
        if not ok:
            print(f"   ❌ Échec d'envoi pour le profil {i}/{len(sections)} — voir erreur ci-dessus.")
        time.sleep(1)  # évite de rafaler l'API Telegram entre les 3 messages

    return tout_envoye


# ============================================================
# PIPELINE PRINCIPAL — orchestre les 5 agents dans l'ordre
# ============================================================

def main():
    print("🚀 Pipeline : Données (1-2, déjà fait) → Calcul 3 profils (3) → IA×3 (4) → Livraison (5)")

    with open(ENTREE_JSON, "r", encoding="utf-8") as f:
        donnees = json.load(f)

    print("\n📊 [AGENT 3 — CALCUL MATHÉMATIQUE, 3 PROFILS DE RISQUE]")
    resultats_profils = generer_trois_coupons(donnees)

    if not any(item["selections"] for item in resultats_profils):
        print("⚠️ Aucune sélection avec edge positif sur aucun des 3 profils — pas de ticket envoyé.")
        notifier_telegram("⚠️ Aucun pick avec edge positif aujourd'hui, sur aucun des 3 profils de risque.")
        return

    print("\n🤖 [AGENT 4 — RÉDACTION IA × 3 PROFILS]")
    sections = agent4_rediger_trois_coupons(resultats_profils)

    print("\n📤 [AGENT 5 — LIVRAISON TELEGRAM]")
    tout_envoye = agent5_envoyer_trois_coupons(sections)
    if not tout_envoye:
        print("⚠️ Au moins un profil n'a pas pu être envoyé sur Telegram (voir erreurs ci-dessus).")
    sauvegarder_ticket_du_jour(resultats_profils)
    print("\n✅ Pipeline terminé !")


MINUTES_MARGE_FIN_MATCH = 130  # 90 min + mi-temps + arrêts de jeu, marge de sécurité


def estimer_heure_fin_ticket(selections_finales):
    """Interroge OddsPapi pour connaître le coup d'envoi de chaque match du ticket, et
    renvoie (en ISO UTC) l'heure estimée de fin du DERNIER match (le plus tardif) + marge
    de sécurité. Sert à verifier_resultats.py pour ne JAMAIS appeler l'API (quota) avant
    cette heure, au lieu de vérifier toutes les 30 minutes toute la soirée pour rien.
    Renvoie None si l'heure de coup d'envoi est introuvable (verifier_resultats.py vérifiera
    alors dès son premier passage, comme filet de sécurité)."""
    date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    try:
        r = requests.get("https://api.oddspapi.io/v4/fixtures",
                          params={"apiKey": ODDSPAPI_KEY, "sportId": 10, "from": date_from, "to": date_to},
                          timeout=20, verify=VERIFIER_SSL_ODDSPAPI)
        fixtures = {fx["fixtureId"]: fx for fx in r.json()} if r.status_code == 200 else {}
    except Exception as e:
        print(f"⚠️ Impossible d'estimer l'heure de fin du ticket : {e}")
        return None

    heures_debut = []
    for s in selections_finales:
        fx = fixtures.get(s["fixture_id_oddspapi"])
        if fx and fx.get("startTime"):
            try:
                heures_debut.append(datetime.fromisoformat(fx["startTime"].replace("Z", "+00:00")))
            except ValueError:
                continue

    if not heures_debut:
        return None

    dernier_coup_envoi = max(heures_debut)
    return (dernier_coup_envoi + timedelta(minutes=MINUTES_MARGE_FIN_MATCH)).isoformat()


def sauvegarder_ticket_du_jour(resultats_profils):
    """Sauvegarde les 3 coupons envoyés (avec fixture_id_oddspapi de chaque jambe, par
    profil) pour que verifier_resultats.py puisse, plus tard dans la journée, aller
    chercher le score final de chaque match et juger si chaque pari est gagné/perdu —
    jamais recalculé ici, juste persisté tel quel pour un usage ultérieur."""
    toutes_selections = [s for item in resultats_profils for s in item["selections"]]
    ticket = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "genere_a": datetime.now().isoformat(),
        "verification_apres": estimer_heure_fin_ticket(toutes_selections),
        "profils": [
            {
                "cle": item["profil"]["cle"],
                "nom": item["profil"]["nom"],
                "cote_totale": calculer_stats_combine(item["selections"])[0] if item["selections"] else None,
                "proba_combinee_pct": calculer_stats_combine(item["selections"])[1] if item["selections"] else None,
                "selections": item["selections"],
            }
            for item in resultats_profils
        ],
        "resultat_envoye": False,
    }
    with open(TICKET_DU_JOUR_JSON, "w", encoding="utf-8") as f:
        json.dump(ticket, f, ensure_ascii=False, indent=2)
    print(f"💾 Ticket du jour (3 profils) sauvegardé dans {TICKET_DU_JOUR_JSON}"
          + (f" — vérification autorisée après {ticket['verification_apres']}" if ticket['verification_apres'] else ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Erreur fatale du pipeline : {e}")
        try:
            notifier_telegram(f"⚠️ *Pipeline échoué* — erreur inattendue : {e}")
        except Exception:
            pass

