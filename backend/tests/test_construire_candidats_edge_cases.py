"""Tests de non-régression des cas limites de
backend.app.services.decision_centrale.construire_candidats — documentent le comportement
RÉEL observé du code (pas une spécification de ce qu'il "devrait" faire). Volontairement
indépendants de backend/tests/test_decision_centrale.py (pas de duplication, pas de DB : la
fonction est pure, elle ne touche jamais la base)."""

from app.services.decision_centrale import construire_candidats
from moteur_central.config import ConfigCentrale

CFG = ConfigCentrale.depuis_env()
HIST_VIDE = {"bet_agent": {}, "moteur": {}}


def _pick(selection="Over", cote=1.9, marche="Total (2.5)", proba=55.0, edge=2.0):
    return {"marche": marche, "marche_affichage": marche, "selection": selection,
            "cote": cote, "proba_modele_pct": proba, "edge_pct": edge}


def _candidat(pick, competition="Ligue Test", fixture_id="fxABC"):
    return {"pick": pick, "competition": competition, "fixture_id_oddspapi": fixture_id}


def test_pool_vide_et_comparaison_vide_renvoie_deux_listes_vides():
    candidats_ba, candidats_mo = construire_candidats({}, [], HIST_VIDE, CFG)
    assert candidats_ba == []
    assert candidats_mo == []


def test_pick_sans_cote_est_silencieusement_ignore():
    pick = _pick()
    del pick["cote"]
    pool = {"H vs A": [_candidat(pick)]}
    candidats_ba, candidats_mo = construire_candidats(pool, [], HIST_VIDE, CFG)
    assert candidats_ba == []
    assert candidats_mo == []


def test_pick_avec_cote_none_est_silencieusement_ignore():
    pick = _pick(cote=None)
    pool = {"H vs A": [_candidat(pick)]}
    candidats_ba, candidats_mo = construire_candidats(pool, [], HIST_VIDE, CFG)
    assert candidats_ba == []
    assert candidats_mo == []


def test_pick_sans_marche_ni_marche_affichage_est_silencieusement_ignore():
    pick = _pick()
    del pick["marche"]
    del pick["marche_affichage"]
    pool = {"H vs A": [_candidat(pick)]}
    candidats_ba, candidats_mo = construire_candidats(pool, [], HIST_VIDE, CFG)
    assert candidats_ba == []
    assert candidats_mo == []


def test_pick_avec_marche_none_et_marche_affichage_none_est_silencieusement_ignore():
    pick = _pick()
    pick["marche"] = None
    pick["marche_affichage"] = None
    pool = {"H vs A": [_candidat(pick)]}
    candidats_ba, candidats_mo = construire_candidats(pool, [], HIST_VIDE, CFG)
    assert candidats_ba == []
    assert candidats_mo == []


def test_deux_candidats_identiques_meme_match_marche_selection_sont_dedupliques():
    pick1 = _pick()
    pick2 = _pick()  # même match/marché/sélection -> doit être dédupliqué via `deja_vus`
    pool = {"H vs A": [_candidat(pick1), _candidat(pick2)]}
    candidats_ba, _ = construire_candidats(pool, [], HIST_VIDE, CFG)
    assert len(candidats_ba) == 1


def test_candidats_differant_seulement_par_la_cote_sont_quand_meme_dedupliques():
    # La clé de dédup est (match, marche, selection) : la cote n'en fait PAS partie, donc deux
    # picks avec des cotes différentes mais le même match/marché/sélection sont dédupliqués
    # (seul le premier rencontré est conservé) — comportement réel, pas une évidence.
    pick1 = _pick(cote=1.9)
    pick2 = _pick(cote=2.5)
    pool = {"H vs A": [_candidat(pick1), _candidat(pick2)]}
    candidats_ba, _ = construire_candidats(pool, [], HIST_VIDE, CFG)
    assert len(candidats_ba) == 1
    assert candidats_ba[0].cote == 1.9  # le premier rencontré gagne


def test_comparaison_sans_entree_correspondante_ne_cree_aucun_candidat_moteur():
    pick = _pick(selection="Over", marche="Total (2.5)")
    pool = {"H vs A": [_candidat(pick)]}
    # Comparaison non vide mais pour une clé différente (autre sélection) -> ne doit jamais
    # matcher et donc ne jamais produire un candidat moteur avec une proba inventée.
    comparaison = [{"match": "H vs A", "marche_bet_agent": "Total (2.5)", "selection": "Under",
                    "proba_moteur_pct": 60.0, "edge_moteur_pct": 5.0}]
    candidats_ba, candidats_mo = construire_candidats(pool, comparaison, HIST_VIDE, CFG)
    assert len(candidats_ba) == 1
    assert candidats_mo == []


def test_comparaison_avec_proba_moteur_pct_none_ne_cree_aucun_candidat_moteur():
    pick = _pick(selection="Over", marche="Total (2.5)")
    pool = {"H vs A": [_candidat(pick)]}
    # La clé correspond exactement, mais proba_moteur_pct est explicitement None : la condition
    # `comp.get("proba_moteur_pct") is not None` doit empêcher la création du candidat moteur.
    comparaison = [{"match": "H vs A", "marche_bet_agent": "Total (2.5)", "selection": "Over",
                    "proba_moteur_pct": None, "edge_moteur_pct": None}]
    candidats_ba, candidats_mo = construire_candidats(pool, comparaison, HIST_VIDE, CFG)
    assert len(candidats_ba) == 1
    assert candidats_mo == []


def test_comparaison_avec_proba_moteur_pct_valide_cree_bien_un_candidat_moteur():
    # Contraste positif pour les deux cas précédents : avec une clé correspondante et une
    # proba_moteur_pct non-None, un candidat moteur doit bien être créé.
    pick = _pick(selection="Over", marche="Total (2.5)")
    pool = {"H vs A": [_candidat(pick)]}
    comparaison = [{"match": "H vs A", "marche_bet_agent": "Total (2.5)", "selection": "Over",
                    "proba_moteur_pct": 60.0, "edge_moteur_pct": 5.0}]
    candidats_ba, candidats_mo = construire_candidats(pool, comparaison, HIST_VIDE, CFG)
    assert len(candidats_ba) == 1
    assert len(candidats_mo) == 1
    assert candidats_mo[0].proba_pct == 60.0
    assert candidats_mo[0].moteur_responsable == "moteur"


def test_historique_vide_pour_les_deux_moteurs_donne_disponible_false_sans_erreur():
    pick = _pick(selection="Over", marche="Total (2.5)")
    pool = {"H vs A": [_candidat(pick)]}
    comparaison = [{"match": "H vs A", "marche_bet_agent": "Total (2.5)", "selection": "Over",
                    "proba_moteur_pct": 60.0, "edge_moteur_pct": 5.0}]
    candidats_ba, candidats_mo = construire_candidats(pool, comparaison, HIST_VIDE, CFG)
    assert candidats_ba[0].historique_marche == {
        "disponible": False, "n": 0, "n_min": CFG.n_min_fiable,
        "raison": "aucune capture jugée pour ce marché",
    }
    assert candidats_mo[0].historique_marche == {
        "disponible": False, "n": 0, "n_min": CFG.n_min_fiable,
        "raison": "aucune capture jugée pour ce marché",
    }
