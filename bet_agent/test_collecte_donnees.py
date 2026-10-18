"""Audit du 09/10/2026 (demande explicite) : OddsPapi (quota 250/jour) et API-Football sont-ils
indépendants, et une panne OddsPapi (429) peut-elle bloquer/ralentir/gonfler la consommation
API-Football ? Tests hors-ligne (aucun appel réseau réel) : python -m pytest test_collecte_donnees.py"""

from types import SimpleNamespace
from unittest import mock

import pytest

import collecte_donnees as cd
import moteur.features as mf


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

        # Ce test exerce spécifiquement le chemin "oddspapi" (sélection ET cotes toujours
        # dépendantes d'OddsPapi) — devenu optionnel depuis que "api_football" est le défaut
        # (13/10/2026) : fixé explicitement, sinon ce test tournerait dans le nouveau mode où
        # recuperer_fixtures_api_football() est normalement appelé pour la découverte.
        monkeypatch.setattr(cd, "FOURNISSEUR_COTES", "oddspapi")
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

    def test_defaut_est_api_football_depuis_le_13_10_2026(self):
        # Avant le 13/10/2026 le défaut était "oddspapi" ; demande explicite ("n'utilise pas
        # oddspapi et utilise tout api football") : "api_football" est désormais le défaut,
        # "oddspapi" reste disponible via la variable d'environnement explicite.
        assert cd.FOURNISSEUR_COTES == "api_football"

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

    def test_bascule_appelle_la_bonne_fonction_selon_le_flag(self, monkeypatch, tmp_path):
        """Vérifie le point d'intégration dans collecter_donnees() lui-même : le flag décide
        strictement laquelle des deux fonctions est appelée, jamais les deux. Depuis le
        13/10/2026 (demande explicite : "n'utilise pas oddspapi et utilise tout api football"),
        FOURNISSEUR_COTES=api_football désactive aussi OddsPapi pour la DÉCOUVERTE des matchs
        du jour (plus seulement pour les cotes) — _telecharger_fixtures_oddspapi() ne doit
        JAMAIS être appelée dans ce mode, même pas pour construire la liste candidate."""
        appels_oddspapi, appels_api_football, appels_fixtures_oddspapi = [], [], []
        # Ligue 1 (league_id=61, un des 5 grands championnats de LIGUES_FILTRE_API_FOOTBALL) —
        # découvert UNIQUEMENT via recuperer_fixtures_api_football ici, jamais via OddsPapi.
        fixture_af = {"teams": {"home": {"name": "Lens"}, "away": {"name": "Auxerre"}},
                     "league": {"id": 61, "name": "Ligue 1", "season": 2026},
                     "fixture": {"id": 999, "date": "2099-01-01T00:00:00+00:00",
                                 "status": {"short": "NS"}}}
        # Isole la sortie JSON réelle de collecter_donnees() dans tmp_path — sans ça, ce test
        # écrit un vrai bet_agent/donnees_collectees.json (constaté le 10/10/2026 : atterrit
        # même à la racine du dépôt selon le cwd de pytest, détecté par le stop-hook git).
        monkeypatch.setattr(cd, "SORTIE_JSON", str(tmp_path / "donnees_collectees.json"))
        monkeypatch.setattr(cd, "MATCHS_MANUELS_ENV", "", raising=False)
        monkeypatch.setattr(cd, "SELECTION_MANUELLE_ACTIVE", False, raising=False)
        monkeypatch.setattr(cd, "MATCHS_MANUELS_DATES", set(), raising=False)
        monkeypatch.setattr(cd, "COMPLEMENT_AUTOMATIQUE_ACTIF", False, raising=False)
        monkeypatch.setattr(cd, "FILTRE_LIGUES_UNIQUES", None, raising=False)
        monkeypatch.setattr(cd, "_telecharger_fixtures_oddspapi",
                            lambda: appels_fixtures_oddspapi.append(1) or [])
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
        assert appels_fixtures_oddspapi == []  # OddsPapi jamais appelé, même pour la découverte


def _fixture_af(home, away, league_id, statut="NS", depart="2099-01-01T15:00:00+00:00"):
    return {"teams": {"home": {"name": home}, "away": {"name": away}},
            "league": {"id": league_id, "name": "x"},
            "fixture": {"id": f"{home}-{away}", "date": depart, "status": {"short": statut}}}


