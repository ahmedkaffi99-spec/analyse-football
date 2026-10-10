"""Tests de l'orchestration SHADOW du moteur_central/ (decision_centrale.py) : construit les
candidats réels à partir du pool bet_agent + comparaison_moteurs, calcule les 3 coupons
indépendants et les journalise — jamais de modification de la sélection ni de Telegram."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Run
from app.models_historique import HistCote, HistDecisionCentrale
from app.services import historique as hist
from app.services.decision_centrale import (
    _combo_vers_json,
    calculer_et_journaliser_shadow,
    construire_candidats,
)
from moteur_central.config import ConfigCentrale
from moteur_central.contrat_adapter import CLES_SCHEMA_COMMUN
from moteur_central.score_central import CandidatCentral

HOME_ID, AWAY_ID = 100, 200


def _run(db):
    run = Run(source="api", statut="en_cours", lance_le=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    return run


def _pick(categorie, selection, cote, proba=55.0, edge=2.0, ligne=2.5):
    return {"categorie": categorie, "marche": f"{categorie} ({ligne})", "marche_affichage": f"{categorie} ({ligne})",
            "handicap": ligne, "selection": selection, "cote": cote, "proba_modele_pct": proba, "edge_pct": edge}


def _candidat(match, pick, af_home_id=HOME_ID, af_away_id=AWAY_ID, home_nom="H", away_nom="A"):
    return {"match": match, "pick": pick, "home_nom": home_nom, "away_nom": away_nom,
            "fixture_id_oddspapi": "fxABC", "af_home_id": af_home_id, "af_away_id": af_away_id,
            "competition_id": 1, "competition": "Ligue Test",
            "date_iso": datetime.now(timezone.utc).isoformat(), "fixture_id_api_football": 999}


def _match_hist(match_id, home_id, away_id, home_g, away_g, jours_avant):
    date_m = (datetime.now(timezone.utc) - timedelta(days=jours_avant)).isoformat()
    return {"match_id": match_id, "date": date_m, "competition_id": 1, "competition": "Ligue Test",
            "saison": 2025, "home_id": home_id, "home": "H", "away_id": away_id, "away": "A",
            "arbitre": None, "statut": "FT", "home_score": home_g, "away_score": away_g, "stats": None}


def _peupler_historique_suffisant(db):
    matchs = []
    for i in range(6):
        matchs.append(_match_hist(i + 1, HOME_ID, 900 + i, 2, 1, jours_avant=30 + i * 10))
        matchs.append(_match_hist(i + 100, AWAY_ID, 900 + i, 1, 1, jours_avant=30 + i * 10))
    hist.upsert_matchs(db, matchs)


def test_construire_candidats_sans_historique_moteur_ne_cree_que_bet_agent():
    with SessionLocal() as db:
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        candidats_ba, candidats_mo = construire_candidats(pool, [], {"bet_agent": {}, "moteur": {}},
                                                           ConfigCentrale.depuis_env())
    assert len(candidats_ba) == 1
    assert candidats_mo == []  # pas de comparaison moteur fournie -> jamais une proba inventée


def test_construire_candidats_avec_moteur_disponible():
    with SessionLocal() as db:
        _peupler_historique_suffisant(db)
        from app.services.comparaison_moteurs import comparer_candidats

        pick = _pick("Total", "Over", 1.9)
        pool = {"H vs A": [_candidat("H vs A", pick)]}
        comparaison = comparer_candidats(db, pool)
        candidats_ba, candidats_mo = construire_candidats(pool, comparaison, {"bet_agent": {}, "moteur": {}},
                                                           ConfigCentrale.depuis_env())
    assert len(candidats_ba) == 1
    assert len(candidats_mo) == 1
    assert candidats_mo[0].moteur_responsable == "moteur"


def test_shadow_journalise_sans_toucher_aux_coupons_ni_jambes_reels():
    with SessionLocal() as db:
        run = _run(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        ligne = calculer_et_journaliser_shadow(db, run, pool, [], cote_min=1.3, cote_max=3.0)

        assert ligne.run_id == run.id
        assert ligne.coupon_bet_agent is not None
        assert ligne.coupon_moteur["genere"] is False  # aucun candidat moteur fourni
        # Le run lui-même n'a aucune colonne de sélection modifiée par cet appel (pas de
        # coupon/jambe créé en base) : la journalisation est strictement additive, séparée.
        from app.models import Coupon

        assert list(db.scalars(select(Coupon).where(Coupon.run_id == run.id))) == []


def test_shadow_une_seule_ligne_par_run_grace_a_la_contrainte_unique():
    with SessionLocal() as db:
        run = _run(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        calculer_et_journaliser_shadow(db, run, pool, [], cote_min=1.3, cote_max=3.0)
        lignes = list(db.scalars(select(HistDecisionCentrale).where(HistDecisionCentrale.run_id == run.id)))
        assert len(lignes) == 1


class TestComboVersJsonContratCommun:
    """Non-régression Phase 1 du plan de bascule (10/10/2026) : _combo_vers_json() utilise
    désormais moteur_central.contrat_adapter.convertir() pour chaque jambe au lieu d'un
    sous-ensemble de champs choisi à la main — les métadonnées du coupon et les champs déjà
    lus ailleurs (runs.py) doivent rester strictement inchangés."""

    def _combo(self, **overrides):
        candidat = CandidatCentral(match="H vs A", marche="resultat", selection="1", cote=1.8,
                                   moteur_responsable="bet_agent", proba_pct=58.0)
        base = {"genere": True, "jambes": [candidat], "cote_totale": 1.8, "score_moyen": 0.58, "nb_jambes": 1}
        base.update(overrides)
        return base

    def test_combo_non_genere_inchange(self):
        resultat = _combo_vers_json({"genere": False, "raison": "pas assez de candidats"})
        assert resultat == {"genere": False, "raison": "pas assez de candidats"}

    def test_metadonnees_du_coupon_inchangees(self):
        resultat = _combo_vers_json(self._combo())
        assert resultat["genere"] is True
        assert resultat["nb_jambes"] == 1
        assert resultat["cote_totale"] == 1.8
        assert resultat["score_moyen"] == 0.58

    def test_runs_py_lit_toujours_nb_jambes_et_genere_sans_casser(self):
        # Reproduit exactement l'accès fait par backend/app/services/runs.py:188-190 : seul
        # ['nb_jambes'] et ['genere'] sont lus pour le log console, jamais le contenu de
        # 'jambes' — ce test prouve que ce chemin de lecture reste valide après le changement.
        resultat = _combo_vers_json(self._combo())
        texte = f"{resultat['nb_jambes'] if resultat['genere'] else 'non généré'} jambe(s)"
        assert texte == "1 jambe(s)"

    def test_chaque_jambe_porte_toutes_les_cles_du_schema_commun(self):
        resultat = _combo_vers_json(self._combo())
        for jambe in resultat["jambes"]:
            assert set(jambe.keys()) == set(CLES_SCHEMA_COMMUN)

    def test_champs_deja_existants_preserves_dans_le_nouveau_format(self):
        # Les champs que l'ancien format exposait à la main (match, marche, selection, cote,
        # moteur_responsable, proba_pct) doivent être retrouvables avec la même valeur, même si
        # le nom de clé pour la cote change ("odds" au lieu de "cote" — voir contrat_adapter.py).
        resultat = _combo_vers_json(self._combo())
        jambe = resultat["jambes"][0]
        assert jambe["market"] == "resultat"
        assert jambe["selection"] == "1"
        assert jambe["odds"] == 1.8
        assert jambe["source"] == "bet_agent"
        assert jambe["proba_pct"] == 58.0

    def test_aucune_donnee_perdue_pour_un_candidat_complet(self):
        candidat = CandidatCentral(match="H vs A", marche="btts", selection="oui", cote=1.9,
                                   moteur_responsable="moteur", proba_pct=55.0, competition="Ligue Test",
                                   proba_calibree_pct=52.0, edge_pct=4.2,
                                   historique_marche={"disponible": True, "n": 40, "win_rate": 0.55},
                                   fixture_id_oddspapi="fx-1", raisons=["edge positif"])
        resultat = _combo_vers_json(self._combo(jambes=[candidat]))
        jambe = resultat["jambes"][0]
        assert jambe["competition"] == "Ligue Test"
        assert jambe["proba_calibree_pct"] == 52.0
        assert jambe["edge_pct"] == 4.2
        assert jambe["fixture_id_oddspapi"] == "fx-1"
        assert jambe["historique_marche"] == {"disponible": True, "n": 40, "win_rate": 0.55}
        assert jambe["reasons"] == ["edge positif"]

    def test_jambes_json_serialisables(self):
        import json

        candidat = CandidatCentral(match="H vs A", marche="btts", selection="oui", cote=1.9,
                                   moteur_responsable="moteur", proba_pct=55.0)
        resultat = _combo_vers_json(self._combo(jambes=[candidat]))
        json.dumps(resultat)  # lève si une valeur n'est pas sérialisable — ne doit jamais lever


def test_shadow_journalise_avec_le_nouveau_format_de_jambe():
    with SessionLocal() as db:
        run = _run(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        ligne = calculer_et_journaliser_shadow(db, run, pool, [], cote_min=1.3, cote_max=3.0)

        assert ligne.coupon_bet_agent is not None
        if ligne.coupon_bet_agent["genere"]:
            for jambe in ligne.coupon_bet_agent["jambes"]:
                assert set(jambe.keys()) == set(CLES_SCHEMA_COMMUN)


def test_shadow_utilise_lhistorique_hist_cotes_deja_juge_pour_le_score():
    with SessionLocal() as db:
        run1 = _run(db)
        # Un historique hist_cotes DÉJÀ jugé pour ce marché (jamais fabriqué dans le vrai
        # pipeline — ici seulement un fixture de test, comme pour tous les autres tests).
        for i in range(10):
            db.add(HistCote(run_id=run1.id, jour=run1.lance_le.date(), fixture_id_oddspapi=f"fx{i}",
                            domicile="H", exterieur="A", marche="Total (2.5)", categorie="Total",
                            ligne=2.5, selection="Over", cote=1.9, proba_bet_agent_pct=60.0,
                            resultat="gagne" if i % 2 == 0 else "perdu"))
        db.commit()

        run2 = _run(db)
        pool = {"H vs A": [_candidat("H vs A", _pick("Total", "Over", 1.9))]}
        ligne = calculer_et_journaliser_shadow(db, run2, pool, [], cote_min=1.3, cote_max=3.0)
        # La présence d'un historique jugé ne doit jamais faire échouer le calcul ; le détail
        # exact du score est vérifié par les tests unitaires de moteur_central/.
        assert ligne.coupon_bet_agent is not None
