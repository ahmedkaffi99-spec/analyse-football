"""
Agent 6 — VÉRIFICATION DES RÉSULTATS. Lit ticket_du_jour.json (écrit par
analyser_et_envoyer.py à midi), attend que TOUS les matchs du ticket soient terminés
(statusName "Finished" côté OddsPapi), récupère le score réel de chacun (/v4/scores),
juge chaque jambe gagnée/perdue/remboursée à partir de ce score, et envoie le bilan
complet + résultat du combiné entier sur Telegram.

Conçu pour être relancé périodiquement par cron dans la soirée : tant qu'un match n'est
pas encore terminé, le script ne fait rien et se termine silencieusement (aucun risque de
spam). Une fois le résultat envoyé, ticket_du_jour.json est marqué resultat_envoye=true
pour ne jamais renvoyer deux fois le même bilan.

Ne rejuge JAMAIS un chiffre du ticket original (cote, marché, sélection) — les recopie
tels quels, ne fait que comparer au score réel.
"""

import os
import re
import json
import requests
import urllib3
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from unidecode import unidecode
from rapidfuzz import fuzz

# Voir collecte_donnees.py pour le détail : OddsPapi est intercepté par un boîtier réseau
# (Fortinet) qui re-signe son certificat avec une CA non reconnue — désactivé uniquement
# pour ce domaine précis (déjà intercepté de toute façon), jamais pour Telegram.

from analyser_et_envoyer import notifier_telegram

load_dotenv("envi.local")

# Vérification du certificat OddsPapi : ACTIVE par défaut (GitHub Actions, serveur, PC).
# ODDSPAPI_SSL_NON_VERIFIE=true seulement sur un réseau qui intercepte le certificat (boîtier
# Fortinet constaté sur l'ancien environnement Termux) — jamais pour les autres APIs.
VERIFIER_SSL_ODDSPAPI = os.getenv("ODDSPAPI_SSL_NON_VERIFIE", "").lower() not in ("1", "true", "oui")
if not VERIFIER_SSL_ODDSPAPI:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY")
TICKET_JSON = "ticket_du_jour.json"

# Corners/cartons : aucune donnée de score fournie par OddsPapi (uniquement les buts) —
# ces jambes ne peuvent pas être vérifiées automatiquement, jamais inventées.
CATEGORIES_NON_VERIFIABLES = ("Total Corners", "Total Cartons")


def recuperer_fixtures_du_jour():
    """Fenêtre large (-1 à +2 jours) pour ne jamais rater un match à cheval sur minuit UTC,
    même logique de sécurité que collecte_donnees.py."""
    date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
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


def trouver_score_api_football(home_nom, away_nom, fixtures_af, cd):
    """Fuzzy-match par nom d'équipe (cd.score_paire_equipes, même seuil que la collecte).
    Renvoie (but_domicile, but_exterieur) — déjà dans le bon ordre — seulement si un match est
    trouvé ET terminé (statut 'FT' : temps réglementaire, pas de prolongation/tirs au but pour
    ces compétitions). None si aucun match fiable ou pas encore terminé."""
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
    if (meilleur.get("fixture") or {}).get("status", {}).get("short") != "FT":
        return None
    buts = meilleur.get("goals") or {}
    if buts.get("home") is None or buts.get("away") is None:
        return None
    return buts["home"], buts["away"]


# ============================================================
# JUGEMENT DE CHAQUE JAMBE — même logique que evaluer_marches, mais appliquée
# au score réel final plutôt qu'à une probabilité Poisson.
# ============================================================

def juger_total(categorie, handicap, selection, home_g, away_g):
    if handicap is None:
        return None
    total = {"Total": home_g + away_g, "Total Équipe 1": home_g, "Total Équipe 2": away_g}[categorie]
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
        return juger_total(categorie, handicap, selection, home_g, away_g)
    if categorie in CATEGORIES_NON_VERIFIABLES:
        return None
    if categorie == "BTTS":
        return juger_btts(selection, home_g, away_g)
    if categorie == "Double Chance":
        return juger_double_chance(selection, home_g, away_g)
    if categorie == "Draw No Bet":
        return juger_draw_no_bet(selection, home_g, away_g)
    if categorie in ("Handicap Européen", "Handicap Asiatique"):
        # "Handicap Asiatique" : compatibilité avec les tickets persistés avant le renommage
        # du 01/10/2026 (voir analyser_et_envoyer.expliquer_marche) — même logique de jugement.
        return juger_handicap(handicap, selection, home_g, away_g) if handicap is not None else None
    if categorie == "Pair/Impair":
        return juger_pair_impair(selection, home_g, away_g)
    if categorie in ("Clean Sheet Équipe 1", "Clean Sheet Équipe 2"):
        return juger_clean_sheet(categorie, selection, home_g, away_g)
    if categorie in ("Win To Nil Équipe 1", "Win To Nil Équipe 2"):
        return juger_win_to_nil(categorie, selection, home_g, away_g)
    return None


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