class TestSelectionMatchsDuJourApiFootball:
    """Tests dédiés du 13/10/2026 (demande explicite : "n'utilise pas oddspapi et utilise
    tout api football") : selectionner_matchs_du_jour_api_football ne doit JAMAIS dépendre
    d'OddsPapi — uniquement des fixtures API-Football, filtrées sur les 5 grands championnats
    (LIGUES_FILTRE_API_FOOTBALL), le statut "NS" et le délai avant coup d'envoi."""

    def test_filtre_sur_les_5_grands_championnats(self):
        fixtures = [
            _fixture_af("Arsenal", "Chelsea", 39),    # Premier League — retenu
            _fixture_af("Obscur FC", "Autre FC", 999),  # ligue hors filtre — exclu
        ]
        matchs = cd.selectionner_matchs_du_jour_api_football(fixtures)
        assert matchs == [("Arsenal", "Chelsea")]

    def test_ligue_des_champions_et_europa_league_incluses(self):
        # Demande explicite du 13/10/2026 : les 5 domestiques font tous relâche pendant les
        # semaines de coupe d'Europe (0 match trouvé le 13/10/2026 en pratique) — C1/C3
        # doivent compter comme sources automatiques, pas seulement les 5 domestiques.
        fixtures = [
            _fixture_af("Galatasaray", "Barcelona", 2),      # UEFA Champions League — retenu
            _fixture_af("Real Betis", "FC Porto", 3),        # UEFA Europa League — retenu
            _fixture_af("Obscur FC", "Autre FC", 848),       # Conference League — PAS demandée, exclue
        ]
        matchs = cd.selectionner_matchs_du_jour_api_football(fixtures)
        assert sorted(matchs) == sorted([("Galatasaray", "Barcelona"), ("Real Betis", "FC Porto")])

    def test_match_deja_commence_ou_termine_exclu(self):
        fixtures = [_fixture_af("Arsenal", "Chelsea", 39, statut="1H"),
                    _fixture_af("Lyon", "Monaco", 61, statut="FT")]
        assert cd.selectionner_matchs_du_jour_api_football(fixtures) == []

    def test_delai_avant_coup_envoi_respecte(self, monkeypatch):
        appels = []
        monkeypatch.setattr(cd, "assez_tot_avant_coup_envoi",
                            lambda depart, *a, **k: appels.append(depart) or False)
        fixtures = [_fixture_af("Arsenal", "Chelsea", 39)]
        assert cd.selectionner_matchs_du_jour_api_football(fixtures) == []
        assert appels == ["2099-01-01T15:00:00+00:00"]

    def test_dedoublonnage_par_paire_equipes(self):
        fixtures = [_fixture_af("Arsenal", "Chelsea", 39), _fixture_af("Arsenal", "Chelsea", 39)]
        assert cd.selectionner_matchs_du_jour_api_football(fixtures) == [("Arsenal", "Chelsea")]

    def test_equipe_feminine_exclue(self, monkeypatch):
        monkeypatch.setattr(cd, "est_equipe_feminine_api_football",
                            lambda nom: nom == "Arsenal W")
        fixtures = [_fixture_af("Arsenal W", "Chelsea W", 39)]
        assert cd.selectionner_matchs_du_jour_api_football(fixtures) == []

    def test_equipe_reserve_exclue(self, monkeypatch):
        monkeypatch.setattr(cd, "contient_indicateur_reserve", lambda nom: "B" in nom)
        fixtures = [_fixture_af("Arsenal B", "Chelsea", 39)]
        assert cd.selectionner_matchs_du_jour_api_football(fixtures) == []

    def test_aucune_dependance_a_oddspapi(self, monkeypatch):
        # Garantie structurelle : cette fonction ne lit jamais fixtures_oddspapi ni aucune
        # fonction OddsPapi — vérifié en s'assurant qu'aucun attribut OddsPapi du module n'est
        # lu pendant l'appel (espion sur _telecharger_fixtures_oddspapi, jamais invoqué ici).
        appels = []
        monkeypatch.setattr(cd, "_telecharger_fixtures_oddspapi", lambda: appels.append(1) or [])
        cd.selectionner_matchs_du_jour_api_football([_fixture_af("Arsenal", "Chelsea", 39)])
        assert appels == []


