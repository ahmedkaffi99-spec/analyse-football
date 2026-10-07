"""Tests du backfill historique (moteur d'analyse) : aucun appel réseau, cd._appel_statistiques_
fixture et SESSION.get sont remplacés par des doubles."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models_historique import HistMatch
from app.services import historique as hist
from app.services import pipeline


def _fixture(fixture_id, statut="FT", home_id=1, away_id=2, home_g=2, away_g=1,
            league_id=39, saison=2024, date="2024-09-14T15:00:00+00:00"):
    return {"fixture": {"id": fixture_id, "date": date, "referee": "M. Dupont", "status": {"short": statut}},
            "league": {"id": league_id, "name": "Premier League", "season": saison},
            "teams": {"home": {"id": home_id, "name": "Home FC"}, "away": {"id": away_id, "name": "Away FC"}},
            "goals": {"home": home_g if statut == "FT" else None, "away": away_g if statut == "FT" else None}}


def _blocs_stats(home_id, away_id):
    return [
        {"team": {"id": home_id, "name": "Home FC"}, "statistics": [
            {"type": "Corner Kicks", "value": 6}, {"type": "Yellow Cards", "value": 2},
            {"type": "Ball Possession", "value": "55%"}]},
        {"team": {"id": away_id, "name": "Away FC"}, "statistics": [
            {"type": "Corner Kicks", "value": 4}, {"type": "Yellow Cards", "value": 3},
            {"type": "Ball Possession", "value": "45%"}]},
    ]


@pytest.fixture
def cd():
    return pipeline.modules()[0]


def test_fixture_vers_match_sans_stats_si_pas_termine(cd):
    m = hist.fixture_vers_match(_fixture(1, statut="NS"), cd, avec_stats=True)
    assert m["home_score"] is None and m["away_score"] is None and m["stats"] is None


def test_fixture_vers_match_avec_stats_si_termine(cd, monkeypatch):
    monkeypatch.setattr(cd, "_appel_statistiques_fixture", lambda fid: _blocs_stats(1, 2))
    m = hist.fixture_vers_match(_fixture(1), cd, avec_stats=True)
    assert m["home_score"] == 2 and m["away_score"] == 1
    assert m["stats"]["home"]["corners"] == 6 and m["stats"]["away"]["corners"] == 4
    assert m["stats"]["home"]["possession"] == 55.0  # "%" nettoyé par cd._valeur_stat


def test_fixture_vers_match_stats_indisponibles_jamais_inventees(cd, monkeypatch):
    monkeypatch.setattr(cd, "_appel_statistiques_fixture", lambda fid: (_ for _ in ()).throw(RuntimeError("quota")))
    m = hist.fixture_vers_match(_fixture(1), cd, avec_stats=True)
    assert m["home_score"] == 2  # le score reste connu
    assert m["stats"] is None    # mais aucune statistique inventée


def test_upsert_idempotent_et_mise_a_jour():
    with SessionLocal() as db:
        m1 = hist.fixture_vers_match(_fixture(1, statut="NS"), None, avec_stats=False)
        assert hist.upsert_matchs(db, [m1]) == 1
        assert db.get(HistMatch, 1).statut == "NS"

        m2 = hist.fixture_vers_match(_fixture(1, statut="FT"), None, avec_stats=False)
        assert hist.upsert_matchs(db, [m2]) == 1
        assert db.query(HistMatch).count() == 1  # pas de doublon
        relu = db.get(HistMatch, 1)
        assert relu.statut == "FT" and relu.home_score == 2


def test_charger_matchs_filtre_par_competition_et_saison():
    with SessionLocal() as db:
        hist.upsert_matchs(db, [
            hist.fixture_vers_match(_fixture(1, league_id=39, saison=2023), None, avec_stats=False),
            hist.fixture_vers_match(_fixture(2, league_id=39, saison=2024), None, avec_stats=False),
            hist.fixture_vers_match(_fixture(3, league_id=61, saison=2024), None, avec_stats=False),
        ])
        tous = hist.charger_matchs(db)
        assert len(tous) == 3
        ligue_39 = hist.charger_matchs(db, competition_id=39)
        assert {m["match_id"] for m in ligue_39} == {1, 2}
        saison_2024 = hist.charger_matchs(db, saisons=[2024])
        assert {m["match_id"] for m in saison_2024} == {2, 3}
        # format directement exploitable par moteur.features.Historique (son en_datetime()
        # traite un datetime naïf comme UTC — SQLite ne conserve pas le fuseau, Postgres oui).
        assert isinstance(tous[0]["date"], datetime)


def test_backfill_ligue_saison_respecte_la_limite_de_stats(monkeypatch):
    fixtures = [_fixture(i, statut="FT", home_id=10, away_id=20) for i in range(1, 6)]
    appels = []

    def fausse_requete(league_id, season):
        return fixtures

    def fausses_stats(fixture_id):
        appels.append(fixture_id)
        return _blocs_stats(10, 20)

    monkeypatch.setattr(hist, "_fixtures_ligue_saison", lambda cd, lid, s: fausse_requete(lid, s))
    monkeypatch.setattr(pipeline.modules()[0], "_appel_statistiques_fixture", fausses_stats)

    with SessionLocal() as db:
        resultat = hist.backfill_ligue_saison(db, 39, 2024, avec_stats=True, limite_appels_stats=2)
        assert resultat == {"ligue": 39, "saison": 2024, "matchs": 5, "termines": 5, "avec_stats": 2}
        assert len(appels) == 2
        assert db.query(HistMatch).count() == 5


def test_backfill_leve_une_erreur_api_football_explicite(monkeypatch):
    def reponse_en_erreur(*a, **kw):
        return SimpleNamespace(json=lambda: {"errors": {"requests": "quota dépassé"}})

    cd, _, _ = pipeline.modules()
    monkeypatch.setattr(cd.SESSION, "get", reponse_en_erreur)
    monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)
    with pytest.raises(RuntimeError, match="quota"):
        hist._fixtures_ligue_saison(cd, 39, 2024)
