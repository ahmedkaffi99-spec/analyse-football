"""Tests de scripts/audit_historique/backtest_complet.py — uniquement les fonctions qui ne
nécessitent ni base de données réelle ni moteur.backtest (charger_depuis_cache, resume) :
charger_depuis_cache lit des fichiers JSON synthétiques créés pour l'occasion (jamais présentés
comme des matchs réels), resume() est testée sur des résultats synthétiques. executer_grille et
charger_depuis_db ne sont pas testées ici : elles n'ont de sens que contre de vraies données
(voir docs/audit_moteur_unique_20_combinaisons.md pour les résultats réels obtenus en les
exécutant directement)."""

import importlib.util
import json
import sys
from pathlib import Path

CHEMIN_MODULE = Path(__file__).resolve().parents[1] / "scripts" / "audit_historique" / "backtest_complet.py"
spec = importlib.util.spec_from_file_location("backtest_complet", CHEMIN_MODULE)
backtest_complet = importlib.util.module_from_spec(spec)
sys.modules["backtest_complet"] = backtest_complet
spec.loader.exec_module(backtest_complet)


class TestChargerDepuisCache:
    def test_fichier_absent_renvoie_none(self, tmp_path):
        assert backtest_complet.charger_depuis_cache(tmp_path, 39, 2024) is None

    def test_liste_nue(self, tmp_path):
        (tmp_path / "39_2024.json").write_text(json.dumps([{"match_id": 1}]))
        assert backtest_complet.charger_depuis_cache(tmp_path, 39, 2024) == [{"match_id": 1}]

    def test_format_payload_liste(self, tmp_path):
        (tmp_path / "39_2024.json").write_text(json.dumps({"payload": [{"match_id": 1}]}))
        assert backtest_complet.charger_depuis_cache(tmp_path, 39, 2024) == [{"match_id": 1}]

    def test_format_payload_chaine_json(self, tmp_path):
        # Format brut d'un export SQL : "payload" est une chaîne JSON, pas déjà une liste.
        (tmp_path / "39_2024.json").write_text(json.dumps({"payload": json.dumps([{"match_id": 1}])}))
        assert backtest_complet.charger_depuis_cache(tmp_path, 39, 2024) == [{"match_id": 1}]


class TestResume:
    def test_combinaison_indisponible(self):
        texte = backtest_complet.resume({"Ligue X 2024/2025": {"indisponible": "aucun match trouvé"}})
        assert "INDISPONIBLE" in texte
        assert "aucun match trouvé" in texte

    def test_combinaison_disponible_affiche_les_metriques(self):
        resultat = {"n_matchs": 10, "global": {"n_predictions": 100, "brier": 0.21, "log_loss": 0.65}}
        texte = backtest_complet.resume({"Ligue X 2024/2025": resultat})
        assert "n_matchs=  10" in texte
        assert "brier=0.2100" in texte
        assert "log_loss=0.6500" in texte
