import pytest

from app.database import SessionLocal
from app.services import sources


def test_understat_refuse_par_defaut_et_autre_sources_ok():
    with SessionLocal() as db:
        sources.initialiser(db)
        sources.initialiser(db)                         # idempotent
        with pytest.raises(sources.SourceNonAutorisee):
            sources.exiger_autorisation(db, "understat")
        with pytest.raises(sources.SourceNonAutorisee):
            sources.exiger_autorisation(db, "source-inconnue")
        assert sources.exiger_autorisation(db, "api-football").nom == "api-football"


def test_autorisation_exige_une_preuve_et_est_tracee():
    with SessionLocal() as db:
        sources.initialiser(db)
        with pytest.raises(ValueError):
            sources.autoriser(db, "understat", "")
        s = sources.autoriser(db, "understat", "e-mail du support Understat daté du 2026-11-20 (réf. dossier)")
        assert s.collecte_autorisee and "inconnue/False" in s.historique
        assert sources.exiger_autorisation(db, "understat")


def test_initialiser_n_ecrase_pas_un_statut_existant():
    with SessionLocal() as db:
        sources.initialiser(db)
        sources.autoriser(db, "understat", "confirmation écrite référence 12345")
        sources.initialiser(db)
        assert sources.exiger_autorisation(db, "understat")
