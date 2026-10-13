"""Tests de la bascule du 11/10/2026 : moteur_central/ devient le moteur par défaut de
runs.py:executer_run() (remplace "deterministe"). Vérifie précisément :
(1) c'est bien moteur_central qui s'exécute par défaut (pas deterministe, pas agent) ;
(2) aucun moteur concurrent n'est lancé en même temps (ae.generer_coupons / agent_pilote
    jamais appelés quand moteur="central") ;
(3) un échec de moteur_central ne bascule JAMAIS silencieusement vers un autre moteur — le run
    se termine en erreur, avec un détail explicite.

Aucun réseau, aucun Telegram réel : agent5_envoyer_coupons est une fausse fonction qui renvoie
simplement True, jamais un appel HTTP."""
import json
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Coupon, Run
from app.models_historique import HistCote, HistDecisionCentrale, HistMatch  # noqa: F401 — enregistre ces
# tables sur Base.metadata AVANT que le fixture base_vide (conftest.py) appelle create_all :
# comparaison_moteurs.comparer_candidats() (appelé par moteur_central_run) lit hist_matchs via
# app.services.historique, jamais importé par défaut dans ce module sinon.
from app.services import pipeline
from app.services.runs import executer_run


def _candidat(match, categorie, selection, cote, proba=70.0, edge=5.0, fid=None):
    home, away = match.split(" vs ")
    return {"match": match, "home_nom": home, "away_nom": away,
            "fixture_id_oddspapi": fid or match,
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)",
                     "marche_affichage": f"{categorie} (2.5)", "handicap": 2.5,
                     "selection": selection, "cote": cote, "proba_modele_pct": proba,
                     "edge_pct": edge, "guide": f"guide {categorie}", "onglet": "onglet"},
            "contexte": {"elo": {}, "buts_attendus": {"domicile": 1.4, "exterieur": 1.1}},
            "competition": "Premier League"}


def _pool_deux_matchs():
    # Deux matchs, cote 1.3 chacun : produit à 2 jambes = 1.69, dans [1.3, 3.0]
    # (moteur_central_run.COTE_MIN_CENTRAL/COTE_MAX_CENTRAL) — un coupon central doit pouvoir
    # se composer avec ce pool minimal.
    return {
        "A vs B": [_candidat("A vs B", "Total", "Over", 1.3)],
        "C vs D": [_candidat("C vs D", "Total", "Over", 1.3)],
    }


def _pool_n_matchs(n, cote=1.3):
    return {f"M{i} vs A{i}": [_candidat(f"M{i} vs A{i}", "Total", "Over", cote)] for i in range(n)}


def _donnees_minimales():
    return {"nb_matchs_demandes": 2, "nb_matchs_avec_marches": 2, "nb_marches_total": 2, "matchs": []}


class _FauxCollecteDonnees(SimpleNamespace):
    def collecter_donnees(self):
        with open(self.SORTIE_JSON, "w", encoding="utf-8") as f:
            json.dump(_donnees_minimales(), f)


_PALIERS_NB_COUPONS_DYNAMIQUE = ((2, 1), (6, 2), (10, 3), (16, 4), (20, 5))


def _nb_coupons_dynamique(nb_matchs_eligibles, paliers=_PALIERS_NB_COUPONS_DYNAMIQUE):
    # Même règle que bet_agent/analyser_et_envoyer.py:nb_coupons_dynamique — réimplémentée ici
    # (ae est un faux module dans ces tests, pas le vrai bet_agent) pour que
    # moteur_central_run.executer_moteur_central (qui l'appelle via ae.nb_coupons_dynamique)
    # dimensionne le nombre de coupons exactement comme en production.
    nb = 0
    for seuil, n in paliers:
        if nb_matchs_eligibles >= seuil:
            nb = n
    return nb


def _verifier_unicite_matchs_coupons(resultats_profils):
    # Même garde-fou que bet_agent/analyser_et_envoyer.py:verifier_unicite_matchs_coupons.
    vus = {}
    for item in resultats_profils:
        for c in item["selections"]:
            if c["match"] in vus and vus[c["match"]] != item["profil"]["cle"]:
                raise ValueError(f"Doublon de match détecté entre coupons : {c['match']!r}")
            vus[c["match"]] = item["profil"]["cle"]


def _faux_modules(pool):
    """ae.generer_coupons lève si jamais appelé : preuve directe qu'aucun moteur concurrent
    (deterministe) ne tourne quand moteur="central" est sélectionné."""
    cd = _FauxCollecteDonnees(SORTIE_JSON=None)
    ae = SimpleNamespace(
        generer_coupons=mock.Mock(side_effect=AssertionError(
            "ae.generer_coupons (moteur deterministe) a été appelé alors que moteur=\"central\" "
            "était sélectionné — un moteur concurrent a tourné.")),
        agent4_rediger_coupons=lambda resultats: ["texte du coupon"] * len(resultats),
        agent5_envoyer_coupons=lambda textes: True,  # jamais un vrai envoi Telegram
        agent3_calcul_pool_candidats=lambda donnees: pool,
        nb_coupons_dynamique=_nb_coupons_dynamique,
        verifier_unicite_matchs_coupons=_verifier_unicite_matchs_coupons,
    )
    return cd, ae