def main():
    if not os.path.exists(TICKET_JSON):
        print("ℹ️ Aucun ticket_du_jour.json — rien à vérifier.")
        return

    with open(TICKET_JSON, "r", encoding="utf-8") as f:
        ticket = json.load(f)

    if ticket.get("resultat_envoye"):
        print("ℹ️ Résultat déjà envoyé pour ce ticket — rien à faire.")
        return

    if ticket.get("date") != datetime.now().strftime("%Y-%m-%d"):
        print("ℹ️ ticket_du_jour.json ne correspond pas à aujourd'hui — rien à faire.")
        return

    profils = ticket.get("profils") or []
    toutes_selections = [s for p in profils for s in p["selections"]]
    if not toutes_selections:
        print("ℹ️ Ticket vide (aucune sélection sur aucun profil) — rien à vérifier.")
        return

    # Aucun appel API tant que le dernier match du ticket n'est pas censé être terminé —
    # évite de consommer le quota OddsPapi toutes les 30 minutes pour rien pendant des heures.
    verification_apres = ticket.get("verification_apres")
    if verification_apres:
        try:
            seuil = datetime.fromisoformat(verification_apres)
            if datetime.now(timezone.utc) < seuil:
                print(f"⏳ Trop tôt (vérification prévue après {verification_apres}) — "
                      f"aucun appel API, on réessaiera au prochain passage du cron.")
                return
        except ValueError:
            pass

    fixtures_du_jour = recuperer_fixtures_du_jour()

    matchs_pas_finis = sorted({
        s["match"] for s in toutes_selections
        if not (fixtures_du_jour.get(s["fixture_id_oddspapi"]) or {}).get("statusName") == "Finished"
    })

    if matchs_pas_finis:
        print(f"⏳ {len(matchs_pas_finis)} match(s) pas encore terminé(s) parmi les 3 profils "
              f"({', '.join(matchs_pas_finis)}) — nouvelle tentative au prochain passage du cron.")
        return

    print("✅ Tous les matchs sont terminés — récupération des scores et jugement des 3 profils...")

    scores_cache = {}

    def score_du_match(fixture_id):
        if fixture_id not in scores_cache:
            scores_cache[fixture_id] = recuperer_score(fixture_id)
        return scores_cache[fixture_id]

    sections_message = []
    resultat_detail_par_profil = {}

    for profil in profils:
        selections = profil["selections"]
        if not selections:
            sections_message.append(f"{profil['nom']}\n_Aucune sélection ce jour-là pour ce profil._")
            continue

        lignes = []
        nb_gagnes = nb_perdus = nb_push = nb_non_verifiable = 0

        for s in selections:
            pick = s["pick"]
            fx = fixtures_du_jour[s["fixture_id_oddspapi"]]
            score = score_du_match(s["fixture_id_oddspapi"])

            if score is None:
                lignes.append(f"❓ {s['match']} — score indisponible : {pick['marche']} non vérifiable")
                nb_non_verifiable += 1
                continue

            p1_g, p2_g = score
            if home_est_participant1(s["home_nom"], fx.get("participant1Name"), fx.get("participant2Name")):
                home_g, away_g = p1_g, p2_g
            else:
                home_g, away_g = p2_g, p1_g

            verdict = grader_pick(pick, home_g, away_g)
            score_txt = f"{home_g}-{away_g}"

            if verdict == "gagne":
                nb_gagnes += 1
                icone = "✅"
            elif verdict == "perdu":
                nb_perdus += 1
                icone = "❌"
            elif verdict == "push":
                nb_push += 1
                icone = "➖ remboursé"
            else:
                nb_non_verifiable += 1
                icone = "❓ non vérifiable"

            lignes.append(f"{icone} {s['match']} ({score_txt}) — {pick['marche']} : "
                           f"{pick['selection']} @ {pick['cote']}")

        combine_gagne = (nb_perdus == 0 and nb_non_verifiable == 0)
        if nb_perdus > 0:
            verdict_global = "❌ PERDU"
        elif nb_non_verifiable > 0:
            verdict_global = "❓ INCERTAIN (au moins une jambe non vérifiable)"
        else:
            verdict_global = "✅ GAGNÉ"

        detail_compte = f"✅ {nb_gagnes} · ❌ {nb_perdus}"
        if nb_push:
            detail_compte += f" · ➖ {nb_push} remboursé(s)"
        if nb_non_verifiable:
            detail_compte += f" · ❓ {nb_non_verifiable} non vérifiable(s)"

        sections_message.append(
            f"{profil['nom']} — {verdict_global}\n\n"
            f"{chr(10).join(lignes)}\n\n"
            f"{detail_compte}\n"
            f"💰 Cote totale : *{profil['cote_totale']}*"
        )
        resultat_detail_par_profil[profil["cle"]] = {
            "gagnes": nb_gagnes, "perdus": nb_perdus, "push": nb_push,
            "non_verifiable": nb_non_verifiable, "combine_gagne": combine_gagne,
        }

    message = (
        f"🏁 *RÉSULTATS DU JOUR — 3 PROFILS — {ticket['date']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(sections_message)
    )

    notifier_telegram(message)

    ticket["resultat_envoye"] = True
    ticket["resultat_detail_par_profil"] = resultat_detail_par_profil
    with open(TICKET_JSON, "w", encoding="utf-8") as f:
        json.dump(ticket, f, ensure_ascii=False, indent=2)
    print("✅ Résultats envoyés sur Telegram et ticket_du_jour.json marqué comme traité.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Erreur fatale de verifier_resultats.py : {e}")
