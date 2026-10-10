"""Audit du 09/10/2026 (demande explicite) : OddsPapi (quota 250/jour) et API-Football sont-ils
indépendants, et une panne OddsPapi (429) peut-elle bloquer/ralentir/gonfler la consommation
API-Football ? Tests hors-ligne (aucun appel réseau réel) : python -m pytest test_collecte_donnees.py"""

from types import SimpleNamespace
from unittest import mock

import pytest

import collecte_donnees as cd


def _reponse(status_code, texte="", donnees=None):
    r = mock.Mock()
    r.status_code = status_code
    r.text = texte
    r.json = mock.Mock(return_value=donnees if donnees is not None else [])
    return r


class TestClassificationDes429OddsPapi:
    """Deux 429 très différents (voir cd._lever_si_429_oddspapi) : le quota journalier épuisé
    (jamais la peine de réessayer) et une limite de vitesse passagère (réessayer après une
    pause). Les confondre a déjà causé une vraie régression (03/10/2026, run 104)."""

    def test_quota_epuise_leve_une_exception_dediee(self):
        r = _reponse(429, texte='{"error":{"code":"REQUEST_LIMIT_EXCEEDED","message":"Request limit exceeded"}}')
        with pytest.raises(cd.QuotaOddsPapiEpuise):
            cd._lever_si_429_oddspapi(r)

    def test_limite_de_vitesse_passagere_leve_une_autre_exception(self):
        r = _reponse(429, texte='{"error":{"code":"RATE_LIMITED"}}')
        with pytest.raises(ValueError):
            cd._lever_si_429_oddspapi(r)

    def test_statut_200_ne_leve_rien(self):
        cd._lever_si_429_oddspapi(_reponse(200))  # ne doit lever aucune exception


class TestAucunRetryQuandLeQuotaEstReellementEpuise:
    """QuotaOddsPapiEpuise est explicitement exclu du retry tenacity (retry_if_not_exception_type)
    — réessayer un quota épuisé ne peut jamais réussir et gaspillerait des requêtes."""

    def test_telecharger_fixtures_un_seul_appel_reseau_si_quota_epuise(self, monkeypatch):
        appels = []

        def _get(url, **kwargs):
            appels.append(url)
            return _reponse(429, texte='{"error":{"code":"REQUEST_LIMIT_EXCEEDED","message":"Request limit exceeded of 250"}}')

        monkeypatch.setattr(cd.SESSION_ODDSPAPI, "get", _get)
        with pytest.raises(cd.QuotaOddsPapiEpuise):
            cd._telecharger_fixtures_oddspapi()
        assert len(appels) == 1  # pas de retry : un quota épuisé ne se résout jamais en réessayant


class TestRecupererFixturesApiFootballIndependantDOddspapi:
    """recuperer_fixtures_api_football() n'appelle jamais OddsPapi — deux fournisseurs, deux
    clés, deux quotas totalement séparés (pas de dépendance directe entre les deux APIs)."""

    def test_toujours_exactement_3_appels_hier_aujourdhui_demain(self, monkeypatch):
        appels = []

        def _get(url, **kwargs):
            appels.append(url)
            return _reponse(200, donnees={"response": [], "errors": None})

        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)
        monkeypatch.setattr(cd.SESSION, "get", _get)
        cd.recuperer_fixtures_api_football()
        assert len(appels) == 3
        assert all("v3.football.api-sports.io" in u for u in appels)

    def test_naffecte_jamais_oddspapi(self, monkeypatch):
        """Aucune des deux URLs appelées par recuperer_fixtures_api_football() ne pointe vers
        oddspapi.io — confirme l'absence de lien direct entre les deux quotas."""
        appels = []
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)
        monkeypatch.setattr(cd.SESSION, "get",
                            lambda url, **kw: appels.append(url) or _reponse(200, donnees={"response": []}))
        cd.recuperer_fixtures_api_football()
        assert not any("oddspapi" in u for u in appels)


