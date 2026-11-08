"""Améliorations du 07/11/2026 (côté backend) : quota API-Football, collecte du jour réutilisable, cote payée, version des règles. IA et API simulées."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import Run
from app.services import bilan, runs
from tests.conftest import collecte_exemple


def J(resultat, cote):
    return SimpleNamespace(resultat=resultat, cote=cote)


# ---- cote payée (jambes remboursées) -------------------------------------------------------------------------------------------------------------------------------
def test_cote_payee_deduit_les_jambes_remboursees():
    # coupon 395 du 07/11 : 8 jambes annoncées 5,39, trois remboursées -> payé 3,09
    jambes = [J("push", 1.2), J("push", 1.21), J("gagne", 1.2), J("push", 1.2), J("gagne", 1.23), J("gagne", 1.24), J("gagne", 1.3), J("gagne", 1.3)]
    assert bilan.cote_payee(jambes) == pytest.approx(3.09, abs=0.01)
    assert bilan.cote_payee([J("gagne", 1.5), J("gagne", 2.0)]) == 3.0
    assert bilan.cote_payee([J("gagne", 1.5), J("perdu", 2.0)]) == 0.0
    assert bilan.cote_payee([J("gagne", 1.5), J("demi_gagne", 2.0)]) == pytest.approx(2.25)       # moitié à 2,0 (1,5 de gain sur 1), moitié remboursée
    assert bilan.cote_payee([J("gagne", 1.5), J("en_attente", 2.0)]) is None                      # jambe pas jugée : cote payée inconnue
    assert bilan.cote_payee([J("gagne", 1.5), J("non_verifiable", 2.0)]) is None


def test_le_bilan_affiche_la_cote_payee_quand_elle_differe_de_la_cote_annoncee():
    c = SimpleNamespace(nom="🟢 PRUDENT", profil="coupon1", statut="gagne", cote_totale=1.74, jour=datetime(2026, 11, 7).date(),
                        jambes=[SimpleNamespace(resultat=r, cote=k, libelle_match="A vs B", marche="Total", selection="Over", match=None)
                                for r, k in (("gagne", 1.2), ("push", 1.21), ("push", 1.2))])
    texte = bilan.construire_message([c])
    assert "Cote totale annoncée : *1.74*" in texte and "Cote payée" in texte and "*1.2*" in texte
    c.jambes = [SimpleNamespace(resultat="gagne", cote=1.3, libelle_match="A vs B", marche="Total", selection="Over", match=None)]
    c.cote_totale = 1.3
    assert "Cote payée" not in bilan.construire_message([c])


# ---- quota API-Football : détection et réutilisation de la collecte du jour --------------------------------------------------------------------------------------
def test_detection_du_quota_api_football():
    import collecte_donnees as cd
    assert cd.quota_api_football_epuise_dans({"requests": "You have reached the request limit for the day, Go to https://dashboard.api-football.com"})
    assert cd.quota_api_football_epuise_dans("Too many requests: rate limit")
    assert not cd.quota_api_football_epuise_dans({"token": "Error/Missing application key"})
    assert not cd.quota_api_football_epuise_dans(None)


def _donnees(*equipes):
    return {"nb_matchs_avec_marches": len(equipes),
            "matchs": [{"api_football": {"home_name": d, "away_name": e}, "match_demande": {"home": d, "away": e}, "oddspapi": {"tous_marches": [1]}} for d, e in equipes]}


def test_collecte_compatible_avec_la_selection_manuelle():
    d = _donnees(("Arsenal", "Hull City"), ("VfB Stuttgart", "Werder Bremen"))
    assert runs.collecte_compatible(d, "")
    assert runs.collecte_compatible(d, "Arsenal FC - Hull City AFC, VfB Stuttgart - SV Werder Bremen")      # noms complets de l'API
    assert not runs.collecte_compatible(d, "Arsenal FC - Hull City AFC, Leeds United - Tottenham")          # un match demandé absent : jamais de substitution silencieuse
    assert not runs.collecte_compatible(_donnees(), "Arsenal - Hull City")


def test_derniere_collecte_reutilisable_du_jour(monkeypatch):
    aujourdhui = datetime.now(timezone.utc)
    with SessionLocal() as db:
        vide = Run(source="test", statut="abandonne", nb_matchs_avec_marches=0, lance_le=aujourdhui)
        bonne = Run(source="test", statut="termine", nb_matchs_avec_marches=2, lance_le=aujourdhui)
        hier = Run(source="test", statut="termine", nb_matchs_avec_marches=5, lance_le=datetime(2020, 1, 1, tzinfo=timezone.utc))
        db.add_all([hier, bonne, vide]); db.commit()
        ids = {"bonne": bonne.id, "vide": vide.id, "hier": hier.id}
        donnees = _donnees(("Arsenal", "Hull City"))
        trouve = runs.derniere_collecte_reutilisable(db, run_exclu=vide.id, matchs_manuels="Arsenal - Hull City", telecharger=lambda db_, source: donnees)
        assert trouve == (ids["bonne"], donnees)                    # ni le run vide, ni celui d'hier
        assert runs.derniere_collecte_reutilisable(db, run_exclu=vide.id, matchs_manuels="Leeds - Tottenham", telecharger=lambda db_, s: donnees) is None


def _agent_en_deux_temps(monkeypatch, quota):
    """Faux agent : sans collecte réutilisée il constate une collecte vide ; avec donnees_reprises il compose un coupon."""
    appels = []
    selection = {"match": "Lens vs Auxerre", "pick": {"categorie": "Total", "marche": "Over Under Full Time (2.5)", "selection": "Over",
                                                     "handicap": 2.5, "cote": 1.8, "proba_modele_pct": 60.0, "edge_pct": 1.0}}

    def executer(**kw):
        appels.append(kw)
        if kw.get("donnees_reprises") is None:
            return {"donnees": {"nb_matchs_avec_marches": 0, "matchs": []}, "resultats_profils": [], "envoye": False, "raison_abandon": "collecte vide", "arret": "collecte vide"}
        return {"donnees": kw["donnees_reprises"], "resultats_profils": [{"profil": {"cle": "p1", "nom": "P1"}, "selections": [selection]}],
                "textes": ["coupon"], "envoye": False, "raison_abandon": None}

    from app.services import pipeline
    monkeypatch.setattr(pipeline, "charger_agent_pilote", lambda: SimpleNamespace(executer=executer))
    import collecte_donnees as cd
    monkeypatch.setattr(cd, "QUOTA_API_FOOTBALL_EPUISE", quota, raising=False)
    monkeypatch.setattr(pipeline, "reinitialiser_caches", lambda cd_, ae_: None)
    return appels


def test_quota_epuise_la_collecte_du_jour_est_reutilisee_automatiquement(monkeypatch):
    appels = _agent_en_deux_temps(monkeypatch, quota=True)
    monkeypatch.setattr(runs, "derniere_collecte_reutilisable", lambda db, run_exclu, manuels=None: (42, collecte_exemple()))
    with SessionLocal() as db:
        run = Run(source="test", statut="en_cours"); db.add(run); db.commit(); rid = run.id
    runs.executer_run(rid, envoyer_telegram=False, moteur="agent")
    assert len(appels) == 2 and appels[1]["donnees_reprises"] is not None
    with SessionLocal() as db:
        assert db.get(Run, rid).statut == "termine"


def test_quota_epuise_sans_collecte_reutilisable_le_run_echoue_avec_la_vraie_cause(monkeypatch):
    appels = _agent_en_deux_temps(monkeypatch, quota=True)
    monkeypatch.setattr(runs, "derniere_collecte_reutilisable", lambda db, run_exclu, manuels=None: None)
    with SessionLocal() as db:
        run = Run(source="test", statut="en_cours"); db.add(run); db.commit(); rid = run.id
    runs.executer_run(rid, envoyer_telegram=False, moteur="agent")
    with SessionLocal() as db:
        run = db.get(Run, rid)
        assert run.statut == "erreur" and "quota" in run.detail.lower() and "API-Football" in run.detail      # jamais « abandonné » ni « succès » trompeur
    assert len(appels) == 1


def test_collecte_vide_sans_quota_reste_un_abandon_normal(monkeypatch):
    appels = _agent_en_deux_temps(monkeypatch, quota=False)
    with SessionLocal() as db:
        run = Run(source="test", statut="en_cours"); db.add(run); db.commit(); rid = run.id
    runs.executer_run(rid, envoyer_telegram=False, moteur="agent")
    with SessionLocal() as db:
        assert db.get(Run, rid).statut == "abandonne"
    assert len(appels) == 1


def test_second_modele_d_une_comparaison_relit_la_collecte_du_premier(monkeypatch):
    appels = _agent_en_deux_temps(monkeypatch, quota=False)
    monkeypatch.setenv("REUTILISER_COLLECTE", "1")
    monkeypatch.setattr(runs, "derniere_collecte_reutilisable", lambda db, run_exclu, manuels=None: (7, collecte_exemple()))
    with SessionLocal() as db:
        run = Run(source="test", statut="en_cours"); db.add(run); db.commit(); rid = run.id
    runs.executer_run(rid, envoyer_telegram=False, moteur="agent")
    assert len(appels) == 1 and appels[0]["donnees_reprises"] is not None            # une seule passe : les données du premier modèle, aucune nouvelle collecte


# ---- version et règles enregistrées ---------------------------------------------------------------------------------------------------------------------------------
def test_version_et_regles_du_run(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "c0201dedec2a7d8dc63eeafa6786432fb51df26f")
    monkeypatch.setenv("PILOTE_MODELE", "deepseek/deepseek-v4.1-flash")
    import profils_smart
    v = runs.version_et_regles(profils_smart.profils(), "agent")
    assert v["commit"] == "c0201de" and v["modele"] == "deepseek/deepseek-v4.1-flash" and v["moteur"] == "agent"
    assert v["profils"]["coupon1"]["jambes"] == [5, 12] and v["profils"]["coupon1"]["bande_cote"] == [5.0, 10.0] and v["profils"]["coupon3"]["bande_cote"] == [16.0, 25.0]
    assert v["profils"]["coupon2"]["plafond_coupons_par_match"] == 2 and v["profils"]["coupon2"]["match_repete"] is True
    assert v["remplissage"]["max_par_coupon"] >= 0 and "plancher_jambe" in v
