"""Phase 2 (06/11/2026) : cohérence totale entre coupons envoyés, statistiques, bilans et mémoire d'apprentissage.
Seuls les coupons d'un run réellement envoyé sur Telegram sont des résultats réels ; les autres restent en base, intacts."""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Coupon, Jambe, MemoireAgent, Run
from app.services import apprentissage
from app.services.bilan import envoyer_bilans
from app.services.qualite_marches import qualite_marches
from app.services.statistiques import calculer, resume_pour_ia

JOUR = date.today() - timedelta(days=1)


def _coupon(db, envoye, resultats, profil="coupon1", marche="Over Under Full Time (2.5)"):
    run = Run(source="api", statut="termine", envoye_telegram=envoye)
    db.add(run)
    db.flush()
    coupon = Coupon(run_id=run.id, jour=JOUR, profil=profil, nom="Test", cote_totale=4.0,
                    statut="perdu" if "perdu" in resultats else "gagne")
    db.add(coupon)
    db.flush()
    for i, res in enumerate(resultats):
        db.add(Jambe(coupon_id=coupon.id, libelle_match=f"R{run.id} M{i} vs N{i}", categorie="Total", marche=marche, selection="Over",
                     cote=1.4, proba_modele_pct=78.0, edge_pct=1.0, resultat=res))
    db.commit()
    return coupon.id


def _deux_runs(db):
    """Un run envoyé (1 coupon gagné, 8 jambes gagnées) et un run NON envoyé (1 coupon perdu, 8 jambes perdues)."""
    envoye = _coupon(db, True, ["gagne"] * 8)
    non_envoye = _coupon(db, False, ["perdu"] * 8)
    return envoye, non_envoye


def test_statistiques_ignorent_les_coupons_non_envoyes():
    with SessionLocal() as db:
        _deux_runs(db)
        bilan = calculer(db)
        profil = bilan["profils"][0]
        assert (profil["coupons"], profil["clos"], profil["gagnes"]) == (1, 1, 1)
        assert bilan["categories"][0]["jugees"] == 8 and bilan["categories"][0]["gagnees"] == 8
        assert "1/1 coupon" in resume_pour_ia(db)


def test_run_uniquement_non_envoye_ne_donne_aucune_statistique():
    with SessionLocal() as db:
        _coupon(db, False, ["perdu", "perdu", "gagne"])
        assert calculer(db) == {"profils": [], "categories": []}
        assert resume_pour_ia(db) is None


def test_apprentissage_ignore_les_coupons_non_envoyes():
    with SessionLocal() as db:
        _deux_runs(db)
        assert len(apprentissage.jambes_jugees(db)) == 8
        assert all(j.resultat == "gagne" for j in apprentissage.jambes_jugees(db, jour=JOUR))
        faits = apprentissage.faits_du_jour(db, JOUR)
        assert len(faits["coupons"]) == 1 and faits["coupons"][0]["statut"] == "gagne"
        assert apprentissage.etudier_jour(db, JOUR, avec_ia=False)
        memoire = apprentissage.memoire_pour_prompt(db)
        assert "perdu" not in (memoire or "").lower().replace("perdu(s)", "")
        assert db.query(MemoireAgent).count() == 1


def test_jour_avec_seulement_des_coupons_non_envoyes_n_est_pas_etudie():
    with SessionLocal() as db:
        _coupon(db, False, ["perdu", "gagne"])
        assert apprentissage.faits_du_jour(db, JOUR) == []
        assert apprentissage.etudier_jour(db, JOUR, avec_ia=False) is None
        assert db.query(MemoireAgent).count() == 0
        assert apprentissage.memoire_pour_prompt(db) is None


def test_bilans_statistiques_memoire_et_qualite_voient_exactement_les_memes_coupons():
    with SessionLocal() as db:
        envoye, non_envoye = _deux_runs(db)
        messages = []
        envoyer_bilans(db, lambda m: messages.append(m) or True)
        assert len(messages) == 1                                             # bilan : le seul coupon envoyé
        assert db.get(Coupon, envoye).bilan_envoye is True
        assert db.get(Coupon, non_envoye).bilan_envoye is False                # historique laissé tel quel
        assert calculer(db)["profils"][0]["coupons"] == 1                      # statistiques : le même
        assert len(apprentissage.jambes_jugees(db)) == 8                       # mémoire : les mêmes jambes
        assert qualite_marches(db, seuil_n_min=1)["Over Under Full Time (2.5)"]["n"] == 8   # qualité des marchés : les mêmes
        # une fois le run non envoyé réellement envoyé, tout le monde le voit en même temps
        db.get(Run, db.get(Coupon, non_envoye).run_id).envoye_telegram = True
        db.commit()
        assert calculer(db)["profils"][0]["coupons"] == 2
        assert len(apprentissage.jambes_jugees(db)) == 16
        assert qualite_marches(db, seuil_n_min=1)["Over Under Full Time (2.5)"]["n"] == 16


def test_run_envoye_partiellement_compte_comme_envoye():
    """Envoi partiel : envoye_telegram est vrai (voir runs.py), donc ses coupons comptent partout."""
    with SessionLocal() as db:
        _coupon(db, True, ["gagne", "perdu"])
        assert calculer(db)["profils"][0]["coupons"] == 1
        assert len(apprentissage.jambes_jugees(db)) == 2


def test_aucune_donnee_historique_n_est_supprimee_ni_modifiee():
    with SessionLocal() as db:
        _, non_envoye = _deux_runs(db)
        calculer(db)
        resume_pour_ia(db)
        apprentissage.jambes_jugees(db)
        assert db.query(Coupon).count() == 2 and db.query(Jambe).count() == 16
        assert all(j.resultat == "perdu" for j in db.get(Coupon, non_envoye).jambes)


