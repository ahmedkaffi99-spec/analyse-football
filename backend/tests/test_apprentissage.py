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
        assert texte and "UNE seule jambe" in texte and "annoncée à 78.0 % perdue" in texte
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


def test_jambe_presente_dans_deux_coupons_comptee_une_fois():
    """Une même jambe dans 2 coupons du jour = 1 jambe jugée, et une seule mention dans l'étude."""
    jour = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        for nom in ("🟢 A", "🟠 B"):
            run = Run(source="api", statut="termine")
            db.add(run)
            db.flush()
            c = Coupon(run_id=run.id, jour=jour, profil="coupon1", nom=nom, cote_totale=5.0, statut="perdu")
            db.add(c)
            db.flush()
            db.add(Jambe(coupon_id=c.id, libelle_match="X vs Y", categorie="Total", marche="Over Under Full Time (2.5)",
                         selection="Over", cote=1.4, proba_modele_pct=78.0, resultat="perdu"))
        db.commit()
        assert len(apprentissage.jambes_jugees(db, jour=jour)) == 1
        texte = apprentissage.etudier_jour(db, jour, avec_ia=False)
        assert texte.count("X vs Y") == 1 and "dans 2 coupon(s)" in texte


def test_match_piege_deux_jambes_differentes_perdues():
    jour = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        run = Run(source="api", statut="termine")
        db.add(run)
        db.flush()
        c = Coupon(run_id=run.id, jour=jour, profil="coupon1", nom="🟢 A", cote_totale=5.0, statut="perdu")
        db.add(c)
        db.flush()
        for sel in ("Over", "Under"):
            db.add(Jambe(coupon_id=c.id, libelle_match="X vs Y", categorie="Total", marche="Total", selection=sel,
                         cote=1.4, proba_modele_pct=72.0, resultat="perdu"))
        db.commit()
        assert "Match piège : X vs Y" in apprentissage.etudier_jour(db, jour, avec_ia=False)


def test_etude_ia_sans_effectif_ecartee_et_refaire_remplace():
    jour = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        _jour_avec_resultats(db, jour, ["gagne", "perdu"])
        faits = apprentissage.faits_du_jour(db, jour)
        stats = apprentissage.statistiques(apprentissage.jambes_jugees(db, jour=jour))
        sans_n = lambda prompt, max_tokens: "Le marché des totaux est mauvais, évite-le. " * 10          # aucune règle chiffrée
        avec_n = lambda prompt, max_tokens: "Règle : limiter les jambes à 5 maximum (n=6 coupons). " * 5
        assert apprentissage._etude_par_ia(faits, stats, [], sans_n) is None
        assert "n=6" in apprentissage._etude_par_ia(faits, stats, [], avec_n)
        apprentissage.etudier_jour(db, jour, avec_ia=False)
        assert apprentissage.etudier_jour(db, jour, avec_ia=False) is None
        assert apprentissage.etudier_jour(db, jour, avec_ia=False, refaire=True)
        assert db.query(MemoireAgent).count() == 1
