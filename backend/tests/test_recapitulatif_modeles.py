"""Récapitulatif « coupon par modèle » : lecture du modèle dans le journal du run, regroupement par run, plage de numéros."""
from datetime import date

import pytest

from app.database import SessionLocal
from app.models import Coupon, Jambe, Run
from app.services import recapitulatif as rc


def _run(db, run_id, detail):
    db.add(Run(id=run_id, statut="termine", detail=detail))


def _coupon(db, cid, run_id, profil, cote, proba, nb_jambes=2):
    c = Coupon(id=cid, run_id=run_id, jour=date(2026, 11, 8), profil=profil, nom="N", cote_totale=cote, proba_combinee_pct=proba)
    for i in range(nb_jambes):
        c.jambes.append(Jambe(libelle_match=f"A{i} vs B{i}", categorie="Total", marche="m", selection="Over", cote=1.5))
    db.add(c)


def test_modele_du_run_lit_le_journal():
    assert rc.modele_du_run('JOURNAL_AGENT {"a":1,"modele_pilote":"openai/gpt-6.1-sol","route_pilote":"x"}') == "openai/gpt-6.1-sol"
    assert rc.modele_du_run("sans journal") is None and rc.modele_du_run(None) is None


def test_noms_lisibles_et_repli():
    assert rc.nom_modele("deepseek (deepseek-flash)") == "DeepSeek officiel"
    assert rc.nom_modele("deepseek/deepseek-v4.1-flash") == "DeepSeek via OpenRouter"
    assert rc.nom_modele("vendeur/inconnu") == "vendeur/inconnu"
    assert rc.nom_modele(None) == rc.MODELE_INCONNU


def test_recapitulatif_regroupe_par_run_avec_le_bon_modele():
    with SessionLocal() as db:
        _run(db, 300, '{"modele_pilote":"deepseek/deepseek-v4.1-flash"}')
        _run(db, 304, '{"modele_pilote":"openai/gpt-6.1-sol"}')
        _coupon(db, 410, 300, "coupon1", 6.76, 12.6, 8)
        _coupon(db, 411, 300, "coupon2", 14.77, 9.0, 5)
        _coupon(db, 413, 304, "coupon1", 6.51, 13.8, 8)
        db.commit()
        lignes = rc.lignes_recapitulatif(db, [413, 410, 411])
    assert [l["coupon"] for l in lignes] == [410, 411, 413]
    texte = rc.construire_message(lignes)
    assert texte.index("DeepSeek via OpenRouter") < texte.index("GPT-6.1 Sol")                 # blocs dans l'ordre des runs
    assert "• coupon 410 · 🟢 Prudent · cote 6.76 · 8 jambes · probabilité 12.6 %" in texte
    assert "• coupon 411 · 🟠 Équilibré · cote 14.77 · 5 jambes" in texte
    assert "(run 300)" in texte and "(run 304)" in texte and "2026-11-08" in texte


def test_run_sans_modele_enregistre_ne_plante_pas():
    with SessionLocal() as db:
        _run(db, 7, None)
        _coupon(db, 70, 7, "coupon3", 30.0, None)
        db.commit()
        texte = rc.construire_message(rc.lignes_recapitulatif(db, [70]))
    assert rc.MODELE_INCONNU in texte and "🔴 Gainer" in texte and "probabilité" not in texte


def test_aucun_coupon():
    with SessionLocal() as db:
        assert rc.lignes_recapitulatif(db, [999]) == []
    assert rc.construire_message([]) == "Aucun coupon trouvé pour ce récapitulatif."


def test_reference_plage():
    assert rc.reference_recapitulatif("410") is None and rc.reference_recapitulatif("410@123") is None
    assert rc.reference_recapitulatif("recap:410-413") == [410, 411, 412, 413]
    assert rc.reference_recapitulatif("recap:5") == [5]
    for mauvaise in ("recap:9-3", "recap:0-2", "recap:1-500"):
        with pytest.raises(ValueError):
            rc.reference_recapitulatif(mauvaise)
