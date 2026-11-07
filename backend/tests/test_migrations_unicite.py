"""Phase 3 : les contraintes d'unicité PRÉPARÉES (backend/migrations/phase3/03_contraintes_unicite.sql, non exécutées sur la vraie base)
sont rejouées ici sur la base de test : elles refusent les doublons et ne gênent aucun flux normal de l'application."""
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import taches
from app.database import SessionLocal, engine
from app.models import Coupon, Jambe, MemoireAgent, Match, PlanVerification, Run
from tests.conftest import collecte_exemple, profils_exemple
from tests.test_api import _faux_pipeline

DOSSIER = Path(__file__).resolve().parents[1] / "migrations" / "phase3"


def _instructions(fichier):
    sql = (DOSSIER / fichier).read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in sql.split(";") if s.strip() and s.strip().lower() not in ("begin", "commit")]


@pytest.fixture
def avec_unicite():
    instructions = _instructions("03_contraintes_unicite.sql")
    assert len(instructions) == 5
    with engine.begin() as conn:
        for i in instructions:
            conn.execute(text(i))
    yield
    with engine.begin() as conn:
        for i in _instructions("99_annulation.sql"):
            conn.execute(text(i))


def _run(db):
    run = Run(source="api", statut="termine")
    db.add(run)
    db.flush()
    return run


def test_les_fichiers_sont_complets_et_sans_donnees_modifiees_hors_02_04():
    assert {f.name for f in DOSSIER.iterdir()} >= {"00_LISEZMOI.md", "01_verifications_prealables.sql", "02_correction_doublon_matchs.sql",
                                                   "03_contraintes_unicite.sql", "99_annulation.sql"}
    for nom in ("01_verifications_prealables.sql", "03_contraintes_unicite.sql", "99_annulation.sql"):
        brut = re.sub(r"--[^\n]*", "", (DOSSIER / nom).read_text(encoding="utf-8")).lower()
        assert not re.search(r"\b(delete|update|truncate|insert)\b", brut), nom   # ni suppression ni modification dans ces fichiers
    assert "rollback" in (DOSSIER / "04_corrections_proposees_NON_RECOMMANDEES_SANS_REVUE.sql").read_text()   # la proposition est annulée par défaut


def test_doublons_refuses(avec_unicite):
    with SessionLocal() as db:
        run = _run(db)
        db.add(Coupon(run_id=run.id, jour=date.today(), profil="coupon1", nom="a", statut="en_attente"))
        db.commit()
        db.add(Coupon(run_id=run.id, jour=date.today(), profil="coupon1", nom="b", statut="en_attente"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        coupon = db.query(Coupon).one()
        for _ in range(2):
            db.add(Jambe(coupon_id=coupon.id, libelle_match="A vs B", categorie="c", marche="m", selection="Over", cote=1.5,
                         resultat="en_attente"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(Match(run_id=run.id, domicile="A", exterieur="B"))
        db.commit()
        db.add(Match(run_id=run.id, domicile="A", exterieur="B"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(MemoireAgent(jour=date.today(), type="etude", contenu="x"))
        db.commit()
        db.add(MemoireAgent(jour=date.today(), type="etude", contenu="y"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_un_plan_clos_n_empeche_pas_un_nouveau_plan(avec_unicite):
    with SessionLocal() as db:
        run = _run(db)
        db.add(PlanVerification(run_id=run.id, plan={}, rapport_final_envoye=True))
        db.add(PlanVerification(run_id=run.id, plan={}, rapport_final_envoye=False))
        db.commit()                                                      # un clos + un non clos : autorisé
        db.add(PlanVerification(run_id=run.id, plan={}, rapport_final_envoye=False))
        with pytest.raises(IntegrityError):
            db.commit()


def test_les_flux_normaux_fonctionnent_avec_les_contraintes(avec_unicite, monkeypatch):
    """Run complet, relance du passage cron, bilan, mémoire : aucune violation d'unicité dans l'usage normal."""
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--telegram", "--moteur", "deterministe"]) == 0
    assert taches.main(["run", "--telegram", "--si-aucun-ticket-aujourdhui", "--moteur", "deterministe"]) == 0   # garde : rien de relancé
    assert taches.main(["envoyer", "--forcer"]) == 0
    assert len(envois) == 2
    with SessionLocal() as db:
        assert db.query(Coupon).count() == 3 and db.query(Run).count() == 1
