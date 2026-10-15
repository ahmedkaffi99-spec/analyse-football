"""Tests dédiés du 15/10/2026 : exclusion des candidats bet_agent (Poisson) sur les marchés
surdispersés (tirs/corners/cartons/fautes/hors-jeux), où seules les prédictions moteur
(binomiale négative) sont fiables — voir docstring de moteur_central_run.py pour le
raisonnement complet (constat réel : coupons dominés par "Total Tirs Under", taux de réussite
faible malgré un edge apparent élevé).

Complétés le 15/10/2026 (même jour, vérification pas-à-pas du run 146 réel) : le filtre
compare `categorie` (libellé français, ex: "Total Tirs"), JAMAIS `marche` (nom brut du
bookmaker, ex: "Shots - Over Under Full Time (26.5)") — un bug réel du premier correctif,
qui ne retirait STRICTEMENT RIEN en production parce qu'il comparait le mauvais champ (voir
test_categorie_correcte_meme_si_marche_brute_ne_matche_pas_les_prefixes, qui aurait été vert
à tort avec l'ancien code puisque la correspondance se faisait sur `marche`, jamais présente
dans le pool réel sous cette forme)."""
import sys
from pathlib import Path

_RACINE_DEPOT = str(Path(__file__).resolve().parents[2])
if _RACINE_DEPOT not in sys.path:
    sys.path.insert(0, _RACINE_DEPOT)

from moteur_central.score_central import CandidatCentral  # noqa: E402

from app.services.moteur_central_run import _exclure_bet_agent_marches_surdisperses  # noqa: E402


def _candidat(match, categorie, responsable, marche=None, selection="over", cote=1.8, proba=70.0):
    return CandidatCentral(match=match, marche=marche or f"{categorie} (brut)", categorie=categorie,
                           selection=selection, cote=cote, moteur_responsable=responsable, proba_pct=proba)


def test_bet_agent_total_tirs_exclu():
    pool = [_candidat("A vs B", "Total Tirs", "bet_agent", marche="Shots - Over Under Full Time (28.5)")]
    assert _exclure_bet_agent_marches_surdisperses(pool) == []


def test_moteur_total_tirs_conserve():
    c = _candidat("A vs B", "Total Tirs", "moteur", marche="Shots - Over Under Full Time (28.5)")
    assert _exclure_bet_agent_marches_surdisperses([c]) == [c]


def test_bet_agent_total_corners_et_cartons_exclus():
    pool = [
        _candidat("A vs B", "Total Corners", "bet_agent", marche="Corners - Over Under Full Time (9.5)"),
        _candidat("A vs B", "Total Cartons", "bet_agent", marche="Yellow Cards - Over Under Full Time (3.5)"),
        _candidat("A vs B", "Total Cartons Équipe 1", "bet_agent", marche="Yellow Cards - Over Under Team 1 (1.5)"),
        _candidat("A vs B", "Total Fautes", "bet_agent", marche="Fouls - Over Under Full Time (22.5)"),
        _candidat("A vs B", "Total Hors-jeux", "bet_agent", marche="Offsides - Over Under Full Time (2.5)"),
    ]
    assert _exclure_bet_agent_marches_surdisperses(pool) == []


def test_bet_agent_buts_et_btts_jamais_exclus():
    # Non-régression : Poisson reste adapté aux buts (événements rares, pas surdispersées) —
    # ces marchés ne doivent jamais être touchés par cette exclusion.
    pool = [
        _candidat("A vs B", "Total", "bet_agent", marche="Over Under Full Time (2.5)"),
        _candidat("A vs B", "Total Équipe 1", "bet_agent", marche="Over Under Team 1 (1.5)"),
        _candidat("A vs B", "BTTS", "bet_agent", marche="Both Teams To Score", selection="oui"),
        _candidat("A vs B", "Double Chance", "bet_agent", marche="Double Chance", selection="1x"),
    ]
    assert _exclure_bet_agent_marches_surdisperses(pool) == pool


def test_melange_garde_seulement_les_candidats_valides():
    valide_moteur = _candidat("A vs B", "Total Tirs", "moteur", marche="Shots - Over Under Full Time (28.5)")
    valide_buts = _candidat("C vs D", "Total", "bet_agent", marche="Over Under Full Time (2.5)")
    exclu = _candidat("A vs B", "Total Corners", "bet_agent", marche="Corners - Over Under Full Time (9.5)")
    resultat = _exclure_bet_agent_marches_surdisperses([valide_moteur, valide_buts, exclu])
    assert resultat == [valide_moteur, valide_buts]


def test_categorie_correcte_meme_si_marche_brute_ne_matche_pas_les_prefixes():
    """Le cas RÉEL du run 146 : `marche` (brute) ne commence jamais par "Total Tirs" (c'est le
    nom du bookmaker, "Shots - ..."), seule `categorie` ("Total Tirs") permet l'exclusion."""
    c = _candidat("A vs B", "Total Tirs", "bet_agent", marche="Shots - Over Under Full Time (32.5)")
    assert not c.marche.startswith("Total Tirs")  # confirme le bug : `marche` seul n'aurait rien exclu
    assert _exclure_bet_agent_marches_surdisperses([c]) == []


def test_categorie_absente_jamais_exclu_par_defaut():
    # Un candidat sans categorie connue (ne devrait jamais arriver en pratique, voir
    # construire_candidats) n'est jamais supposé surdispersé — pas d'exclusion par excès de
    # prudence sur une donnée manquante.
    c = CandidatCentral(match="A vs B", marche="Shots - Over Under Full Time (28.5)", selection="under",
                        cote=1.8, moteur_responsable="bet_agent", proba_pct=70.0, categorie=None)
    assert _exclure_bet_agent_marches_surdisperses([c]) == [c]
