"""Tests de moteur_central/contrat_adapter.py — aucun appel réseau, aucun appel Supabase.

Couvre exactement les exigences mandatées : comparaison de la branche "avec Prediction" au
vrai moteur/contrat.py (jamais modifié) ; toutes les clés du schéma commun pour les candidats
"moteur" et "bet_agent" ; champs None, cotes absentes, probabilité calibrée absente, raisons
vides, décisions retenu/rejeté ; unités et valeurs exactes de edge_pct/proba_pct/
proba_calibree_pct ; aucune donnée d'origine perdue, aucun modèle inventé."""

from datetime import datetime, timezone

from moteur import contrat as mcontrat
from moteur.modeles.registre import Prediction

from moteur_central.contrat_adapter import CLES_SCHEMA_COMMUN, convertir
from moteur_central.score_central import CandidatCentral


def _candidat_bet_agent(**overrides):
    base = dict(
        match="Arsenal - Chelsea", marche="resultat", selection="1", cote=1.8,
        moteur_responsable="bet_agent", proba_pct=58.0,
    )
    base.update(overrides)
    return CandidatCentral(**base)


def _candidat_moteur(**overrides):
    base = dict(
        match="Lyon - Marseille", marche="btts", selection="oui", cote=1.9,
        moteur_responsable="moteur", proba_pct=55.0,
    )
    base.update(overrides)
    return CandidatCentral(**base)


def _prediction_reelle():
    # Issues binaires valides (demi_gagne + rembourse + demi_perdu == 0 -> binaire=True).
    issues = {"gagne": 0.62, "demi_gagne": 0.0, "rembourse": 0.0, "demi_perdu": 0.0, "perdu": 0.38}
    return Prediction(
        modele=3, nom_modele="poisson_dixon_coles", marche="btts", ligne=None,
        selection="oui", issues=issues, parametres={"rho": 0.0, "mu_home": 1.4, "mu_away": 1.1},
    )


class TestToutesLesClesPresentes:
    def test_candidat_bet_agent_sans_prediction(self):
        candidat = _candidat_bet_agent()
        resultat = convertir(candidat)
        assert set(resultat.keys()) == set(CLES_SCHEMA_COMMUN)

    def test_candidat_moteur_sans_prediction(self):
        candidat = _candidat_moteur()
        resultat = convertir(candidat)
        assert set(resultat.keys()) == set(CLES_SCHEMA_COMMUN)

    def test_candidat_avec_prediction_reelle(self):
        candidat = _candidat_moteur()
        resultat = convertir(candidat, prediction=_prediction_reelle())
        assert set(resultat.keys()) == set(CLES_SCHEMA_COMMUN)


class TestSourceJamaisConfondueAvecLeModele:
    def test_source_bet_agent(self):
        resultat = convertir(_candidat_bet_agent())
        assert resultat["source"] == "bet_agent"
        assert resultat["model"] is None
        assert resultat["model_name"] is None

    def test_source_moteur_sans_prediction(self):
        resultat = convertir(_candidat_moteur())
        assert resultat["source"] == "moteur"
        assert resultat["model"] is None  # aucune Prediction fournie -> jamais un modèle inventé
        assert resultat["model_name"] is None

    def test_source_moteur_avec_prediction(self):
        resultat = convertir(_candidat_moteur(), prediction=_prediction_reelle())
        assert resultat["source"] == "moteur"
        assert resultat["model"] == 3
        assert resultat["model_name"] == "poisson_dixon_coles"


class TestNonRegressionVersLeContratReel:
    """La branche "avec Prediction" ne doit JAMAIS diverger de moteur/contrat.py:prediction()
    pour les champs dont celui-ci reste seul responsable."""

    def test_champs_du_contrat_identiques_a_lappel_direct(self):
        pred = _prediction_reelle()
        horodatage = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attendu = mcontrat.prediction(match_id=None, p=pred, horodatage=horodatage)
        obtenu = convertir(_candidat_moteur(), prediction=pred, horodatage=horodatage)
        for cle in ("model", "model_name", "market", "line", "selection", "raw_probability",
                    "probability", "calibrated", "calibration_n", "binary", "model_version",
                    "features_version", "parameters", "timestamp"):
            assert obtenu[cle] == attendu[cle], f"{cle} : {obtenu[cle]!r} != {attendu[cle]!r}"

    def test_market_et_selection_ne_sont_pas_ecrases_par_le_candidat(self):
        # Le candidat a un marché/sélection DIFFÉRENTS de la Prediction fournie : la sortie doit
        # suivre la Prediction (seule source de vérité pour cette branche), jamais le candidat.
        candidat = _candidat_bet_agent(marche="resultat", selection="1")
        pred = _prediction_reelle()  # marche="btts", selection="oui"
        resultat = convertir(candidat, prediction=pred)
        assert resultat["market"] == "btts"
        assert resultat["selection"] == "oui"

    def test_raw_probability_et_probability_viennent_de_la_prediction(self):
        pred = _prediction_reelle()
        resultat = convertir(_candidat_moteur(), prediction=pred)
        assert resultat["raw_probability"] == pred.probabilite == 0.62
        assert resultat["probability"] == 0.62
        assert resultat["binary"] is True


