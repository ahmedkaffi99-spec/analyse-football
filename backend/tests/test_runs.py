"""Tests de backend/app/services/runs.py:executer_run — le point d'entrée réel de production.

Non-régression de l'incident réel du 10/10/2026 (run #129) : un coupon RÉELLEMENT envoyé sur
Telegram a disparu sans trace de la base parce qu'une erreur SQL dans un bloc purement
informatif (capture historique dans hist_cotes) a empoisonné la transaction encore ouverte,
faisant échouer le commit final qui aurait dû enregistrer ce coupon déjà envoyé. Correctif :
le coupon et le statut du run sont désormais commités avant tout bloc optionnel, et chaque bloc
optionnel fait un rollback explicite en cas d'échec.

LIMITE CONNUE DE CES TESTS (vérifiée empiriquement, pas supposée) : la vraie base de production
est PostgreSQL, où une instruction SQL en échec met la TRANSACTION ENTIÈRE en état "aborted"
(toute commande suivante lève tant qu'aucun ROLLBACK n'a eu lieu) — c'est cette cascade qui a
causé l'incident réel. La base de test (SQLite, voir app.config.construire_database_url) n'a
PAS ce comportement : un commit() après une requête SQLite en échec réussit sans rollback
préalable (vérifié directement, repro manuelle). Les tests "comportemental" ci-dessous (le
coupon reste enregistré) restent donc vrais même SANS le correctif sous SQLite — ils documentent
le comportement correct, mais ne peuvent pas, seuls, détecter une régression de ce correctif
précis. Le test TestLeRollbackEstReellementAppele comble ce manque : il vérifie DIRECTEMENT
que db.rollback() est appelé par le gestionnaire d'exception, indépendamment du moteur de base
de données — c'est lui qui échouerait si le rollback explicite était retiré du code."""

import json
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Coupon, Run
from app.services import pipeline
from app.services.runs import executer_run


def _donnees_minimales():
    return {
        "nb_matchs_demandes": 1, "nb_matchs_avec_marches": 1, "nb_marches_total": 1,
        "matchs": [{
            "match_demande": {"home": "A", "away": "B"},
            "api_football": None,
            "oddspapi": {"fixture_id": "fx-1", "tous_marches": [
                {"marche_id": "1", "marche": "Over Under Full Time", "handicap": 2.5,
                 "periode": "fulltime",
                 "selections": [{"selection": "Over", "cote": 1.9}, {"selection": "Under", "cote": 1.9}]},
            ]},
            "stats_historiques": None, "stats_detaillees_10_matchs": None, "classement": None,
            "serper": None, "head_to_head": None, "blessures": None, "predictions_api_football": None,
        }],
    }


def _resultats_coupon_valide():
    return [{"profil": {"cle": "jour", "nom": "Coupon du jour"},
            "selections": [{"match": "A vs B", "home_nom": "A", "away_nom": "B",
                            "fixture_id_oddspapi": "fx-1",
                            "pick": {"categorie": "Total", "marche": "Over Under Full Time (2.5)",
                                     "handicap": 2.5, "selection": "Over", "cote": 1.9,
                                     "proba_modele_pct": 75.0, "edge_pct": 5.0,
                                     "guide": None, "onglet": None}}]}]


class _FauxCollecteDonnees(SimpleNamespace):
    """cd minimal : runs.py fait `cd.SORTIE_JSON = <chemin tmp>` puis `cd.collecter_donnees()`
    — cette dernière doit écrire le JSON au chemin lu dynamiquement sur self, pas figé à la
    construction (le vrai chemin tmp n'est connu qu'au moment où runs.py l'assigne)."""

    def collecter_donnees(self):
        with open(self.SORTIE_JSON, "w", encoding="utf-8") as f:
            json.dump(_donnees_minimales(), f)


def _faux_modules():
    """cd/ae minimaux couvrant exactement ce qu'executer_run appelle en moteur="deterministe"
    sans dépendre du vrai bet_agent (aucun appel réseau, aucun fichier réel hors tmp de test)."""
    cd = _FauxCollecteDonnees(SORTIE_JSON=None)
    ae = SimpleNamespace(
        generer_coupons=lambda donnees, qualite_marches=None: _resultats_coupon_valide(),
        agent4_rediger_coupons=lambda resultats: ["texte du coupon"],
        agent5_envoyer_coupons=lambda textes: True,  # jamais un vrai envoi : ce test ne mocke que la valeur de retour
        agent3_calcul_pool_candidats=lambda donnees: {},
    )
    return cd, ae