class TestResilienceCollecterDonneesPanneOddsPapi:
    """Constaté en production le 08-09/10/2026 : quand OddsPapi répond 429 (quota épuisé), le
    run se termine en 0/0 match exploitable. Vérifie ICI que ce n'est pas une panne API-Football
    qui se propage, et que la panne OddsPapi ne fait JAMAIS consommer plus d'appels API-Football
    (au contraire : moins, car la boucle par match ne s'exécute sur aucun candidat)."""

    @pytest.fixture(autouse=True)
    def _environnement_sans_selection_manuelle(self, monkeypatch, tmp_path):
        # Isole le test de tout état d'environnement réel (sélection manuelle, filtre ligues...).
        monkeypatch.setattr(cd, "MATCHS_MANUELS_ENV", "", raising=False)
        monkeypatch.setattr(cd, "SELECTION_MANUELLE_ACTIVE", False, raising=False)
        monkeypatch.setattr(cd, "MATCHS_MANUELS_DATES", set(), raising=False)
        monkeypatch.setattr(cd, "COMPLEMENT_AUTOMATIQUE_ACTIF", False, raising=False)
        monkeypatch.setattr(cd, "FILTRE_LIGUES_UNIQUES", None, raising=False)
        monkeypatch.setattr(cd, "SORTIE_JSON", str(tmp_path / "donnees_collectees.json"))

    def test_echec_oddspapi_quota_epuise_naugmente_jamais_les_appels_api_football(self, monkeypatch):
        appels_api_football = []

        def _oddspapi_en_panne():
            raise cd.QuotaOddsPapiEpuise("429 quota OddsPapi du jour épuisé — test")

        def _api_football_falsifie():
            appels_api_football.append(1)
            return []

        monkeypatch.setattr(cd, "_telecharger_fixtures_oddspapi", _oddspapi_en_panne)
        monkeypatch.setattr(cd, "recuperer_fixtures_api_football", _api_football_falsifie)
        monkeypatch.setattr(cd, "collecter_contexte_serper", lambda *a, **k: None)

        cd.collecter_donnees()

        # L'échec OddsPapi (capturé par le try/except interne de collecter_donnees) laisse
        # matchs_a_traiter vide -> recuperer_fixtures_api_football() n'est PAS appelé : la
        # panne OddsPapi ne déclenche aucun appel API-Football supplémentaire (ni même les 3
        # habituels), elle ne fait que réduire la consommation à zéro pour ce run.
        assert appels_api_football == []

    def test_matchs_disponibles_cote_appelle_bien_api_football_une_fois(self, monkeypatch):
        """Contre-épreuve : quand OddsPapi renvoie au moins un match exploitable, l'appel
        API-Football (identification/stats) a bien lieu comme avant — la résilience à la panne
        OddsPapi ne doit jamais supprimer la collecte quand les cotes sont disponibles."""
        appels_api_football = []

        fixture_avec_cotes = {
            "participant1Name": "Lens", "participant2Name": "Auxerre", "hasOdds": True,
            "statusName": "Pre-Game", "startTime": "2099-01-01T00:00:00Z",
            "tournamentName": "Ligue 1", "categoryName": "France", "fixtureId": "fxLENSAUX",
        }

        def _api_football_falsifie():
            appels_api_football.append(1)
            return []

        monkeypatch.setattr(cd, "_telecharger_fixtures_oddspapi", lambda: [fixture_avec_cotes])
        monkeypatch.setattr(cd, "recuperer_fixtures_api_football", _api_football_falsifie)
        monkeypatch.setattr(cd, "assez_tot_avant_coup_envoi", lambda *a, **k: True)
        monkeypatch.setattr(cd, "recuperer_marches_pour_fixture", lambda *a, **k: [])
        monkeypatch.setattr(cd, "collecter_contexte_serper", lambda *a, **k: None)

        cd.collecter_donnees()

        assert appels_api_football == [1]


