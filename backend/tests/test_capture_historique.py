"""Tests de la capture PROSPECTIVE des cotes dans hist_cotes (capture_historique.py) :
aucune cote fabriquée, aucun doublon dans la même journée, la sélection/les probabilités
bet_agent ne sont jamais touchées (lecture seule du pool), et le jugement différé réutilise
les mêmes règles que verification.py."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Run
from app.models_historique import HistCote
from app.services import historique as hist
from app.services.capture_historique import capturer_predictions, juger_cotes_en_attente

HOME_ID, AWAY_ID = 100, 200


def _run(db, lance_le=None):
    run = Run(source="api", statut="en_cours", lance_le=lance_le or datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    return run


def _pick(categorie, selection, cote, proba=55.0, edge=2.0, ligne=2.5, marche_affichage=None):
    return {"categorie": categorie, "marche": marche_affichage or f"{categorie} ({ligne})",
            "marche_affichage": marche_affichage or f"{categorie} ({ligne})", "handicap": ligne,
            "selection": selection, "cote": cote, "proba_modele_pct": proba, "edge_pct": edge}


def _candidat(match, pick, fixture_id_oddspapi="fxABC", home_nom="H", away_nom="A"):
    return {"match": match, "pick": pick, "home_nom": home_nom, "away_nom": away_nom,
            "fixture_id_oddspapi": fixture_id_oddspapi, "af_home_id": HOME_ID, "af_away_id": AWAY_ID,
            "competition_id": 1, "competition": "Ligue Test",
            "date_iso": datetime.now(timezone.utc).isoformat(), "fixture_id_api_football": 999}


def test_capture_une_ligne_par_candidat_avec_cote_reelle():
    with SessionLocal() as db:
        run = _run(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        n = capturer_predictions(db, run, pool)
        assert n == 1
        lignes = list(db.scalars(select(HistCote)))
        assert len(lignes) == 1
        ligne = lignes[0]
        assert ligne.cote == 1.9
        assert ligne.proba_bet_agent_pct == 55.0
        assert ligne.edge_bet_agent_pct == 2.0
        assert ligne.domicile == "H" and ligne.exterieur == "A"
        assert ligne.run_id == run.id
        assert ligne.resultat is None  # pas encore jugée


def test_aucune_cote_fabriquee_candidat_sans_cote_ignore():
    with SessionLocal() as db:
        run = _run(db)
        pick_sans_cote = _pick("Total", "Over", cote=None)
        pool = {"H vs A": [_candidat("H vs A", pick_sans_cote)]}
        n = capturer_predictions(db, run, pool)
        assert n == 0
        assert list(db.scalars(select(HistCote))) == []


def test_meme_candidat_revu_le_meme_jour_pas_de_doublon():
    with SessionLocal() as db:
        run1 = _run(db)
        pick = _pick("Total", "Over", 1.9)
        pool = {"H vs A": [_candidat("H vs A", pick)]}
        capturer_predictions(db, run1, pool)

        # Même match/marché/ligne/sélection revu à un passage ultérieur du cron, même jour,
        # même si la cote a légèrement bougé : ne doit PAS être réinséré.
        run2 = _run(db, lance_le=run1.lance_le + timedelta(minutes=30))
        pick_bis = _pick("Total", "Over", 1.95)
        pool2 = {"H vs A": [_candidat("H vs A", pick_bis)]}
        n2 = capturer_predictions(db, run2, pool2)
        assert n2 == 0
        lignes = list(db.scalars(select(HistCote)))
        assert len(lignes) == 1
        assert lignes[0].cote == 1.9  # la première capture n'a jamais été écrasée
        assert lignes[0].run_id == run1.id


def test_meme_candidat_un_autre_jour_est_capture_a_nouveau():
    with SessionLocal() as db:
        run1 = _run(db, lance_le=datetime.now(timezone.utc) - timedelta(days=1))
        pick = _pick("Total", "Over", 1.9)
        pool = {"H vs A": [_candidat("H vs A", pick)]}
        capturer_predictions(db, run1, pool)

        run2 = _run(db, lance_le=datetime.now(timezone.utc))
        pool2 = {"H vs A": [_candidat("H vs A", pick)]}
        n2 = capturer_predictions(db, run2, pool2)
        assert n2 == 1
        assert len(list(db.scalars(select(HistCote)))) == 2


def test_doublons_dans_le_meme_pool_ne_comptes_quune_fois():
    with SessionLocal() as db:
        run = _run(db)
        pick = _pick("Total", "Over", 1.9)
        pool = {"H vs A": [_candidat("H vs A", pick), _candidat("H vs A", dict(pick))]}
        n = capturer_predictions(db, run, pool)
        assert n == 1


def test_capture_un_tres_grand_nombre_de_candidats_sans_depasser_la_limite_de_parametres():
    # Constaté en production le 10/10/2026 (run 124) : un run réel évalue facilement plusieurs
    # milliers de candidats (centaines de marchés x dizaines de matchs) ; un seul INSERT
    # multi-lignes dépassait la limite Postgres de 65535 paramètres et la capture entière
    # échouait silencieusement. 1500 candidats forcent plusieurs lots (TAILLE_LOT=1000).
    with SessionLocal() as db:
        run = _run(db)
        pool = {}
        for i in range(1500):
            match = f"M{i} vs X{i}"
            pool[match] = [_candidat(match, _pick("Total", "Over", 1.9), fixture_id_oddspapi=f"fx{i}")]
        n = capturer_predictions(db, run, pool)
        assert n == 1500
        assert db.scalar(select(HistCote.id).limit(1)) is not None
        total = len(list(db.scalars(select(HistCote))))
        assert total == 1500


def test_proba_moteur_capturee_si_disponible_sinon_none_jamais_invente():
    with SessionLocal() as db:
        # Aucun hist_matchs peuplé : le moteur n'a pas d'historique suffisant -> None, jamais
        # une probabilité inventée. comparer_candidats échoue proprement ou renvoie None ; la
        # capture bet_agent ne doit jamais être bloquée pour autant.
        run = _run(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        capturer_predictions(db, run, pool)
        ligne = db.scalars(select(HistCote)).first()
        assert ligne.proba_moteur_pct is None
        assert ligne.modele_moteur is None


def test_capture_ne_modifie_jamais_le_pick_dorigine():
    with SessionLocal() as db:
        run = _run(db)
        pick = _pick("Total", "Over", 1.9)
        pick_avant = dict(pick)
        pool = {"H vs A": [_candidat("H vs A", pick)]}
        capturer_predictions(db, run, pool)
        assert pick == pick_avant  # lecture seule, jamais une mutation du pick bet_agent


def _match_hist(match_id, home_id, away_id, home_g, away_g, jours_avant, statut="FT"):
    date_m = (datetime.now(timezone.utc) - timedelta(days=jours_avant)).isoformat()
    return {"match_id": match_id, "date": date_m, "competition_id": 1, "competition": "Ligue Test",
            "saison": 2025, "home_id": home_id, "home": "H", "away_id": away_id, "away": "A",
            "arbitre": None, "statut": statut, "home_score": home_g, "away_score": away_g, "stats": None}


class _FixtureAF:
    """Double minimal imitant la forme attendue par vr.trouver_fixture_api_football &co."""

    def __init__(self, home, away, statut, home_g, away_g):
        self.home, self.away = home, away
        self.statut, self.home_g, self.away_g = statut, home_g, away_g

    def vers_brut(self):
        return {"teams": {"home": {"name": self.home}, "away": {"name": self.away}},
                "fixture": {"status": {"short": self.statut}}, "goals": {"home": self.home_g, "away": self.away_g}}


def test_juger_cotes_en_attente_total_gagne_via_api_football(monkeypatch):
    with SessionLocal() as db:
        run = _run(db)
        pick = _pick("Total", "Over", 1.9, ligne=2.5)
        pool = {"Home FC vs Away FC": [_candidat("Home FC vs Away FC", pick, home_nom="Home FC", away_nom="Away FC")]}
        capturer_predictions(db, run, pool)

        from app.services import pipeline

        cd, _, vr = pipeline.modules()
        fx = _FixtureAF("Home FC", "Away FC", "FT", 2, 1).vers_brut()  # total = 3 > 2.5 -> Over gagne
        monkeypatch.setattr(vr, "recuperer_fixtures_api_football_du_jour", lambda: [fx])

        resultat = juger_cotes_en_attente(db)
        assert resultat["jugees"] == 1
        ligne = db.scalars(select(HistCote)).first()
        assert ligne.resultat == "gagne"
        assert ligne.juge_le is not None


def test_juger_cotes_en_attente_match_pas_termine_laisse_en_attente(monkeypatch):
    with SessionLocal() as db:
        run = _run(db)
        pick = _pick("Total", "Over", 1.9, ligne=2.5)
        pool = {"Home FC vs Away FC": [_candidat("Home FC vs Away FC", pick, home_nom="Home FC", away_nom="Away FC")]}
        capturer_predictions(db, run, pool)

        from app.services import pipeline

        _, _, vr = pipeline.modules()
        monkeypatch.setattr(vr, "recuperer_fixtures_api_football_du_jour", lambda: [])
        monkeypatch.setattr(vr, "recuperer_fixtures_du_jour", lambda: {})

        resultat = juger_cotes_en_attente(db)
        assert resultat["pas_termine"] == 1
        ligne = db.scalars(select(HistCote)).first()
        assert ligne.resultat is None
