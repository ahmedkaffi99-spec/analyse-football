"""Correctifs du 07/11/2026 après les runs réels 272-280 : DDL de démarrage tolérant (verrous), finalisation sans schéma, frein de relances désactivable, cote arrondie
acceptée, coût DeepSeek estimé de façon réaliste. Aucun réseau ni base de production ; ces tests ne prouvent aucune rentabilité prédictive."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import database, garde, taches
from app.database import SessionLocal

RACINE = Path(__file__).resolve().parents[2]
for chemin in (RACINE, RACINE / "bet_agent"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))


class FausseConnexion:
    """Répond aux requêtes de lecture du schéma avec des données canoniques et enregistre le DDL demandé."""
    def __init__(self, colonnes=(), rls=None, privileges=None):
        self.colonnes, self.rls, self.privileges, self.ddl = list(colonnes), dict(rls or {}), set(privileges or ()), []

    def execute(self, requete, params=None):
        sql = str(requete)
        if "information_schema.columns" in sql:
            return iter(self.colonnes)
        if "relrowsecurity" in sql:
            return iter(self.rls.items())
        if "has_table_privilege" in sql:
            return SimpleNamespace(scalar=lambda: (params["role"], params["cible"]) in self.privileges)
        self.ddl.append(sql)


def test_colonnes_manquantes_en_lecture_seule():
    c = FausseConnexion(colonnes=[("cotes", "capture_le"), ("jambes", "collecte_le")])
    ajouts = (("cotes", "capture_le", "TIMESTAMPTZ"), ("jambes", "proba_marche_pct", "DOUBLE PRECISION"), ("jambes", "collecte_le", "TIMESTAMPTZ"))
    assert database.colonnes_manquantes(c, ajouts) == [("jambes", "proba_marche_pct", "DOUBLE PRECISION")]
    assert c.ddl == []                                                                  # aucune écriture, donc aucun verrou


def test_regime_etabli_aucun_ddl_de_durcissement():
    tables = [(None, "runs"), (None, "coupons")]
    c = FausseConnexion(rls={"runs": True, "coupons": True}, privileges=set())
    assert database.durcissements_manquants(c, tables, ["anon", "authenticated"]) == []   # RLS déjà actif, aucun droit public : rien à faire


def test_durcissement_seulement_quand_il_manque_quelque_chose():
    tables = [(None, "runs"), (None, "coupons"), ("s", "jambes")]
    c = FausseConnexion(rls={"runs": True, "coupons": False}, privileges={("anon", '"runs"')})
    instr = database.durcissements_manquants(c, tables, ["anon"])
    assert 'ALTER TABLE "coupons" ENABLE ROW LEVEL SECURITY' in instr and 'ALTER TABLE "s"."jambes" ENABLE ROW LEVEL SECURITY' in instr
    assert 'REVOKE ALL ON TABLE "runs" FROM "anon"' in instr
    assert not any('ALTER TABLE "runs"' in i for i in instr)                            # runs a déjà le RLS : pas de verrou inutile


class FauxMoteur:
    def __init__(self, erreur=None):
        self.erreur, self.sql = erreur, []

    def begin(self):
        moteur = self

        class Contexte:
            def __enter__(self_):
                if moteur.erreur:
                    raise moteur.erreur
                return SimpleNamespace(execute=lambda r, p=None: moteur.sql.append(str(r)))

            def __exit__(self_, *a):
                return False
        return Contexte()


def test_ddl_tolerant_pose_un_delai_de_verrou_court(monkeypatch):
    moteur = FauxMoteur()
    monkeypatch.setattr(database, "engine", moteur)
    assert database._ddl_tolerant("ALTER TABLE runs ENABLE ROW LEVEL SECURITY") is True
    assert moteur.sql[0] == f"SET LOCAL lock_timeout = '{database.DELAI_VERROU_DDL}'" and "ENABLE ROW LEVEL SECURITY" in moteur.sql[1]


def test_ddl_tolerant_n_arrete_jamais_le_demarrage_si_la_table_est_verrouillee(monkeypatch):
    monkeypatch.setattr(database, "engine", FauxMoteur(erreur=RuntimeError("canceling statement due to lock timeout")))
    messages = []
    assert database._ddl_tolerant("ALTER TABLE runs ENABLE ROW LEVEL SECURITY", journal=messages.append) is False
    assert messages and "Entretien du schéma ignoré" in messages[0] and "lock timeout" in messages[0]


def test_init_db_sqlite_inchange():
    database.init_db()                                                                  # SQLite (tests) : create_all seulement, aucune requête PostgreSQL


# ---------- finalisation ----------
def test_la_finalisation_ne_touche_jamais_au_schema_ni_ne_cloture(monkeypatch):
    def interdit(*a, **k):
        pytest.fail("la finalisation ne doit ni créer de schéma ni clôturer d'autres runs")
    monkeypatch.setattr(taches, "init_db", interdit)
    monkeypatch.setattr(taches, "cloturer_runs_interrompus", interdit)
    monkeypatch.delenv("COUTS_FICHIER", raising=False)
    assert taches.main(["finaliser"]) == 0


def test_les_autres_taches_initialisent_toujours_la_base(monkeypatch):
    appels = []
    monkeypatch.setattr(taches, "init_db", lambda: appels.append("init"))
    monkeypatch.setattr(taches, "tache_budget", lambda a: 0)
    taches.main(["budget"])
    assert appels == ["init"]


def test_l_etape_de_finalisation_du_workflow_ne_peut_pas_bloquer_le_job():
    import yaml
    wf = yaml.safe_load((RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))
    etape = next(e for e in wf["jobs"]["run"]["steps"] if e.get("name") == "Finaliser le run (coûts conservés)")
    assert etape["timeout-minutes"] <= 5 and etape["continue-on-error"] is True and "always()" in str(etape["if"])


# ---------- frein de relances ----------
def test_frein_de_relances_desactivable_par_zero(monkeypatch):
    monkeypatch.setattr(garde.config, "MAX_ECHECS_PAYANTS_PAR_JOUR", 0)
    with SessionLocal() as db:
        assert garde.relances_payantes_epuisees(db) is False                            # 0 = désactivé (avant : bloquait toutes les relances)
    monkeypatch.setattr(garde.config, "MAX_ECHECS_PAYANTS_PAR_JOUR", -3)
    with SessionLocal() as db:
        assert garde.relances_payantes_epuisees(db) is False
