"""Comparaison PARALLÈLE bet_agent (production, Telegram) vs moteur/ (10 modèles formels,
Dixon-Coles + binomiale négative) — demande explicite du 10/10/2026 : "faire fonctionner le
nouveau moteur en parallèle du pipeline actuel, sans modifier le coupon Telegram".

RÈGLES ABSOLUES :
- Jamais utilisée pour choisir un pari ni pour modifier le texte envoyé sur Telegram — appelée
  séparément, après la composition du coupon (voir runs.py, derrière MOTEUR_COMPARAISON_ACTIVE,
  désactivée par défaut).
- Aucune calibration FABRIQUÉE : "methode_calibration" reste "non_calibree" tant qu'aucun
  calibrateur n'a démontré un gain réel mesuré par backtest. Constat réel (rapport du
  10/10/2026, 760 matchs Premier League réels) : la calibration walk-forward ACTUELLE est NETTE-
  MENT MOINS bonne que la probabilité brute sur les données disponibles aujourd'hui (Brier 0.197
  brut contre 0.199 calibré pour "resultat", 0.241 contre 0.246 pour "btts") — donc ne JAMAIS
  l'appliquer ici tant que cette conclusion n'a pas changé avec plus d'historique.
- Si l'historique réel (hist_matchs) est insuffisant pour une équipe, le moteur est marqué
  indisponible pour CE candidat — jamais une probabilité inventée.
- Seuls les marchés listés dans MARCHE_MOTEUR_PAR_CATEGORIE sont mappés aujourd'hui (Total,
  Total Équipe 1/2, BTTS, Double Chance) — un marché bet_agent non mappé est signalé tel quel,
  jamais deviné."""

import sys
from pathlib import Path

# moteur/ vit à la racine du dépôt, hors du package "app" — jamais sur sys.path quand ce
# fichier est importé via `python -m app.taches` (working-directory: backend, voir workflows)
# ni via `pytest` lancé depuis backend/ (voir tests/test_comparaison_moteurs.py). Ce module est
# le SEUL pont entre les deux arborescences : c'est ici, et nulle part ailleurs dans backend/,
# que la racine du dépôt est ajoutée au path si besoin.
_RACINE_DEPOT = str(Path(__file__).resolve().parents[3])
if _RACINE_DEPOT not in sys.path:
    sys.path.insert(0, _RACINE_DEPOT)

from moteur import cotes as mcotes  # noqa: E402
from moteur.config import Config  # noqa: E402
from moteur.features import Historique, construire_features, en_datetime  # noqa: E402
from moteur.modeles.registre import predire_match  # noqa: E402

from app.services.historique import charger_matchs

CFG = Config()

# (categorie bet_agent, selection bet_agent en minuscules) -> (marche moteur, selection moteur)
# ligne (handicap) reprise telle quelle du candidat bet_agent dans les deux cas.
MARCHE_MOTEUR_PAR_CATEGORIE = {
    ("Total", "over"): ("buts_total", "over"), ("Total", "under"): ("buts_total", "under"),
    ("Total Équipe 1", "over"): ("buts_equipe1", "over"), ("Total Équipe 1", "under"): ("buts_equipe1", "under"),
    ("Total Équipe 2", "over"): ("buts_equipe2", "over"), ("Total Équipe 2", "under"): ("buts_equipe2", "under"),
    ("BTTS", "oui"): ("btts", "oui"), ("BTTS", "yes"): ("btts", "oui"),
    ("BTTS", "non"): ("btts", "non"), ("BTTS", "no"): ("btts", "non"),
    ("Double Chance", "1x"): ("double_chance", "1X"), ("Double Chance", "x2"): ("double_chance", "X2"),
    ("Double Chance", "12"): ("double_chance", "12"),
}


def _marche_moteur(categorie, selection):
    cle = (categorie, str(selection).lower())
    return MARCHE_MOTEUR_PAR_CATEGORIE.get(cle)


def predictions_moteur_pour_match(hist, home_id, away_id, competition_id, date_iso, lignes=None):
    """Toutes les prédictions moteur/ pour ce match (10 modèles), ou None si l'historique réel
    des deux équipes est insuffisant (cfg.min_matchs_equipe) — jamais un chiffre inventé.
    hist : moteur.features.Historique déjà construit (voir comparer_candidats — une seule
    requête hist_matchs par run, jamais rechargée par candidat)."""
    match = {"match_id": -1, "date": date_iso, "home_id": home_id, "away_id": away_id,
             "competition_id": competition_id, "arbitre": None}
    features = construire_features(match, hist, CFG.fenetre_forme)
    if features["home"]["n_matchs"] < CFG.min_matchs_equipe or features["away"]["n_matchs"] < CFG.min_matchs_equipe:
        return None, features["home"]["n_matchs"], features["away"]["n_matchs"]
    return predire_match(features, CFG, lignes), features["home"]["n_matchs"], features["away"]["n_matchs"]


