"""Tests de la désactivation RÉVERSIBLE de POIDS_MARCHE (audit du 11/10/2026, "faire évoluer le
moteur à partir des rapports historiques", section 3 : "prépare une désactivation réversible de
son influence sur les prédictions, sans supprimer le code ni les données historiques des
cotes"). POIDS_MARCHE_OVERRIDE (env) prend le dessus sur la constante 0.65 si définie — jamais
en production tant que personne ne la définit explicitement (aucune variable d'environnement de
ce nom n'est câblée dans .github/workflows/pipeline-quotidien.yml par ce correctif)."""

import importlib
import os

import pytest

import analyser_et_envoyer as ae


@pytest.fixture
def poids_marche_a_zero():
    """Recharge ae avec POIDS_MARCHE_OVERRIDE=0, puis recharge TOUJOURS ae à la valeur par
    défaut en sortie — y compris si le test échoue — pour qu'aucune autre suite (ex.
    moteur_central/tests/test_melange.py, qui compare à ae.POIDS_MARCHE==0.65) n'hérite d'une
    constante surchargée. Restauration faite HORS de toute variable d'environnement patchée :
    un `importlib.reload` exécuté alors que POIDS_MARCHE_OVERRIDE est encore dans os.environ
    ne restaurerait rien (bug constaté en écrivant ce test — la restauration doit arriver
    après la suppression de la variable, pas seulement après le `try`/`finally` mal placé)."""
    ancien = os.environ.get("POIDS_MARCHE_OVERRIDE")
    os.environ["POIDS_MARCHE_OVERRIDE"] = "0"
    importlib.reload(ae)
    try:
        yield ae
    finally:
        if ancien is None:
            os.environ.pop("POIDS_MARCHE_OVERRIDE", None)
        else:
            os.environ["POIDS_MARCHE_OVERRIDE"] = ancien
        importlib.reload(ae)  # exécuté APRÈS restauration de l'environnement


class TestValeurParDefautInchangee:
    def test_sans_variable_environnement_poids_marche_vaut_0_65(self):
        # Reproduit le test déjà existant (test_backtest_production.py) : non-régression
        # explicite sur la valeur par défaut, pour que ce correctif ne puisse jamais la faire
        # dériver silencieusement.
        assert ae.POIDS_MARCHE == 0.65


class TestSurchargeReversible:
    def test_poids_marche_override_change_la_constante_au_rechargement(self, poids_marche_a_zero):
        assert poids_marche_a_zero.POIDS_MARCHE == 0.0

    def test_restauration_apres_le_test(self):
        # Test séparé, exécuté après un test utilisant la fixture ci-dessus (ordre de
        # déclaration) : si la restauration de la fixture avait le même bug que celui corrigé
        # ici, ae.POIDS_MARCHE resterait à 0.0 et ce test échouerait.
        assert ae.POIDS_MARCHE == 0.65

    def test_poids_marche_a_zero_rend_la_probabilite_purement_modele(self, poids_marche_a_zero):
        """Avec POIDS_MARCHE=0, evaluer_marches_toutes doit renvoyer EXACTEMENT la probabilité
        du modèle (p_modele), jamais mélangée au marché — vérifie la formule réelle
        (p = (1-POIDS_MARCHE)*p_modele + POIDS_MARCHE*p_marche), pas seulement la constante."""
        from cas_synthetiques_demo import CAS_SYNTHETIQUES_DEMO

        ae_zero = poids_marche_a_zero
        for marches, _ in CAS_SYNTHETIQUES_DEMO:
            mu_home, mu_away, _, _, _ = ae_zero.estimer_expected_goals_depuis_marches(marches)
            candidats_modele_seul = ae_zero.evaluer_marches_toutes(marches, mu_home, mu_away)
            candidats_bruts = ae_zero._evaluer_marches_brut(marches, mu_home, mu_away)
            par_cle = {(c["marche"], c["selection"]): c["proba_modele_pct"] for c in candidats_bruts}
            for c in candidats_modele_seul:
                brut = par_cle.get((c["marche"], c["selection"]))
                if brut is not None:
                    assert abs(c["proba_modele_pct"] - round(brut, 1)) < 0.2, (
                        f"{c['marche']}/{c['selection']} : attendu ≈{brut} (modèle pur), "
                        f"obtenu {c['proba_modele_pct']} (POIDS_MARCHE=0 n'annule pas le marché)")