def test_memoire_relit_seulement_les_etudes_de_jours_avec_coupon_envoye():
    with SessionLocal() as db:
        _coupon(db, False, ["perdu", "perdu"])                 # JOUR : uniquement non envoyé
        autre = JOUR - timedelta(days=3)
        run = Run(source="api", statut="termine", envoye_telegram=True)
        db.add(run)
        db.flush()
        db.add(Coupon(run_id=run.id, jour=autre, profil="coupon1", nom="T", cote_totale=3.0, statut="gagne"))
        db.add(MemoireAgent(jour=JOUR, type="etude", contenu="ETUDE_SUR_ESSAI"))
        db.add(MemoireAgent(jour=autre, type="etude", contenu="ETUDE_REELLE"))
        db.commit()
        memoire = apprentissage.memoire_pour_prompt(db)
        assert "ETUDE_REELLE" in memoire and "ETUDE_SUR_ESSAI" not in memoire
        assert db.query(MemoireAgent).count() == 2             # rien n'est supprimé


def test_plan_d_un_run_non_envoye_est_cloture_sans_attendre_un_bilan_qui_ne_viendra_pas():
    from app import taches
    from app.models import PlanVerification
    with SessionLocal() as db:
        non_envoye = _coupon(db, False, ["gagne"])
        envoye = _coupon(db, True, ["gagne"])
        for coupon_id in (non_envoye, envoye):
            db.add(PlanVerification(run_id=db.get(Coupon, coupon_id).run_id, plan={"vagues": []}, rapport_final_envoye=False))
        db.commit()
        clos = {pv.run_id for pv in taches.plan_verification_a_cloturer(db)}
        assert clos == {db.get(Coupon, non_envoye).run_id}      # le run envoyé attend encore son bilan


def _jour_melange(db):
    """Un jour avec un coupon envoyé (gagné, 2 jambes gagnées) et un coupon d'essai (perdu), plus une étude ancienne bâtie sur les deux."""
    _coupon(db, True, ["gagne", "gagne"])
    _coupon(db, False, ["perdu"] * 4, profil="coupon2")
    db.add(MemoireAgent(jour=JOUR, type="etude", contenu="ANCIENNE ETUDE MELANGEE", stats={"jambes_jugees": 6}))
    db.commit()


def test_apercu_montre_ancienne_et_nouvelle_etude_sans_rien_ecrire(capsys):
    from app import taches
    with SessionLocal() as db:
        _jour_melange(db)
        avant = [(m.id, m.contenu, m.stats) for m in db.query(MemoireAgent)]
    assert taches.main(["apprendre", "--apercu", "--jour", JOUR.isoformat(), "--sans-ia"]) == 0
    sortie = capsys.readouterr().out
    assert "ANCIENNE ETUDE MELANGEE" in sortie and "NOUVELLE ÉTUDE" in sortie and "1 coupon(s) gagné(s), 0 perdu(s) sur 1" in sortie
    assert "aucune écriture en base" in sortie
    with SessionLocal() as db:
        assert [(m.id, m.contenu, m.stats) for m in db.query(MemoireAgent)] == avant     # strictement inchangée
        assert db.query(Coupon).count() == 2


def test_apercu_exige_un_jour(capsys):
    from app import taches
    assert taches.main(["apprendre", "--apercu"]) == 1


def test_exporter_sauvegarde_la_memoire_et_refuse_d_ecraser(tmp_path, capsys):
    import json
    from app import taches
    fichier = tmp_path / "memoire.json"
    with SessionLocal() as db:
        _jour_melange(db)
    assert taches.main(["apprendre", "--exporter", str(fichier)]) == 0
    sauvegarde = json.loads(fichier.read_text(encoding="utf-8"))
    assert len(sauvegarde) == 1 and sauvegarde[0]["contenu"] == "ANCIENNE ETUDE MELANGEE" and sauvegarde[0]["stats"] == {"jambes_jugees": 6}
    assert taches.main(["apprendre", "--exporter", str(fichier)]) == 1          # jamais d'écrasement
    assert "non écrasée" in capsys.readouterr().out


def test_regeneration_ne_garde_que_les_coupons_envoyes_puis_remplace_apres_validation():
    """Le remplacement réel (--refaire) n'a lieu que sur demande explicite ; il part des seuls coupons envoyés."""
    with SessionLocal() as db:
        _jour_melange(db)
        assert apprentissage.etudier_jour(db, JOUR, avec_ia=False, refaire=True, ecrire=False)       # aperçu
        assert db.query(MemoireAgent).one().contenu == "ANCIENNE ETUDE MELANGEE"
        nouveau = apprentissage.etudier_jour(db, JOUR, avec_ia=False, refaire=True)                 # remplacement validé
        etude = db.query(MemoireAgent).one()
        assert etude.contenu == nouveau and "ANCIENNE" not in nouveau and etude.stats["jambes_jugees"] == 2
        assert "1 coupon(s) gagné(s), 0 perdu(s) sur 1" in nouveau


def test_regeneration_d_un_jour_sans_coupon_envoye_conserve_l_ancienne_etude():
    with SessionLocal() as db:
        _coupon(db, False, ["perdu", "perdu"])
        db.add(MemoireAgent(jour=JOUR, type="etude", contenu="ETUDE SUR ESSAIS"))
        db.commit()
        assert apprentissage.etudier_jour(db, JOUR, avec_ia=False, refaire=True) is None
        assert db.query(MemoireAgent).one().contenu == "ETUDE SUR ESSAIS"      # rien n'est supprimé quand il n'y a rien à recalculer
