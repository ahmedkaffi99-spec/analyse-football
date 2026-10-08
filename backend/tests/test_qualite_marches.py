"""Tests de qualite_marches (taux de réussite réel par marché, sur les paris déjà jugés) :
aucun appel réseau, seulement la base de test SQLite."""

from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Coupon, Jambe, Run
from app.services.qualite_marches import qualite_marches


def _run_avec_jambes(db, jambes, lance_le=None):
    run = Run(source="api", statut="termine", lance_le=lance_le or datetime.now(timezone.utc))
    db.add(run)
    db.flush()
    coupon = Coupon(run_id=run.id, jour=run.lance_le.date(), profil="jour", nom="Coupon")
    db.add(coupon)
    db.flush()
    for marche, resultat, edge_pct in jambes:
        db.add(Jambe(coupon_id=coupon.id, libelle_match="A vs B", categorie=marche, marche=marche,
                     selection="X", cote=1.5, resultat=resultat, edge_pct=edge_pct))
    db.commit()


def test_calcule_le_taux_de_reussite_reel_par_marche():
    with SessionLocal() as db:
        _run_avec_jambes(db, [
            ("Double Chance Full Time", "perdu", -10.0), ("Double Chance Full Time", "perdu", -8.0),
            ("Double Chance Full Time", "perdu", -12.0), ("Double Chance Full Time", "perdu", -9.0),
            ("Double Chance Full Time", "perdu", -11.0), ("Double Chance Full Time", "perdu", -10.0),
            ("Double Chance Full Time", "perdu", -9.0), ("Double Chance Full Time", "gagne", 5.0),
        ])
        resultat = qualite_marches(db)
    assert resultat["Double Chance Full Time"]["n"] == 8
    assert resultat["Double Chance Full Time"]["taux_reussite_pct"] == 12.5
    assert resultat["Double Chance Full Time"]["edge_moyen_pct"] == -8.0


def test_sous_le_seuil_minimum_absent_du_resultat():
    with SessionLocal() as db:
        _run_avec_jambes(db, [("Marché rare", "gagne", 5.0), ("Marché rare", "perdu", -5.0)])
        resultat = qualite_marches(db, seuil_n_min=8)
    assert "Marché rare" not in resultat


def test_push_et_non_verifiable_ignores():
    with SessionLocal() as db:
        _run_avec_jambes(db, [("Marché X", "push", None), ("Marché X", "non_verifiable", None)]
                         + [("Marché X", "gagne", 1.0)] * 8)
        resultat = qualite_marches(db, seuil_n_min=8)
    assert resultat["Marché X"]["n"] == 8
    assert resultat["Marché X"]["taux_reussite_pct"] == 100.0


def test_hors_fenetre_ignore():
    with SessionLocal() as db:
        vieux = datetime.now(timezone.utc) - timedelta(days=120)
        _run_avec_jambes(db, [("Marché ancien", "gagne", 1.0)] * 10, lance_le=vieux)
        resultat = qualite_marches(db, fenetre_jours=60, seuil_n_min=8)
    assert "Marché ancien" not in resultat