def _run(db):
    run = Run(source="api", statut="en_cours")
    db.add(run)
    db.commit()
    return run


class TestMoteurCentralEstBienCeluiQuiSexecute:
    def test_coupon_central_genere_sans_moteur_concurrent(self):
        pool = _pool_deux_matchs()
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules(pool)
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
                # moteur="central" est le DÉFAUT de executer_run() depuis le 11/10/2026 — non
                # passé explicitement ici, pour vérifier précisément CE défaut.
                executer_run(run_id, envoyer_telegram=True)
            ae.generer_coupons.assert_not_called()

        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "termine"
            assert run_relu.envoye_telegram is True
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert len(coupons) == 1
            assert coupons[0].profil == "central_1"
            # Les deux matchs du pool central ont bien été retenus (2 jambes, cote ~1.69).
            assert len(coupons[0].jambes) == 2
            # Compatibilité avec la chaîne existante (instruction 5) : categorie/handicap/
            # guide/onglet sont bien récupérés depuis le pool bet_agent d'origine, pas perdus.
            jambe = coupons[0].jambes[0]
            assert jambe.categorie == "Total"
            assert jambe.handicap == 2.5
            assert jambe.guide == "guide Total"

    def test_moteur_explicite_central_identique_au_defaut(self):
        pool = _pool_deux_matchs()
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules(pool)
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
                executer_run(run_id, envoyer_telegram=False, moteur="central")
            ae.generer_coupons.assert_not_called()
        with SessionLocal() as db:
            assert db.get(Run, run_id).statut == "termine"


class TestAucunRepliSilencieuxVersUnAutreMoteur:
    def test_pool_insuffisant_termine_en_erreur_jamais_de_repli(self):
        # Un seul match/candidat : sous le minimum de 2 jambes de moteur_central/selection.py
        # — aucun coupon ne peut être composé.
        pool = {"A vs B": [_candidat("A vs B", "Total", "Over", 1.3)]}
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules(pool)
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"):
                executer_run(run_id, moteur="central")
            # Jamais de repli vers generer_coupons (deterministe) après l'échec de moteur_central.
            ae.generer_coupons.assert_not_called()

        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "erreur"
            assert "Moteur central" in run_relu.detail
            assert "aucun coupon composé" in run_relu.detail
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert coupons == []

    def test_pool_vide_termine_en_erreur_jamais_de_repli(self):
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules({})
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"):
                executer_run(run_id, moteur="central")
            ae.generer_coupons.assert_not_called()
        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "erreur"
            assert "pool de candidats vide" in run_relu.detail

    def test_depuis_run_refuse_explicitement_pour_moteur_central(self):
        # --depuis-run n'est pas supporté avec moteur="central" (voir runs.py) : une erreur
        # explicite, jamais une tentative silencieuse de reprise mal supportée.
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules(_pool_deux_matchs())
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"):
                executer_run(run_id, moteur="central", depuis_run=999)
        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "erreur"
            assert "depuis-run" in run_relu.detail


class TestGenerationDynamiqueMultiCoupons:
    """13/10/2026, demande explicite : "je veux plusieurs jambes ou plusieurs coupons
    combiné" — moteur_central/selection.py ne compose nativement qu'un seul coupon par appel ;
    moteur_central_run.executer_moteur_central boucle en excluant à chaque tour les matchs
    déjà utilisés (même principe que la génération dynamique de bet_agent du 11/10/2026)."""

    def test_six_matchs_donnent_deux_coupons_sans_recouvrement(self):
        # 6 matchs éligibles -> palier "6" de nb_coupons_dynamique = 2 coupons.
        pool = _pool_n_matchs(6)
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules(pool)
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
                executer_run(run_id, moteur="central")

        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "termine"
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert len(coupons) == 2
            assert {c.profil for c in coupons} == {"central_1", "central_2"}
            matchs_vus = [j.libelle_match for c in coupons for j in c.jambes]
            assert len(matchs_vus) == len(set(matchs_vus)), (
                "un même match apparaît dans plusieurs coupons du moteur central")

    def test_deux_matchs_seulement_un_seul_coupon(self):
        # Comportement inchangé pour un petit pool : un seul coupon (palier "2" = 1).
        pool = _pool_deux_matchs()
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules(pool)
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
                executer_run(run_id, moteur="central")
        with SessionLocal() as db:
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert len(coupons) == 1
