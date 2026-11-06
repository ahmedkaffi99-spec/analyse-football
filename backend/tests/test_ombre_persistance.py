"""Persistance, jugement et rapport du suivi en ombre."""
from datetime import date

from app.database import SessionLocal
from app.models import Coupon, CouponOmbre, Jambe, Run
from app.services import ombre_persistance as op


def _cand(match, selection, cote=1.4):
    return {"match": match, "home_nom": match.split(" vs ")[0], "fixture_id_oddspapi": None,
            "pick": {"categorie": "Total", "marche": "Over Under Full Time (2.5)", "selection": selection, "cote": cote,
                     "proba_modele_pct": 72.0, "edge_pct": 1.0}}


def test_enregistrer_ecartes_dedoublonne_et_groupe_par_origine():
    with SessionLocal() as db:
        run = Run(source="api", statut="termine")
        db.add(run)
        db.flush()
        ecartes = [{"origine": "ia_famille", "candidat": _cand("A vs B", "Over"), "raison": "r"},
                   {"origine": "ia_famille", "candidat": _cand("A vs B", "Over"), "raison": "doublon"},
                   {"origine": "veto_python", "candidat": _cand("C vs D", "Under"), "raison": "edge"}]
        assert op.enregistrer_ecartes(db, run, date.today(), ecartes) == 2
        db.commit()
        modeles = {c.modele: len(c.jambes) for c in db.query(CouponOmbre)}
        assert modeles == {"ecartes_ia": 1, "ecartes_veto": 1}


def test_enregistrer_comparaison_et_rapport():
    with SessionLocal() as db:
        run = Run(source="api", statut="termine")
        db.add(run)
        db.flush()
        resultat = {"modele": "m/x", "erreur": None, "tokens_entree": 1000, "tokens_sortie": 500, "cout_usd": 0.25,
                    "coupons": [{"profil": "coupon1", "cote_totale": 5.5, "dans_la_bande": True,
                                 "selections": [_cand("A vs B", "Over"), _cand("C vs D", "Under")]}]}
        op.enregistrer_comparaison(db, run, date.today(), [resultat])
        for j in db.query(op.JambeOmbre):
            j.resultat = "gagne" if j.selection == "Over" else "perdu"
        # une jambe réelle jugée pour la ligne « gardés »
        c = Coupon(run_id=run.id, jour=date.today(), profil="coupon1", nom="réel", statut="gagne")
        db.add(c)
        db.flush()
        db.add(Jambe(coupon_id=c.id, libelle_match="A vs B", categorie="Total", marche="x", selection="Over", cote=1.4,
                     proba_modele_pct=70.0, resultat="gagne"))
        db.commit()
        texte = op.rapport(db, jours=7)
        assert "m/x : 1 coupon(s) composé(s), 1 dans la bande" in texte and "1/2 = 50.0 %" in texte
        assert "0.25 $" in texte and "1500 tokens" in texte
        assert "aucun pari jugé pour l'instant" in texte   # pas encore de paris écartés jugés