def _sql_cassee(db, *args, **kwargs):
    """Reproduit la VRAIE panne de l'incident (pas une simple exception Python) : exécute une
    requête SQL réellement invalide pour que SQLAlchemy marque effectivement la transaction en
    échec (PendingRollbackError sur toute opération suivante tant qu'aucun rollback n'a eu
    lieu) — un simple RuntimeError levé sans toucher la session ne reproduit pas ce symptôme et
    ne permettrait pas à ce test de distinguer le code corrigé du code cassé."""
    from sqlalchemy import text

    db.execute(text("SELECT * FROM table_qui_nexiste_absolument_pas_42"))


def _run(db, statut="en_cours"):
    run = Run(source="api", statut=statut)
    db.add(run)
    db.commit()
    return run


class TestEchecBlocOptionnelNeffaceJamaisLeCouponDejaEnvoye:
    """Reproduit exactement l'incident réel du 10/10/2026 (run #129) : un bloc optionnel
    (capture historique dans hist_cotes) échoue après l'envoi Telegram — le coupon doit
    malgré tout rester enregistré en base, et le run doit rester marqué "termine"."""

    def test_echec_de_la_capture_historique_nefface_pas_le_coupon(self):
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules()
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions", side_effect=_sql_cassee):
                executer_run(run_id, envoyer_telegram=True)

        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "termine"
            assert run_relu.envoye_telegram is True
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert len(coupons) == 1
            assert len(coupons[0].jambes) == 1

    def test_echec_de_la_comparaison_parallele_nefface_pas_le_coupon(self):
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules()
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch.dict("os.environ", {"MOTEUR_COMPARAISON_ACTIVE": "true"}), \
                    mock.patch("app.services.comparaison_moteurs.comparer_candidats", side_effect=_sql_cassee), \
                    mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
                executer_run(run_id, envoyer_telegram=True)

        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "termine"
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert len(coupons) == 1

    def test_aucun_echec_comportement_normal_inchange(self):
        # Cas normal (aucun bloc optionnel ne plante) : le coupon est enregistré, le run est
        # "termine" — comportement identique à avant ce correctif.
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules()
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
                executer_run(run_id, envoyer_telegram=True)

        with SessionLocal() as db:
            run_relu = db.get(Run, run_id)
            assert run_relu.statut == "termine"
            assert run_relu.envoye_telegram is True
            coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id)))
            assert len(coupons) == 1


class TestLeRollbackEstReellementAppele:
    """Test discriminant indépendant du moteur de base de données (voir limite documentée en
    tête de fichier) : vérifie DIRECTEMENT que db.rollback() est appelé quand un bloc optionnel
    échoue — en espionnant Session.rollback (classe SQLAlchemy réellement utilisée par
    SessionLocal), pas en déduisant l'appel d'un effet de bord qui n'existe que sous Postgres."""

    def test_rollback_appele_apres_echec_capture_historique(self):
        from sqlalchemy.orm import Session

        rollback_original = Session.rollback
        with SessionLocal() as db:
            run = _run(db)
            run_id = run.id
            cd, ae = _faux_modules()
            with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), \
                    mock.patch.object(pipeline, "reinitialiser_caches"), \
                    mock.patch("app.services.capture_historique.capturer_predictions",
                               side_effect=RuntimeError("boum")), \
                    mock.patch.object(Session, "rollback", autospec=True,
                                      side_effect=rollback_original) as rollback_espion:
                executer_run(run_id, envoyer_telegram=True)
        assert rollback_espion.called, (
            "db.rollback() n'a jamais été appelé après l'échec de capturer_predictions — "
            "sans cet appel, l'incident réel du 10/10/2026 (run 129) peut se reproduire sous "
            "Postgres (transaction empoisonnée -> commit final perdu -> coupon déjà envoyé "
            "sur Telegram jamais enregistré).")
