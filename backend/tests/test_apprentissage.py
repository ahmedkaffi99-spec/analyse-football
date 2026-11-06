"""Mémoire d'apprentissage : étude d'un jour jugé, idempotence, texte injecté dans la mission de l'agent."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Coupon, Jambe, MemoireAgent, Run
from app.services import apprentissage


def _jour_avec_resultats(db, jour, resultats):
    run = Run(source="api", statut="termine")
    db.add(run)
    db.flush()
    coupon = Coupon(run_id=run.id, jour=jour, profil="coupon1", nom="🟢 Test", cote_totale=5.0,
                    statut="perdu" if "perdu" in resultats else "gagne")
    db.add(coupon)
    db.flush()
    for i, res in enumerate(resultats):
        db.add(Jambe(coupon_id=coupon.id, libelle_match=f"M{i} vs N{i}", categorie="Total", marche="Over Under Full Time (2.5)",
                     selection="Over", cote=1.4, proba_modele_pct=78.0, edge_pct=1.0, resultat=res))
    db.commit()


def test_etude_du_jour_enregistree_une_seule_fois():
    jour = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        _jour_avec_resultats(db, jour, ["gagne", "gagne", "perdu"])
        texte = apprentissage.etudier_jour(db, jour, avec_ia=False)
        assert texte and "UNE seule jambe" in texte and "78.0 % PERDUE" in texte
        assert db.query(MemoireAgent).count() == 1
        assert apprentissage.etudier_jour(db, jour, avec_ia=False) is None   # idempotent
        assert db.query(MemoireAgent).count() == 1


def test_jour_avec_jambe_en_attente_non_etudie():
    jour = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        _jour_avec_resultats(db, jour, ["gagne", "en_attente"])
        assert apprentissage.etudier_jour(db, jour, avec_ia=False) is None
        assert apprentissage.memoire_pour_prompt(db) is None


def test_memoire_pour_prompt_contient_etude_et_fiabilite():
    jour = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        _jour_avec_resultats(db, jour, ["gagne", "perdu", "perdu", "gagne", "perdu", "perdu"])
        apprentissage.etudier_jour(db, jour, avec_ia=False)
        texte = apprentissage.memoire_pour_prompt(db)
        assert texte.startswith("MÉMOIRE D'APPRENTISSAGE")
        assert "ÉTUDE DU" in texte and "70-80 %" in texte and "réussite réelle 33.3 %" in texte


def test_statistiques_tranches():
    with SessionLocal() as db:
        _jour_avec_resultats(db, date.today(), ["gagne", "perdu"])
        stats = apprentissage.statistiques(apprentissage.jambes_jugees(db))
        assert stats["par_proba"]["70-80 %"] == {"n": 2, "gagnees": 1, "reussite_pct": 50.0, "annoncee_pct": 78.0}