class TestChampsAbsentsGeresExplicitement:
    def test_cote_absente(self):
        candidat = _candidat_bet_agent(cote=None)
        resultat = convertir(candidat)
        assert resultat["odds"] is None
        assert resultat["implied_probability"] is None
        # edge_pct peut rester fourni indépendamment (non recalculé à partir de la cote) ;
        # ici il n'a pas été fourni par le candidat non plus.
        assert resultat["edge_pct"] is None
        assert resultat["edge"] is None

    def test_cote_invalide_inferieure_ou_egale_a_1(self):
        candidat = _candidat_bet_agent(cote=1.0)
        resultat = convertir(candidat)
        assert resultat["implied_probability"] is None

    def test_probabilite_calibree_absente(self):
        candidat = _candidat_bet_agent(proba_calibree_pct=None)
        resultat = convertir(candidat)
        assert resultat["proba_calibree_pct"] is None
        assert resultat["calibrated"] is False
        # Sans calibrée, probability retombe sur proba_pct brute.
        assert resultat["probability"] == candidat.proba_pct / 100

    def test_probabilite_calibree_presente(self):
        candidat = _candidat_bet_agent(proba_pct=58.0, proba_calibree_pct=52.5)
        resultat = convertir(candidat)
        assert resultat["calibrated"] is True
        assert resultat["probability"] == 0.525
        assert resultat["raw_probability"] == 0.58

    def test_raisons_vides_par_defaut(self):
        candidat = _candidat_bet_agent()
        assert candidat.raisons == []
        resultat = convertir(candidat)
        assert resultat["reasons"] == []

    def test_raisons_du_candidat_preservees_si_non_ecrasees(self):
        candidat = _candidat_bet_agent(raisons=["edge positif", "H2H favorable"])
        resultat = convertir(candidat)
        assert resultat["reasons"] == ["edge positif", "H2H favorable"]

    def test_raisons_explicitement_fournies_remplacent_celles_du_candidat(self):
        candidat = _candidat_bet_agent(raisons=["ancienne raison"])
        resultat = convertir(candidat, raisons=["nouvelle raison"])
        assert resultat["reasons"] == ["nouvelle raison"]

    def test_raisons_vide_explicitement_fournie_nest_pas_confondue_avec_absente(self):
        candidat = _candidat_bet_agent(raisons=["gardée si non écrasée"])
        resultat = convertir(candidat, raisons=[])
        assert resultat["reasons"] == []


class TestDecisionJamaisDevinee:
    def test_decision_none_par_defaut(self):
        resultat = convertir(_candidat_bet_agent())
        assert resultat["decision"] is None

    def test_decision_retenu(self):
        resultat = convertir(_candidat_bet_agent(), retenu=True)
        assert resultat["decision"] == "retenu"

    def test_decision_rejete(self):
        resultat = convertir(_candidat_bet_agent(), retenu=False)
        assert resultat["decision"] == "rejeté"


class TestUnitesEtValeursExactes:
    def test_edge_pct_preserve_sans_recalcul(self):
        candidat = _candidat_bet_agent(edge_pct=12.3456)
        resultat = convertir(candidat)
        assert resultat["edge_pct"] == 12.3456  # valeur brute, jamais recalculée

    def test_edge_fraction_est_edge_pct_divise_par_100(self):
        candidat = _candidat_bet_agent(edge_pct=12.3456)
        resultat = convertir(candidat)
        assert resultat["edge"] == 12.3456 / 100

    def test_proba_pct_et_proba_calibree_pct_bruts_preserves(self):
        candidat = _candidat_bet_agent(proba_pct=58.0, proba_calibree_pct=52.5)
        resultat = convertir(candidat)
        assert resultat["proba_pct"] == 58.0
        assert resultat["proba_calibree_pct"] == 52.5

    def test_implied_probability_coherente_avec_moteur_cotes(self):
        from moteur import cotes as mcotes
        candidat = _candidat_bet_agent(cote=2.0)
        resultat = convertir(candidat)
        assert resultat["implied_probability"] == mcotes.proba_implicite(2.0) == 0.5


class TestAucuneDonneeDoriginePerdue:
    def test_competition_fixture_id_historique_preserves(self):
        hist = {"disponible": True, "n": 42, "win_rate": 0.6}
        candidat = _candidat_bet_agent(
            competition="Premier League", fixture_id_oddspapi="fx-123", historique_marche=hist,
        )
        resultat = convertir(candidat)
        assert resultat["competition"] == "Premier League"
        assert resultat["fixture_id_oddspapi"] == "fx-123"
        assert resultat["historique_marche"] is hist

    def test_match_id_toujours_none_jamais_assimile_a_fixture_id(self):
        candidat = _candidat_bet_agent(fixture_id_oddspapi="fx-999")
        resultat = convertir(candidat)
        assert resultat["match_id"] is None
        assert resultat["fixture_id_oddspapi"] == "fx-999"

    def test_calibration_n_jamais_confondu_avec_historique_marche_n(self):
        hist = {"disponible": True, "n": 42, "win_rate": 0.6}
        candidat = _candidat_bet_agent(historique_marche=hist)
        resultat = convertir(candidat)
        assert resultat["calibration_n"] is None
        assert resultat["historique_marche"]["n"] == 42

    def test_odds_et_selection_du_candidat_preserves_sans_prediction(self):
        candidat = _candidat_bet_agent(cote=1.75, selection="X")
        resultat = convertir(candidat)
        assert resultat["odds"] == 1.75
        assert resultat["selection"] == "X"
        assert resultat["market"] == candidat.marche


class TestAucunModeleInvente:
    def test_sans_prediction_model_version_et_features_version_restent_none(self):
        resultat = convertir(_candidat_bet_agent())
        assert resultat["model_version"] is None
        assert resultat["features_version"] is None
        assert resultat["parameters"] is None
        assert resultat["binary"] is None
        assert resultat["calibration_n"] is None

    def test_bookmaker_et_odds_timestamp_jamais_devines(self):
        resultat = convertir(_candidat_bet_agent())
        assert resultat["bookmaker"] is None
        assert resultat["odds_timestamp"] is None
