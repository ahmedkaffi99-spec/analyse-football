"""Tests de l'identification shadow (shadow_identification.py) : 0 appel réseau — données
synthétiques uniquement, vérifie le filtrage pays (faux positifs) et l'exigence de cotes
réelles + correspondance API-Football fiable avant d'accepter un candidat."""

from shadow_identification import identifier_candidats


def _fixture_op(tournoi, pays, home, away, fixture_id="fx", has_odds=True, statut="Pre-Game"):
    return {"hasOdds": has_odds, "statusName": statut, "tournamentName": tournoi,
            "categoryName": pays, "participant1Name": home, "participant2Name": away,
            "fixtureId": fixture_id, "startTime": "2026-10-15T15:00:00Z"}


def _fixture_af(home, away, fixture_id=1001, league_id=39):
    return {"teams": {"home": {"name": home, "id": 1}, "away": {"name": away, "id": 2}},
            "league": {"id": league_id, "name": "x", "season": 2026},
            "fixture": {"id": fixture_id, "date": "2026-10-15T15:00:00+00:00"}}


def test_candidat_valide_identifie():
    candidats = identifier_candidats(
        [_fixture_op("Premier League", "England", "Arsenal", "Chelsea")],
        [_fixture_af("Arsenal", "Chelsea")])
    assert len(candidats) == 1
    assert candidats[0]["fixture_id_api_football"] == 1001


def test_faux_positif_pays_exclu():
    # Une "Premier League" existe aussi au Liban — le mot-clé seul ne suffit pas.
    candidats = identifier_candidats(
        [_fixture_op("Premier League", "Lebanon", "ClubX", "ClubY")],
        [_fixture_af("ClubX", "ClubY")])
    assert candidats == []


def test_match_sans_cote_reelle_exclu():
    candidats = identifier_candidats(
        [_fixture_op("Premier League", "England", "Arsenal", "Chelsea", has_odds=False)],
        [_fixture_af("Arsenal", "Chelsea")])
    assert candidats == []


def test_sans_correspondance_api_football_fiable_exclu():
    candidats = identifier_candidats(
        [_fixture_op("Premier League", "England", "Arsenal", "Chelsea")],
        [_fixture_af("Équipe totalement différente", "Une autre")])
    assert candidats == []


def test_un_seul_candidat_par_championnat_par_defaut():
    candidats = identifier_candidats(
        [_fixture_op("Premier League", "England", "Arsenal", "Chelsea", fixture_id="fx1"),
         _fixture_op("Premier League", "England", "Liverpool", "Everton", fixture_id="fx2")],
        [_fixture_af("Arsenal", "Chelsea", fixture_id=1001), _fixture_af("Liverpool", "Everton", fixture_id=1002)],
        max_par_championnat=1)
    assert len(candidats) == 1


def test_cinq_championnats_cibles_bien_couverts():
    fixtures_op = [
        _fixture_op("Premier League", "England", "A", "B", fixture_id="fx1"),
        _fixture_op("La Liga", "Spain", "C", "D", fixture_id="fx2"),
        _fixture_op("Serie A", "Italy", "E", "F", fixture_id="fx3"),
        _fixture_op("Bundesliga", "Germany", "G", "H", fixture_id="fx4"),
        _fixture_op("Ligue 1", "France", "I", "J", fixture_id="fx5"),
    ]
    fixtures_af = [_fixture_af(h, a, fixture_id=1000 + i)
                  for i, (h, a) in enumerate([("A", "B"), ("C", "D"), ("E", "F"), ("G", "H"), ("I", "J")])]
    candidats = identifier_candidats(fixtures_op, fixtures_af)
    assert len(candidats) == 5
    assert {c["championnat"] for c in candidats} == {"Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"}
