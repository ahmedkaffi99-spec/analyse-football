"""Script de comparaison des trois moteurs : données de TEST synthétiques uniquement, jamais présentées comme des résultats réels."""
import json
import os
import random
import subprocess
import sys

RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RACINE)

from outils import comparer_moteurs as cm  # noqa: E402


def _obs(n, graine, biais=0.0):
    rnd = random.Random(graine)
    return [{"cle": [f"m{i}", "buts", "over"], "jour": f"2026-10-{1 + i // 10:02d}", "p": 0.6 + biais, "p_marche": 0.6, "cote": 1.7,
             "issue": int(rnd.random() < 0.6), "marche": "buts"} for i in range(n)]


def test_rapport_sans_classement_si_echantillon_insuffisant(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"agent": _obs(20, 1), "central": _obs(20, 1), "deterministe": _obs(20, 1)}), encoding="utf-8")
    texte = cm.rapport(cm.charger(str(f)))
    assert "AUCUN CLASSEMENT" in texte and "agent" in texte and "central" in texte and "deterministe" in texte
    assert "indisponible" in texte                                                      # backtest hors échantillon impossible avec 20 paris


def test_rapport_avec_classement_indicatif_et_backtest(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"agent": _obs(400, 1), "central": _obs(400, 1, 0.1), "deterministe": _obs(400, 1, -0.1)}), encoding="utf-8")
    texte = cm.rapport(cm.charger(str(f)))
    assert "classement par Brier indicatif" in texte and "Backtest hors échantillon : Brier brut" in texte and "n'est pas une preuve" in texte


def test_ligne_de_commande(tmp_path):
    f, sortie = tmp_path / "o.json", tmp_path / "r.md"
    f.write_text(json.dumps({"a": _obs(10, 1), "b": _obs(10, 2)}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", os.path.join(RACINE, "outils", "comparer_moteurs.py"), str(f), "--sortie", str(sortie)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "Comparaison des trois moteurs" in sortie.read_text(encoding="utf-8")
