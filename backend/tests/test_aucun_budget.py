"""07/11/2026 — AUCUN plafond, AUCUNE alerte de budget : c'est le propriétaire qui décide de la dépense. Les coûts restent seulement mesurés (détail des runs, commande « budget »).
Tests locaux ; aucun réseau."""
import inspect
from pathlib import Path

import pytest

from app import config, garde, taches
from app.services import alertes, budget

RACINE = Path(__file__).resolve().parents[2]


def test_plus_aucune_alerte_de_budget_vers_telegram():
    for nom in ("envoyer_alerte_budget", "envoyer_alerte_seuil_budget", "seuil_alerte_budget_pct"):
        assert not hasattr(alertes, nom), nom
    source = inspect.getsource(taches.tache_run)
    assert "budget" not in source.lower()                                               # le run n'envoie plus aucun message « Budget IA »


def test_le_plafond_journalier_n_existe_plus(monkeypatch):
    for valeur in ("0", "1", "3", "n'importe quoi"):
        monkeypatch.setenv("BUDGET_JOUR_USD", valeur)
        assert budget.budget_jour_usd() is None
    assert not hasattr(budget, "budget_restant")


def test_le_cout_reste_mesure_sans_aucune_alerte():
    assert budget.couts_depuis_fichier({"pilote": {"cout_usd": 0.3, "appels_cout_estime": 5}, "vote": [{"cout_usd": 0.2}]}) == {
        "pilote": {"cout_usd": 0.3, "appels_cout_estime": 5}, "vote": [{"cout_usd": 0.2}], "total_usd": 0.5, "source": "fichier_couts"}


def test_le_frein_de_relances_est_desactive_par_defaut():
    assert config.MAX_ECHECS_PAYANTS_PAR_JOUR == 0
    from app.database import SessionLocal
    with SessionLocal() as db:
        assert garde.relances_payantes_epuisees(db) is False


def test_le_workflow_ne_definit_plus_aucune_variable_de_budget():
    import yaml
    texte = (RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8")
    env = yaml.safe_load(texte)["jobs"]["run"]["env"]
    for nom in ("BUDGET_JOUR_USD", "OMBRE_BUDGET_USD", "BUDGET_ALERTE_PCT", "BUDGET_MIN_PAR_MODELE_USD"):
        assert nom not in env, nom
    assert env["MAX_ECHECS_PAYANTS_PAR_JOUR"] == "${{ vars.MAX_ECHECS_PAYANTS_PAR_JOUR || '0' }}"