class TestBasculeFournisseurCotesApiFootball:
    """Migration minimale, réversible (FOURNISSEUR_COTES, demande explicite du 10/10/2026) :
    par défaut ("oddspapi"), zéro changement de comportement. Réutilise uniquement
    adaptateur_api_football.capturer_api_football_adapte (jamais dupliqué ici)."""

    def test_defaut_reste_oddspapi_zero_changement(self):
        assert cd.FOURNISSEUR_COTES == "oddspapi"

    def _resultat(self, **kwargs):
        from adaptateur_api_football import ResultatAdaptateur
        return ResultatAdaptateur(**kwargs)

    def test_marches_valides_renvoyes(self, monkeypatch):
        marches = [{"marche_id": "1", "marche": "Full Time Result", "type": "", "handicap": None,
                   "periode": None, "selections": [{"selection": "1", "cote": 2.0}]},
                  {"marche_id": "2", "marche": "Asian Handicap", "type": "", "handicap": -1.25,
                   "periode": None, "selections": [{"selection": "1", "cote": 1.9}]}]
        resultat = self._resultat(marches=marches)
        import adaptateur_api_football as adf
        monkeypatch.setattr(adf, "capturer_api_football_adapte", lambda *a, **k: resultat)
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)

        tous = cd.recuperer_marches_pour_fixture_api_football(12345)

        assert tous is not None
        noms = {m["marche"] for m in tous}
        assert noms == {"Full Time Result"}  # Asian Handicap jamais activé, même renvoyé par l'adaptateur

    def test_asian_handicap_jamais_active_meme_si_seul_marche_disponible(self, monkeypatch):
        marches = [{"marche_id": "2", "marche": "Asian Handicap", "type": "", "handicap": -1.25,
                   "periode": None, "selections": [{"selection": "1", "cote": 1.9}]}]
        resultat = self._resultat(marches=marches)
        import adaptateur_api_football as adf
        monkeypatch.setattr(adf, "capturer_api_football_adapte", lambda *a, **k: resultat)
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)

        assert cd.recuperer_marches_pour_fixture_api_football(1) is None

    def test_cote_perimee_jamais_presentee_comme_actuelle(self, monkeypatch):
        resultat = self._resultat(perime=True, age_secondes=999.0,
                                  marches_perimes=[{"marche": "Full Time Result"}])
        import adaptateur_api_football as adf
        monkeypatch.setattr(adf, "capturer_api_football_adapte", lambda *a, **k: resultat)
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)

        assert cd.recuperer_marches_pour_fixture_api_football(1) is None

    def test_429_jamais_de_marche_invente_et_jamais_de_retry(self, monkeypatch):
        appels = []
        resultat = self._resultat(quota_epuise=True, erreur="quota_api_football_epuise_ou_limite_debit")
        import adaptateur_api_football as adf

        def _capture(*a, **k):
            appels.append(1)
            return resultat

        monkeypatch.setattr(adf, "capturer_api_football_adapte", _capture)
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)

        assert cd.recuperer_marches_pour_fixture_api_football(1) is None
        assert len(appels) == 1  # jamais de retry automatique sur un 429

    def test_erreur_reseau_jamais_de_marche_invente(self, monkeypatch):
        resultat = self._resultat(erreur="timeout")
        import adaptateur_api_football as adf
        monkeypatch.setattr(adf, "capturer_api_football_adapte", lambda *a, **k: resultat)
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)

        assert cd.recuperer_marches_pour_fixture_api_football(1) is None

    def test_compteur_appels_incremente_meme_en_echec(self, monkeypatch):
        import adaptateur_api_football as adf
        monkeypatch.setattr(adf, "capturer_api_football_adapte",
                            lambda *a, **k: self._resultat(erreur="timeout"))
        monkeypatch.setattr(cd, "_respecter_rate_limit_api_football", lambda: None)
        avant = cd._appels_odds_api_football_consommes
        cd.recuperer_marches_pour_fixture_api_football(1)
        assert cd._appels_odds_api_football_consommes == avant + 1

    def test_bascule_appelle_la_bonne_fonction_selon_le_flag(self, monkeypatch):
        """Vérifie le point d'intégration dans collecter_donnees() lui-même : le flag décide
        strictement laquelle des deux fonctions est appelée, jamais les deux."""
        appels_oddspapi, appels_api_football = [], []
        fixture_avec_cotes = {
            "participant1Name": "Lens", "participant2Name": "Auxerre", "hasOdds": True,
            "statusName": "Pre-Game", "startTime": "2099-01-01T00:00:00Z",
            "tournamentName": "Ligue 1", "categoryName": "France", "fixtureId": "fxLENSAUX",
        }
        monkeypatch.setattr(cd, "MATCHS_MANUELS_ENV", "", raising=False)
        monkeypatch.setattr(cd, "SELECTION_MANUELLE_ACTIVE", False, raising=False)
        monkeypatch.setattr(cd, "MATCHS_MANUELS_DATES", set(), raising=False)
        monkeypatch.setattr(cd, "COMPLEMENT_AUTOMATIQUE_ACTIF", False, raising=False)
        monkeypatch.setattr(cd, "FILTRE_LIGUES_UNIQUES", None, raising=False)
        fixture_af = {"teams": {"home": {"name": "Lens", "id": 1}, "away": {"name": "Auxerre", "id": 2}},
                     "league": {"id": 10, "name": "Ligue 1", "season": 2026},
                     "fixture": {"id": 999, "date": "2099-01-01T00:00:00+00:00"}}
        monkeypatch.setattr(cd, "_telecharger_fixtures_oddspapi", lambda: [fixture_avec_cotes])
        monkeypatch.setattr(cd, "recuperer_fixtures_api_football", lambda: [fixture_af])
        monkeypatch.setattr(cd, "assez_tot_avant_coup_envoi", lambda *a, **k: True)
        monkeypatch.setattr(cd, "collecter_contexte_serper", lambda *a, **k: None)
        monkeypatch.setattr(cd, "recuperer_marches_pour_fixture",
                            lambda *a, **k: appels_oddspapi.append(1) or [])
        monkeypatch.setattr(cd, "recuperer_marches_pour_fixture_api_football",
                            lambda *a, **k: appels_api_football.append(1) or [])

        monkeypatch.setattr(cd, "FOURNISSEUR_COTES", "api_football")
        cd.collecter_donnees()

        assert appels_api_football == [1]
        assert appels_oddspapi == []
