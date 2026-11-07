"""Phase 3 : garde légère du cron — les passages inutiles sont sautés, la protection contre les doubles envois est conservée."""
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import garde
from app.database import SessionLocal
from app.models import Run

RACINE = Path(__file__).resolve().parents[2]
TOT = datetime.now(timezone.utc).replace(hour=9, minute=7, second=0, microsecond=0)
DERNIER = TOT.replace(hour=13, minute=27)


def _run(db, statut, envoye=False, quand=None):
    db.add(Run(source="api", statut=statut, envoye_telegram=envoye, lance_le=quand or TOT))
    db.commit()


def test_aucun_coupon_aujourd_hui_le_pipeline_tourne():
    with SessionLocal() as db:
        assert garde.decision_passage(db, TOT)[0] is True
        _run(db, "abandonne")                                    # abandon sans envoi : le passage suivant réessaie
        _run(db, "erreur")
        assert garde.decision_passage(db, TOT)[0] is True


def test_coupons_deja_envoyes_le_job_est_saute():
    with SessionLocal() as db:
        _run(db, "termine", envoye=True)
        lancer, raison = garde.decision_passage(db, TOT)
        assert lancer is False and "déjà envoyés" in raison
        assert garde.decision_passage(db, DERNIER)[0] is False   # même au dernier passage : tout est réglé


def test_run_en_erreur_apres_envoi_ne_relance_rien():
    with SessionLocal() as db:
        _run(db, "erreur", envoye=True)
        assert garde.decision_passage(db, TOT)[0] is False


def test_run_en_cours_recent_est_saute_sauf_au_dernier_passage_sans_envoi():
    with SessionLocal() as db:
        _run(db, "en_cours", quand=TOT - timedelta(minutes=10))
        assert garde.decision_passage(db, TOT)[0] is False       # un run travaille : ne pas empiler
        db.query(Run).update({"lance_le": DERNIER - timedelta(minutes=10)})
        db.commit()
        lancer, raison = garde.decision_passage(db, DERNIER)     # fin de fenêtre, rien d'envoyé : le job doit signaler le blocage
        assert lancer is True and "signaler" in raison


def test_run_bloque_depuis_longtemps_est_cloture_par_la_garde():
    with SessionLocal() as db:
        _run(db, "en_cours", quand=datetime.now(timezone.utc) - timedelta(hours=5))
        lancer, _ = garde.decision_passage(db, datetime.now(timezone.utc))
        assert lancer is True                                    # sinon le jour resterait bloqué sans que le job `run` ne s'exécute
        assert db.query(Run).one().statut == "erreur"


def test_main_ecrit_la_sortie_du_workflow_et_laisse_passer_en_cas_de_doute(tmp_path, monkeypatch):
    sortie = tmp_path / "sortie.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(sortie))
    with SessionLocal() as db:
        _run(db, "termine", envoye=True)
    assert garde.main() == 0
    assert "passer=false" in sortie.read_text()

    class BaseHS:
        def __enter__(self):
            raise RuntimeError("base injoignable")
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("app.database.SessionLocal", lambda: BaseHS())
    sortie.write_text("")
    assert garde.main() == 0
    assert "passer=true" in sortie.read_text()                  # doute -> le job `run` décide (double protection)


def test_la_garde_n_importe_aucune_dependance_lourde():
    code = ("import sys; sys.path.insert(0, %r); import app.garde; "
            "print([m for m in ('fastapi', 'requests', 'pydantic', 'uvicorn') if m in sys.modules])" % str(RACINE / "backend"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PATH": "/usr/bin", "DATABASE_URL": "sqlite://"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("[]")


def test_workflow_saute_le_job_run_seulement_pour_un_passage_planifie_inutile():
    yaml = pytest.importorskip("yaml")
    flux = yaml.safe_load((RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))
    jobs = flux["jobs"]
    assert jobs["run"]["if"] == "${{ needs.preparer.outputs.passer != 'false' }}"
    assert jobs["preparer"]["outputs"]["passer"] == "${{ steps.g.outputs.passer }}"
    garde_etape = next(e for e in jobs["preparer"]["steps"] if e.get("id") == "g")
    assert garde_etape["if"] == "${{ github.event_name == 'schedule' }}"          # jamais pour un lancement manuel
    assert "garde.py" in garde_etape["run"] and "requirements" not in garde_etape["run"]   # pas d'installation complète
    assert any("schedule" in str(e.get("if")) for e in jobs["preparer"]["steps"] if e.get("uses", "").startswith("actions/setup-python"))
    # la garde historique reste dans le job `run` : double protection contre les doubles envois
    lancer = next(e for e in jobs["run"]["steps"] if e.get("name") == "Lancer le pipeline")
    assert "--si-aucun-ticket-aujourdhui" in lancer["run"]
    # tentatives de collecte conservées (24 passages) : la configuration du cron doit toujours exister dans le fichier, qu'elle soit active
    # ou temporairement mise en pause en commentaire (pause du 07/11/2026 : « # PAUSE   - cron: »)
    texte = (RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8")
    assert '- cron: "7,27,47 6-13 * * *"' in texte
    if "schedule" in flux[True]:
        assert flux[True]["schedule"][0]["cron"] == "7,27,47 6-13 * * *"
