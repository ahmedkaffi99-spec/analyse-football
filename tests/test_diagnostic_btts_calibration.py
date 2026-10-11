"""Tests de scripts/audit_historique/diagnostic_btts_calibration.py — fonctions pures
(correlation, brier_skill_score, decouper_chronologique) et non-régression/anti-fuite sur
ajuster_isotone/ajuster_platt avec des lignes SYNTHÉTIQUES (jamais présentées comme de vraies
prédictions — les vrais chiffres mesurés sur hist_matchs sont dans
docs/diagnostic_btts_calibration.md, pas ici)."""

import importlib.util
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHEMIN_MODULE = Path(__file__).resolve().parents[1] / "scripts" / "audit_historique" / "diagnostic_btts_calibration.py"
spec = importlib.util.spec_from_file_location("diagnostic_btts_calibration", CHEMIN_MODULE)
diag = importlib.util.module_from_spec(spec)
sys.modules["diagnostic_btts_calibration"] = diag
# L'exécution du module importe moteur.* en tête de fonctions seulement (pas au niveau module),
# donc son chargement ne nécessite pas que "moteur" soit sur sys.path.
spec.loader.exec_module(diag)


@dataclass
class _LignePourTest:
    """Objet minimal portant exactement les attributs lus par ajuster_isotone/ajuster_platt/
    appliquer_isotone/appliquer_platt/decouper_chronologique — jamais le vrai moteur.backtest.Ligne
    (pas nécessaire pour tester ces fonctions isolément)."""
    modele: int
    marche: str
    proba_brute: float
    gagne: int
    binaire: bool
    date: datetime


class TestCorrelation:
    def test_parfaitement_correlee(self):
        points = [(0.1, 0), (0.9, 1), (0.2, 0), (0.8, 1)]
        assert diag.correlation(points) > 0.9

    def test_aucune_correlation_renvoie_proche_de_zero(self):
        # Probabilité constante -> variance nulle du côté x -> corrélation définie à 0 (garde-fou).
        points = [(0.5, 0), (0.5, 1), (0.5, 0), (0.5, 1)]
        assert diag.correlation(points) == 0.0

    def test_liste_vide_ne_plante_pas(self):
        assert diag.correlation([]) == 0.0


class TestBrierSkillScore:
    def test_pire_que_deviner_0_5_est_negatif(self):
        # brier > 0.25 (baseline) -> skill score négatif, signal explicite de non-qualité
        # (jamais visible sur le seul Brier Score global, voir la mission).
        points = [(0.9, 0)] * 10 + [(0.9, 1)]  # très confiant et très souvent faux
        assert diag.brier_skill_score(points) < 0

    def test_prediction_parfaite_vaut_1(self):
        points = [(1.0, 1), (0.0, 0)]
        assert diag.brier_skill_score(points) == 1.0


class TestDecouperChronologique:
    def _lignes(self, n):
        depart = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [_LignePourTest(1, "x", 0.5, i % 2, True, depart + timedelta(days=i)) for i in range(n)]

    def test_proportions_respectees(self):
        train, val, test = diag.decouper_chronologique(self._lignes(100))
        assert len(train) == 60 and len(val) == 20 and len(test) == 20

    def test_aucune_fuite_chronologique_train_ne_depasse_jamais_validation(self):
        """Test ANTI-FUITE explicite (demande de la mission) : aucune ligne de `train` ne doit
        avoir une date postérieure à la plus ancienne ligne de `validation`, et aucune ligne de
        `validation` une date postérieure à la plus ancienne ligne de `test` — sinon le futur
        fuiterait dans l'ajustement."""
        lignes = self._lignes(100)
        # Mélange l'ordre d'entrée : decouper_chronologique doit re-trier par date lui-même,
        # jamais faire confiance à l'ordre reçu (sinon une fuite serait possible si l'appelant
        # oublie de trier).
        import random

        melange = lignes[:]
        random.Random(42).shuffle(melange)
        train, val, test = diag.decouper_chronologique(melange)
        assert max(ln.date for ln in train) <= min(ln.date for ln in val)
        assert max(ln.date for ln in val) <= min(ln.date for ln in test)


class TestIsotoneNonRegression:
    def _lignes(self, n, depart_jour=0):
        depart = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=depart_jour)
        # Modèle sciemment surconfiant (annonce 0.9, gagne 60% du temps) — l'isotone doit le
        # corriger vers ~0.6, exactement comme déjà vérifié pour Isotone seule dans
        # moteur/tests/test_moteur.py::test_isotone_monotone_et_corrige_une_surconfiance.
        return [_LignePourTest(1, "x", 0.9, 1 if i % 10 < 6 else 0, True, depart + timedelta(hours=i)) for i in range(n)]

    def test_ajuster_puis_appliquer_corrige_la_surconfiance(self):
        train = self._lignes(200)
        cal = diag.ajuster_isotone(train, min_n=100)
        cible = self._lignes(10, depart_jour=100)
        resultat = diag.appliquer_isotone(cal, cible)
        probas_calibrees = {p for p, _ in resultat}
        assert all(abs(p - 0.6) < 0.05 for p in probas_calibrees)

    def test_echantillon_insuffisant_renvoie_la_proba_brute_inchangee(self):
        train = self._lignes(10)  # < min_n
        cal = diag.ajuster_isotone(train, min_n=100)
        cible = self._lignes(3, depart_jour=50)
        resultat = diag.appliquer_isotone(cal, cible)
        assert all(p == 0.9 for p, _ in resultat)  # proba brute conservée, jamais devinée

    def test_isotone_najuste_jamais_sur_les_donnees_cibles(self):
        """Anti-fuite : ajuster() ne doit lire QUE `train` — falsifier `cible` après coup ne
        doit rien changer au résultat déjà calculé à partir du calibrateur ajusté sur train."""
        train = self._lignes(200)
        cal = diag.ajuster_isotone(train, min_n=100)
        cible_originale = self._lignes(5, depart_jour=100)
        resultat_avant = diag.appliquer_isotone(cal, cible_originale)
        for ln in cible_originale:
            ln.gagne = 1 - ln.gagne  # falsifie les labels APRÈS l'ajustement du calibrateur
        resultat_apres = diag.appliquer_isotone(cal, cible_originale)
        probas_avant = [p for p, _ in resultat_avant]
        probas_apres = [p for p, _ in resultat_apres]
        assert probas_avant == probas_apres  # la proba calibrée ne dépend pas du label de la cible
