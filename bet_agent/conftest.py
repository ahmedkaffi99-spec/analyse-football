import pytest


@pytest.fixture(autouse=True)
def agents_familles_desactives_par_defaut(monkeypatch):
    """Les tests existants du stratège comptent ses appels IA : les agents de famille
    (agents_familles.py) y sont désactivés, et activés explicitement dans leurs propres tests."""
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "0")


@pytest.fixture(autouse=True)
def fourchette_de_cote_par_jambe_neutralisee(monkeypatch):
    """Les tests existants du calcul utilisent des cotes arbitraires (1.08 à 9.0) : la fourchette
    par jambe de production (1.2-1.8, voir ae.COTE_MIN_JAMBE_DEFAUT) y est neutralisée, et testée
    explicitement dans test_fourchette_de_cote_par_jambe_1_2_a_1_8."""
    import analyser_et_envoyer as ae
    monkeypatch.setattr(ae, "COTE_MIN_JAMBE", 0.0)
    monkeypatch.setattr(ae, "COTE_MAX_JAMBE", 0.0)


@pytest.fixture(autouse=True)
def plancher_de_remuneration_neutralise(monkeypatch):
    """Les tests existants du stratège utilisent des cotes totales arbitraires (1.3 à 9) : le plancher de rémunération de production
    (agent_strategie.COTE_TOTALE_MIN_COUPON, 1.60 par défaut) y est neutralisé, et testé explicitement dans test_remuneration_minimale.py."""
    import agent_strategie as st
    monkeypatch.setattr(st, "COTE_TOTALE_MIN_COUPON", 0.0)


@pytest.fixture(autouse=True)
def planchers_des_moteurs_communs_neutralises(monkeypatch):
    """Même raison : les planchers de rémunération partagés par les moteurs central et déterministe (moteur/profils_risque.py) sont neutralisés pour les tests existants."""
    import os
    import sys
    racine = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    if racine not in sys.path:
        sys.path.insert(0, racine)
    from moteur import profils_risque as pr
    monkeypatch.setattr(pr, "COTE_MIN_JAMBE", 0.0)
    monkeypatch.setattr(pr, "COTE_TOTALE_MIN_COUPON", 0.0)
    monkeypatch.setattr(pr, "MAX_JAMBES_REMPLISSAGE", 0)
    import agent_strategie as st
    monkeypatch.setattr(st, "MAX_JAMBES_REMPLISSAGE", 0)   # limite des jambes de remplissage : testée explicitement dans test_ameliorations_07_11.py
    monkeypatch.setenv("FILTRER_MATCHS_COMMENCES", "0")      # les tests existants utilisent des dates fictives : le filtre des matchs commencés est testé à part


@pytest.fixture(autouse=True)
def selection_meme_jour_neutralisee(monkeypatch):
    """Les tests existants de sélection utilisent des dates fictives (2099) : le filtre « matchs du
    jour seulement » (cd.MATCHS_UNIQUEMENT_DU_JOUR) y est désactivé, et testé explicitement dans
    TestSelectionUniquementDuJour."""
    import collecte_donnees as cd
    monkeypatch.setattr(cd, "MATCHS_UNIQUEMENT_DU_JOUR", False)


@pytest.fixture(autouse=True)
def categories_exclues_neutralisees(monkeypatch):
    """Les tests existants du stratège utilisent BTTS, Handicap Asiatique, tirs et corners d'équipe : la liste
    d'exclusion de production (agent_strategie.CATEGORIES_EXCLUES_PAR_DEFAUT) y est neutralisée, et testée
    explicitement dans test_categories_exclues_par_defaut_* (qui retire cette variable)."""
    monkeypatch.setenv("CATEGORIES_EXCLUES", "aucune")


@pytest.fixture(autouse=True)
def telegram_sans_attente(monkeypatch):
    """Les nouvelles tentatives Telegram (429, passerelle, connexion) attendent quelques secondes en production : aucune attente en test."""
    import analyser_et_envoyer as ae
    monkeypatch.setattr(ae, "_pause_telegram", lambda secondes: None)