def comparer_candidat(predictions_moteur, n_home, n_away, candidat):
    """candidat : un élément du pool bet_agent ({"match", "pick": {...}}). Renvoie le dict à 9
    champs demandé (proba bet_agent / proba moteur / proba calibrée / cote / cote juste / edge /
    historique / modèle responsable / décision de chaque système) — jamais une sélection,
    seulement une comparaison affichée/journalisée."""
    pick = candidat["pick"]
    proba_betagent = (pick.get("proba_modele_pct") or 0) / 100 if pick.get("proba_modele_pct") is not None else None
    cote = pick.get("cote")
    decision_betagent = "retenu (si sélectionné par le Monte Carlo)" if proba_betagent else "non calculé (marché brut)"

    resultat = {
        "match": candidat["match"], "marche_bet_agent": pick.get("marche_affichage") or pick.get("marche"),
        "selection": pick.get("selection"), "cote_bookmaker": cote,
        "cote_juste": round(1 / proba_betagent, 3) if proba_betagent else None,
        "proba_bet_agent_pct": pick.get("proba_modele_pct"), "edge_bet_agent_pct": pick.get("edge_pct"),
        "decision_bet_agent": decision_betagent,
        "proba_moteur_pct": None, "modele_moteur": None, "calibration": "non_calibree",
        "n_historique_home": n_home, "n_historique_away": n_away, "decision_moteur": None,
    }
    mapping = _marche_moteur(pick.get("categorie"), pick.get("selection"))
    if mapping is None:
        resultat["decision_moteur"] = "marché non mappé (voir MARCHE_MOTEUR_PAR_CATEGORIE)"
        return resultat
    marche_moteur, selection_moteur = mapping
    if predictions_moteur is None:
        resultat["decision_moteur"] = f"indisponible : historique insuffisant (home={n_home}, away={n_away} matchs, minimum {CFG.min_matchs_equipe})"
        return resultat
    ligne = pick.get("handicap")
    pred = next((p for p in predictions_moteur if p.marche == marche_moteur and p.ligne == ligne
                and p.selection == selection_moteur), None)
    if pred is None:
        resultat["decision_moteur"] = f"prédiction absente pour ligne={ligne} (non modélisable ici)"
        return resultat
    p_moteur = pred.probabilite
    resultat["proba_moteur_pct"] = round(p_moteur * 100, 1)
    resultat["modele_moteur"] = pred.nom_modele
    resultat["edge_moteur_pct"] = round(mcotes.edge(p_moteur, cote) * 100, 1) if cote else None
    resultat["decision_moteur"] = ("retenu (proba >= seuil)" if p_moteur * 100 >= CFG.proba_min * 100
                                   else "rejeté (proba < seuil)")
    return resultat


def comparer_candidats(db, pool):
    """pool : {match: [candidat, ...]} (agent3_calcul_pool_candidats, avec af_home_id/
    af_away_id/competition_id/date_iso ajoutés le 10/10/2026). Une comparaison par candidat
    UNIQUE (un seul par (match, catégorie, sélection) — les doublons de ligne ne sont comparés
    qu'une fois pour limiter le volume). Une seule requête hist_matchs pour tout le run."""
    hist = Historique(charger_matchs(db))
    deja_vus, resultats = set(), []
    for nom_match, candidats in pool.items():
        if not candidats:
            continue
        premier = candidats[0]
        home_id, away_id = premier.get("af_home_id"), premier.get("af_away_id")
        competition_id, date_iso = premier.get("competition_id"), premier.get("date_iso")
        predictions_moteur = n_home = n_away = None
        if home_id and away_id and date_iso:
            predictions_moteur, n_home, n_away = predictions_moteur_pour_match(
                hist, home_id, away_id, competition_id, date_iso)
        for c in candidats:
            cle = (nom_match, c["pick"].get("categorie"), c["pick"].get("selection"))
            if cle in deja_vus:
                continue
            deja_vus.add(cle)
            resultat = comparer_candidat(predictions_moteur, n_home, n_away, c)
            if (home_id is None or away_id is None) and resultat["decision_moteur"] \
                    and resultat["decision_moteur"].startswith("indisponible : historique insuffisant"):
                resultat["decision_moteur"] = "indisponible : équipe API-Football non identifiée"
            resultats.append(resultat)
    return resultats
