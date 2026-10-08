"""Tests de la comparaison parallèle bet_agent / moteur (comparaison_moteurs.py) : aucun appel
réseau, aucune sélection ni texte Telegram touchés — uniquement la production des 9 champs de
comparaison, avec repli honnête ("indisponible"/"non mappé") quand les données manquent."""

from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.services import historique as hist
from app.services.comparaison_moteurs import comparer_candidats

HOME_ID, AWAY_ID = 100, 200


def _match_hist(match_id, home_id, away_id, home_g, away_g, jours_avant):
    date = (datetime.now(timezone.utc) - timedelta(days=jours_avant)).isoformat()
    return {"match_id": match_id, "date": date, "competition_id": 1, "competition": "Ligue Test",
            "saison": 2025, "home_id": home_id, "home": "H", "away_id": away_id, "away": "A",
            "arbitre": None, "statut": "FT", "home_score": home_g, "away_score": away_g, "stats": None}


def _peupler_historique_suffisant(db):
    # 6 matchs pour chaque équipe (>= cfg.min_matchs_equipe=5), tous dans le passé.
    matchs = []
    for i in range(6):
        matchs.append(_match_hist(i + 1, HOME_ID, 900 + i, 2, 1, jours_avant=30 + i * 10))
        matchs.append(_match_hist(i + 100, AWAY_ID, 900 + i, 1, 1, jours_avant=30 + i * 10))
    hist.upsert_matchs(db, matchs)


def _pick(categorie, selection, cote, proba, edge, ligne=2.5):
    return {"categorie": categorie, "marche": f"{categorie} ({ligne})", "marche_affichage": f"{categorie} ({ligne})",
            "handicap": ligne, "selection": selection, "cote": cote, "proba_modele_pct": proba, "edge_pct": edge}


def _candidat(match, pick, af_home_id=HOME_ID, af_away_id=AWAY_ID):
    return {"match": match, "pick": pick, "af_home_id": af_home_id, "af_away_id": af_away_id,
            "competition_id": 1, "date_iso": datetime.now(timezone.utc).isoformat()}


def test_marche_mappe_avec_historique_suffisant_produit_une_vraie_comparaison():
    with SessionLocal() as db:
        _peupler_historique_suffisant(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9, 55.0, 2.0))]}
        resultats = comparer_candidats(db, pool)
    assert len(resultats) == 1
    r = resultats[0]
    assert r["proba_bet_agent_pct"] == 55.0
    assert r["cote_bookmaker"] == 1.9
    assert r["cote_juste"] == round(1 / 0.55, 3)
    assert r["proba_moteur_pct"] is not None  # le moteur a pu prédire : historique suffisant
    assert r["modele_moteur"] == "buts_total"
    assert r["calibration"] == "non_calibree"  # jamais fabriquée (demande explicite)
    assert r["decision_moteur"] in ("retenu (proba >= seuil)", "rejeté (proba < seuil)")


def test_historique_insuffisant_marque_indisponible_jamais_invente():
    with SessionLocal() as db:
        # Aucun hist_matchs peuplé pour ces équipes.
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9, 55.0, 2.0))]}
        resultats = comparer_candidats(db, pool)
    r = resultats[0]
    assert r["proba_moteur_pct"] is None
    assert "historique insuffisant" in r["decision_moteur"]
    assert "home=0" in r["decision_moteur"] and "away=0" in r["decision_moteur"]


def test_marche_non_mappe_signale_sans_deviner():
    with SessionLocal() as db:
        _peupler_historique_suffisant(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Winning Margin Full Time", "1-0", 6.0, 12.0, 5.0))]}
        resultats = comparer_candidats(db, pool)
    r = resultats[0]
    assert r["proba_moteur_pct"] is None
    assert "non mappé" in r["decision_moteur"]


def test_equipe_api_football_non_identifiee_signalee():
    with SessionLocal() as db:
        _peupler_historique_suffisant(db)
        c = _candidat("H vs A", _pick("Total", "Over", 1.9, 55.0, 2.0), af_home_id=None, af_away_id=None)
        pool = {"H vs A": [c]}
        resultats = comparer_candidats(db, pool)
    r = resultats[0]
    assert r["proba_moteur_pct"] is None
    assert "équipe API-Football non identifiée" in r["decision_moteur"]


def test_jamais_de_selection_ni_de_texte_telegram_touches():
    # La comparaison ne renvoie que des champs d'information : aucune clé "selections"/
    # "coupon"/"texte" ne doit apparaître dans le résultat.
    with SessionLocal() as db:
        _peupler_historique_suffisant(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9, 55.0, 2.0))]}
        resultats = comparer_candidats(db, pool)
    cles_interdites = {"selections", "coupon", "texte", "telegram"}
    assert not (cles_interdites & set(resultats[0].keys()))


def test_doublons_de_candidat_compares_une_seule_fois():
    with SessionLocal() as db:
        _peupler_historique_suffisant(db)
        pick = _pick("Total", "Over", 1.9, 55.0, 2.0)
        pool = {"H vs A": [_candidat("H vs A", pick), _candidat("H vs A", dict(pick))]}
        resultats = comparer_candidats(db, pool)
    assert len(resultats) == 1