class TestRecupererElo:
    """18/10/2026, demande explicite ("propose une correction : intégrer l'Elo au calcul de
    bet_agent, avec un poids mesuré par backtest comme pour H2H") : recuperer_elo réutilise
    moteur.features.Historique.elo (walk-forward, jamais de fuite) depuis hist_matchs — jamais
    un run bloqué par cette étape (DB indisponible, ligue hors historique 5 saisons, etc.),
    même principe que le reste des sources API-Football de ce module."""

    def setup_method(self):
        cd._cache_historique_elo.clear()

    def test_ligue_hors_historique_5_saisons_renvoie_none(self):
        # Ligue des Champions (2) : hist_matchs n'a que les 5 championnats domestiques.
        assert cd.recuperer_elo(541, 536, 2, "2026-10-18T19:00:00+00:00") is None

    def test_date_absente_renvoie_none(self):
        assert cd.recuperer_elo(541, 536, 140, None) is None

    def test_historique_deja_en_cache_est_reutilise_sans_recharger_la_base(self):
        appels_elo = []

        def elo_bidon(match_fictif):
            appels_elo.append(match_fictif)
            return 1773.4, 1510.0

        cd._cache_historique_elo[140] = SimpleNamespace(elo=elo_bidon)
        resultat = cd.recuperer_elo(541, 536, 140, "2026-10-18T19:00:00+00:00")
        assert resultat == {"elo_home": 1773.4, "elo_away": 1510.0}
        assert len(appels_elo) == 1
        assert appels_elo[0]["home_id"] == 541 and appels_elo[0]["away_id"] == 536

    def test_erreur_pendant_le_calcul_renvoie_none_jamais_une_exception(self):
        def elo_qui_plante(match_fictif):
            raise RuntimeError("base indisponible")

        cd._cache_historique_elo[140] = SimpleNamespace(elo=elo_qui_plante)
        assert cd.recuperer_elo(541, 536, 140, "2026-10-18T19:00:00+00:00") is None


class TestRecupererArbitreCartonsMoyenne:
    """18/10/2026, demande explicite ("lance les deux", audit Agent 7) : moteur/modeles/
    registre.py applique déjà un effet arbitre validé mathématiquement mais bet_agent ne
    l'utilisait pas du tout — même angle mort que l'Elo avant intégration. Réutilise
    moteur.features.construire_features (jamais une formule réimplémentée ici) et le même
    cache par ligue que recuperer_elo — jamais un run bloqué par cette étape."""

    def setup_method(self):
        cd._cache_historique_elo.clear()

    def test_ligue_hors_historique_5_saisons_renvoie_none(self):
        assert cd.recuperer_arbitre_cartons_moyenne("A. Taylor", 2, "2026-10-18T19:00:00+00:00") is None

    def test_date_absente_renvoie_none(self):
        assert cd.recuperer_arbitre_cartons_moyenne("A. Taylor", 140, None) is None

    def test_arbitre_absent_renvoie_none(self):
        assert cd.recuperer_arbitre_cartons_moyenne(None, 140, "2026-10-18T19:00:00+00:00") is None
        assert cd.recuperer_arbitre_cartons_moyenne("", 140, "2026-10-18T19:00:00+00:00") is None

    def test_historique_suffisant_renvoie_les_trois_champs(self, monkeypatch):
        cd._cache_historique_elo[140] = SimpleNamespace(elo=lambda m: (1500.0, 1500.0))
        monkeypatch.setattr(mf, "construire_features", lambda match, hist: {
            "arbitre_n": 8, "arbitre_cartons_moy": 5.2, "ligue": {"yellow_cards_par_equipe": 2.1},
        })
        resultat = cd.recuperer_arbitre_cartons_moyenne("A. Taylor", 140, "2026-10-18T19:00:00+00:00")
        assert resultat == {"arbitre_n": 8, "arbitre_cartons_moy": 5.2, "moy_ligue_cartons_par_equipe": 2.1}

    def test_historique_arbitre_insuffisant_renvoie_none(self, monkeypatch):
        cd._cache_historique_elo[140] = SimpleNamespace(elo=lambda m: (1500.0, 1500.0))
        monkeypatch.setattr(mf, "construire_features", lambda match, hist: {
            "arbitre_n": 2, "arbitre_cartons_moy": 5.2, "ligue": {"yellow_cards_par_equipe": 2.1},
        })
        assert cd.recuperer_arbitre_cartons_moyenne("A. Taylor", 140, "2026-10-18T19:00:00+00:00") is None

    def test_erreur_pendant_le_calcul_renvoie_none_jamais_une_exception(self, monkeypatch):
        cd._cache_historique_elo[140] = SimpleNamespace(elo=lambda m: (1500.0, 1500.0))

        def plante(match, hist):
            raise RuntimeError("base indisponible")

        monkeypatch.setattr(mf, "construire_features", plante)
        assert cd.recuperer_arbitre_cartons_moyenne("A. Taylor", 140, "2026-10-18T19:00:00+00:00") is None
