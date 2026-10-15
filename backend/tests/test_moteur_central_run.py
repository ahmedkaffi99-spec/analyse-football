"""Tests dédiés du 15/10/2026 : exclusion des candidats bet_agent (Poisson) sur les marchés
surdispersés (tirs/corners/cartons/fautes/hors-jeux), où seules les prédictions moteur
(binomiale négative) sont fiables — voir docstring de moteur_central_run.py pour le
raisonnement complet (constat réel : coupons dominés par "Total Tirs Under", taux de réussite
faible malgré un edge apparent élevé)."""
import sys
from pathlib import Path

_RACINE_DEPOT = str(Path(__file__).resolve().parents[2])
if _RACINE_DEPOT not in sys.path:
    sys.path.insert(0, _RACINE_DEPOT)

from moteur_central.score_central import CandidatCentral  # noqa: E402

from app.services.moteur_central_run import _exclure_bet_agent_marches_surdisperses  # noqa: E402


def _candidat(match, marche, responsable, selection="over", cote=1.8, proba=70.0):
    return CandidatCentral(match=match, marche=marche, selection=selection, cote=cote,
                           moteur_responsable=responsable, proba_pct=proba)


def test_bet_agent_total_tirs_exclu():
    pool = [_candidat("A vs B", "Total Tirs (28.5)", "bet_agent")]
    assert _exclure_bet_agent_marches_surdisperses(pool) == []


def test_moteur_total_tirs_conserve():
    c = _candidat("A vs B", "Total Tirs (28.5)", "moteur")
    assert _exclure_bet_agent_marches_surdisperses([c]) == [c]


def test_bet_agent_total_corners_et_cartons_exclus():
    pool = [
        _candidat("A vs B", "Total Corners (9.5)", "bet_agent"),
        _candidat("A vs B", "Total Cartons (3.5)", "bet_agent"),
        _candidat("A vs B", "Total Cartons Équipe 1 (1.5)", "bet_agent"),
        _candidat("A vs B", "Total Fautes (22.5)", "bet_agent"),
        _candidat("A vs B", "Total Hors-jeux (2.5)", "bet_agent"),
    ]
    assert _exclure_bet_agent_marches_surdisperses(pool) == []


def test_bet_agent_buts_et_btts_jamais_exclus():
    # Non-régression : Poisson reste adapté aux buts (événements rares, pas surdispersés) —
    # ces marchés ne doivent jamais être touchés par cette exclusion.
    pool = [
        _candidat("A vs B", "Total (2.5)", "bet_agent"),
        _candidat("A vs B", "Total Équipe 1 (1.5)", "bet_agent"),
        _candidat("A vs B", "BTTS", "bet_agent", selection="oui"),
        _candidat("A vs B", "Double Chance", "bet_agent", selection="1x"),
    ]
    assert _exclure_bet_agent_marches_surdisperses(pool) == pool


def test_melange_garde_seulement_les_candidats_valides():
    valide_moteur = _candidat("A vs B", "Total Tirs (28.5)", "moteur")
    valide_buts = _candidat("C vs D", "Total (2.5)", "bet_agent")
    exclu = _candidat("A vs B", "Total Corners (9.5)", "bet_agent")
    resultat = _exclure_bet_agent_marches_surdisperses([valide_moteur, valide_buts, exclu])
    assert resultat == [valide_moteur, valide_buts]
