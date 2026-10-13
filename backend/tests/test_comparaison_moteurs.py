"""Tests de la comparaison parallèle bet_agent / moteur (comparaison_moteurs.py) : aucun appel
réseau, aucune sélection ni texte Telegram touchés — uniquement la production des 9 champs de
comparaison, avec repli honnête ("indisponible"/"non mappé") quand les données manquent."""

from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.services import historique as hist
from app.services.comparaison_moteurs import MARCHE_MOTEUR_PAR_CATEGORIE, _marche_moteur, comparer_candidats

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


class TestCouvertureElargie13Octobre2026:
    """Demande explicite : "augmenter la couverture du moteur" — corners/cartons/tirs
    (modèles 8-10 de moteur/modeles/registre.py, déjà couverts par les 4 saisons des 5
    championnats en base) étaient exclus de MARCHE_MOTEUR_PAR_CATEGORIE avant cet
    élargissement, alors qu'ils dominent en volume le pool réel de bet_agent."""

    def test_total_corners_mappe(self):
        assert _marche_moteur("Total Corners", "Over") == ("corners_total", "over")
        assert _marche_moteur("Total Corners", "Under") == ("corners_total", "under")

    def test_total_cartons_et_par_equipe_mappes(self):
        assert _marche_moteur("Total Cartons", "Over") == ("cartons_total", "over")
        assert _marche_moteur("Total Cartons Équipe 1", "Over") == ("cartons_equipe1", "over")
        assert _marche_moteur("Total Cartons Équipe 2", "Under") == ("cartons_equipe2", "under")

    def test_total_tirs_mappe(self):
        assert _marche_moteur("Total Tirs", "Over") == ("tirs_total", "over")

    def test_marches_pre_existants_toujours_mappes(self):
        # Non-régression : l'élargissement ne doit jamais retirer un mapping déjà validé.
        assert _marche_moteur("Total", "Over") == ("buts_total", "over")
        assert _marche_moteur("BTTS", "Yes") == ("btts", "oui")
        assert _marche_moteur("Double Chance", "1X") == ("double_chance", "1X")

    def test_marche_corners_avec_historique_suffisant_produit_une_vraie_comparaison(self):
        with SessionLocal() as db:
            _peupler_historique_suffisant(db)
            pool = {"H vs A": [_candidat("H vs A", _pick("Total Corners", "Over", 1.9, 55.0, 2.0, ligne=9.5))]}
            resultats = comparer_candidats(db, pool)
        r = resultats[0]
        # L'historique suffit (n_matchs >= min_matchs_equipe) : le moteur doit tenter une
        # prédiction, jamais la rejeter pour "marché non mappé" comme avant cet élargissement.
        assert r["decision_moteur"] != "marché non mappé (voir MARCHE_MOTEUR_PAR_CATEGORIE)"

    def test_aucun_marche_existant_ecrase(self):
        # Garde-fou structurel : chaque entrée pré-existante reste présente telle quelle.
        anciennes = {
            ("Total", "over"): ("buts_total", "over"), ("Total", "under"): ("buts_total", "under"),
            ("Total Équipe 1", "over"): ("buts_equipe1", "over"),
            ("Total Équipe 2", "under"): ("buts_equipe2", "under"),
            ("BTTS", "oui"): ("btts", "oui"), ("BTTS", "non"): ("btts", "non"),
            ("Double Chance", "1x"): ("double_chance", "1X"),
        }
        for cle, valeur in anciennes.items():
            assert MARCHE_MOTEUR_PAR_CATEGORIE[cle] == valeur
