"""Spécialistes par marché : non-régression (golden) et contrat d'interface."""

import json
from pathlib import Path

import pytest

from moteur.config import Config
from moteur.features import Historique, construire_features
from moteur.modeles.catalogue import MODELES
from moteur.modeles.registre import predire_match
from moteur.modeles.specialistes import SPECIALISTES, SPECIALISTE_PAR_NUMERO, ContexteMatch
from moteur.tests.simulation import championnat

GOLDEN = Path(__file__).parent / "golden" / "predire_match_v1.json"
CFG_LEGACY = Config(dispersion_corners=0, dispersion_cartons=0, dispersion_tirs=0, dispersion_tirs_cadres=0,
                    dispersion_fautes=0)


@pytest.fixture(scope="module")
def monde():
    matchs, _ = championnat()
    return matchs, Historique(matchs)


def _instantane(monde, cfg):
    matchs, hist = monde
    sortie = []
    for idx in (130, 180, 230, 260):
        for p in predire_match(construire_features(matchs[idx], hist, cfg.fenetre_forme), cfg):
            sortie.append([idx, p.modele, p.nom_modele, p.marche, p.ligne, p.selection,
                           {k: round(v, 12) for k, v in p.issues.items()}, p.parametres])
    return json.loads(json.dumps(sortie))


def test_refactor_identique_a_l_ancien_registre(monde):
    """Les 11 spécialistes reproduisent exactement (valeurs ET ordre) l'ancien predire_match monolithique."""
    assert _instantane(monde, CFG_LEGACY) == json.loads(GOLDEN.read_text())


def test_dispersion_mesuree_ne_touche_que_les_comptages(monde):
    legacy, mesure = _instantane(monde, CFG_LEGACY), _instantane(monde, Config())
    assert len(legacy) == len(mesure)
    for a, b in zip(legacy, mesure):
        if a[1] <= 7:  # buts : inchangés
            assert a == b
    assert any(a != b for a, b in zip(legacy, mesure) if a[1] >= 8)


def test_chaque_modele_a_son_specialiste_et_ses_marches():
    assert sorted(SPECIALISTE_PAR_NUMERO) == sorted(MODELES)
    for s in SPECIALISTES:
        assert s.nom == MODELES[s.numero][0]
        assert set(s.marches) == set(MODELES[s.numero][1])
        assert s.donnees_requises and s.version


def test_specialiste_sans_donnees_ne_predit_rien(monde):
    matchs, hist = monde
    f = construire_features(matchs[0], hist, 10)  # premier match : aucun historique
    ctx = ContexteMatch(f, Config())
    lignes = {"buts_total": [2.5], "corners_total": [9.5]}
    assert all(s.predire(ctx, lignes) == [] for s in SPECIALISTES)


def test_matrice_partagee_entre_specialistes_de_buts(monde):
    matchs, hist = monde
    ctx = ContexteMatch(construire_features(matchs[200], hist, 10), Config())
    from moteur.modeles.specialistes.buts import matrice_du_match
    assert matrice_du_match(ctx) is matrice_du_match(ctx)
