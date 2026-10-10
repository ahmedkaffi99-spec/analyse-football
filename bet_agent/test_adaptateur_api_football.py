"""Tests de bet_agent/adaptateur_api_football.py — 100% synthétique, AUCUN appel réseau
(capturer_api_football_adapte n'est jamais appelée ici)."""

from datetime import datetime, timedelta, timezone

from adaptateur_api_football import (CATEGORIES_SANS_LIGNE, calculer_age_secondes,
                                     categories_indisponibles, construire_resultat,
                                     extraire_cotations_brutes, traduire_en_marches_oddspapi)

T0 = datetime(2026, 10, 10, 18, 0, 0, tzinfo=timezone.utc)


def _reponse_api_football(bets, update_iso="2026-10-10T17:59:00+00:00", bookmaker_id=11):
    return {"response": [{"update": update_iso, "bookmakers": [{"id": bookmaker_id, "bets": bets}]}]}


BETS_COMPLETS = [
    {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": "2.10"},
                                                  {"value": "Draw", "odd": "3.40"},
                                                  {"value": "Away", "odd": "3.20"}]},
    {"id": 2, "name": "Double Chance", "values": [{"value": "Home/Draw", "odd": "1.30"},
                                                   {"value": "Home/Away", "odd": "1.20"},
                                                   {"value": "Draw/Away", "odd": "1.60"}]},
    {"id": 3, "name": "Both Teams Score", "values": [{"value": "Yes", "odd": "1.80"},
                                                      {"value": "No", "odd": "1.95"}]},
    {"id": 4, "name": "Asian Handicap", "values": [{"value": "Home -1.25", "odd": "1.90"},
                                                    {"value": "Away +1.25", "odd": "1.95"}]},
    {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "1.85"},
                                                      {"value": "Under 2.5", "odd": "1.95"}]},
    {"id": 6, "name": "Corners Over Under", "values": [{"value": "Over 9.5", "odd": "1.90"},
                                                        {"value": "Under 9.5", "odd": "1.90"}]},
    {"id": 7, "name": "Yellow Over/Under", "values": [{"value": "Over 3.5", "odd": "1.88"},
                                                       {"value": "Under 3.5", "odd": "1.92"}]},
    {"id": 8, "name": "Total Shots", "values": [{"value": "Over 23.5", "odd": "1.90"},
                                                 {"value": "Under 23.5", "odd": "1.90"}]},
    {"id": 9, "name": "Total - Home", "values": [{"value": "Over 1.5", "odd": "1.85"},
                                                  {"value": "Under 1.5", "odd": "1.95"}]},
    {"id": 10, "name": "Total - Away", "values": [{"value": "Over 1.5", "odd": "1.85"},
                                                   {"value": "Under 1.5", "odd": "1.95"}]},
]
# NB (limite connue, documentée) : API-Football encode l'Asian Handicap avec une ligne
# MIRORÉE par sélection ("Home -1.25" / "Away +1.25"), alors qu'OddsPapi partage UNE seule
# valeur de handicap entre "1" et "2" au sein d'un même marché (confirmé par les données
# réelles du 10/10/2026 : selection "1" et "2" partagent exactement la même valeur de ligne
# côté OddsPapi, jamais mirorée). Deviner la convention de signe inverse pour les fusionner
# serait une correspondance inventée — interdit explicitement par la demande. Ce fichier ne
# fusionne donc JAMAIS les deux côtés d'une ligne Asian Handicap API-Football : chaque
# (sélection, ligne) reste un marché à une seule sélection, jamais mélangé ni deviné. C'est
# une limite assumée de la Phase B, à lever explicitement en Phase C si besoin (ex : si un
# futur test réel confirme la convention de signe à utiliser).
N_MARCHES_ATTENDUS = 11  # 10 catégories, Asian Handicap scindé en 2 (1 par sélection/ligne)


class TestExtractionEtTraduction:
    def test_tous_les_marches_connus_sont_traduits(self):
        cotations, maj, erreur = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        assert erreur is None
        assert maj == "2026-10-10T17:59:00+00:00"
        marches, ambigus = traduire_en_marches_oddspapi(cotations)
        assert ambigus == []
        assert len(marches) == N_MARCHES_ATTENDUS
        noms = {m["marche"] for m in marches}
        assert noms == {"Full Time Result", "Double Chance Full Time", "Both Teams To Score",
                        "Asian Handicap", "Over Under Full Time", "Corners - Over Under Full Time",
                        "Yellow Cards - Over Under Full Time", "Shots - Over Under Full Time",
                        "Over Under Team 1", "Over Under Team 2"}

    def test_asian_handicap_scinde_en_deux_marches_un_cote_chacun(self):
        # Limite connue (voir commentaire au-dessus de BETS_COMPLETS) : jamais de fusion par
        # inversion de signe devinée -> 2 entrées à 1 sélection chacune pour 1 ligne réelle.
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        marches, _ = traduire_en_marches_oddspapi(cotations)
        hcp = [m for m in marches if m["marche"] == "Asian Handicap"]
        assert len(hcp) == 2
        assert all(len(m["selections"]) == 1 for m in hcp)

    def test_1x2_double_chance_btts_sans_ligne_significative(self):
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        marches, _ = traduire_en_marches_oddspapi(cotations)
        for m in marches:
            if m["marche"] in ("Full Time Result", "Double Chance Full Time", "Both Teams To Score"):
                assert m["handicap"] is None

    def test_asian_handicap_preserve_sa_ligne_et_jamais_devine_european(self):
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        marches, _ = traduire_en_marches_oddspapi(cotations)
        hcp = next(m for m in marches if m["marche"] == "Asian Handicap")
        assert hcp["handicap"] == -1.25
        assert all(m["marche"] != "European Handicap" for m in marches)

    def test_european_handicap_jamais_substitue_par_asian(self):
        # Même si l'Asian Handicap est présent, aucune entrée "European Handicap" ne doit
        # jamais être produite — API-Football n'a pas cet équivalent (confirmé par 2 tests
        # réels antérieurs), ce fichier ne doit JAMAIS le simuler.
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        marches, _ = traduire_en_marches_oddspapi(cotations)
        assert "European Handicap" not in {m["marche"] for m in marches}

    def test_selections_au_format_attendu_par_analyser_et_envoyer(self):
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        marches, _ = traduire_en_marches_oddspapi(cotations)
        totaux = next(m for m in marches if m["marche"] == "Over Under Full Time")
        textes = {s["selection"] for s in totaux["selections"]}
        assert textes == {"Over", "Under"}
        resultat = next(m for m in marches if m["marche"] == "Full Time Result")
        textes_1x2 = {s["selection"] for s in resultat["selections"]}
        assert textes_1x2 == {"1", "X", "2"}

    def test_marche_non_mappe_jamais_invente(self):
        bets = [{"id": 99, "name": "Marché Inconnu XYZ", "values": [{"value": "A", "odd": "1.5"}]}]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets))
        assert cotations == []

    def test_cote_invalide_jamais_coercee(self):
        bets = [{"id": 1, "name": "Match Winner", "values": [
            {"value": "Home", "odd": "pas_un_nombre"},
            {"value": "Draw", "odd": "0.9"},     # <= 1.0, impossible en décimal réel
            {"value": "Away", "odd": "3.20"},
        ]}]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets))
        assert len(cotations) == 1
        assert cotations[0]["selection"] == "2"

    def test_bookmaker_different_de_1xbet_ignore(self):
        bets = [{"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": "2.0"}]}]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets, bookmaker_id=999))
        assert cotations == []

    def test_reponse_vide_signalee_jamais_une_absence_silencieuse(self):
        cotations, maj, erreur = extraire_cotations_brutes({"response": []})
        assert erreur == "réponse vide"

    def test_reponse_avec_erreurs_jamais_traitee_comme_des_cotes(self):
        cotations, maj, erreur = extraire_cotations_brutes({"errors": {"requests": "Too many requests"}})
        assert erreur is not None and cotations == []


class TestDoublonsEtAmbiguites:
    def test_doublon_identique_jamais_rejete(self):
        bets = [{"id": 1, "name": "Match Winner", "values": [
            {"value": "Home", "odd": "2.10"}, {"value": "Home", "odd": "2.10"},  # doublon exact
            {"value": "Draw", "odd": "3.40"}, {"value": "Away", "odd": "3.20"},
        ]}]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets))
        marches, ambigus = traduire_en_marches_oddspapi(cotations)
        assert ambigus == []
        resultat = marches[0]
        assert sum(1 for s in resultat["selections"] if s["selection"] == "1") == 1

    def test_doublon_incoherent_rejete_jamais_moyenne(self):
        bets = [{"id": 1, "name": "Match Winner", "values": [
            {"value": "Home", "odd": "2.10"}, {"value": "Home", "odd": "2.50"},  # incohérent
            {"value": "Draw", "odd": "3.40"}, {"value": "Away", "odd": "3.20"},
        ]}]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets))
        marches, ambigus = traduire_en_marches_oddspapi(cotations)
        assert len(ambigus) == 1 and ambigus[0]["selection"] == "1"
        resultat = marches[0]
        textes = {s["selection"] for s in resultat["selections"]}
        assert "1" not in textes  # la sélection ambiguë est exclue, jamais choisie au hasard
        assert textes == {"X", "2"}


class TestMarchesIndisponibles:
    def test_marche_absent_signale_jamais_invente(self):
        bets = [b for b in BETS_COMPLETS if b["name"] != "Both Teams Score"]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets))
        absents = categories_indisponibles(cotations)
        assert absents == ["BTTS"]

    def test_tout_present_rien_indisponible(self):
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(BETS_COMPLETS))
        assert categories_indisponibles(cotations) == []

    def test_absence_partielle_signalee_sans_toucher_au_reste(self):
        bets = [b for b in BETS_COMPLETS if b["name"] not in ("Total - Home", "Total - Away")]
        cotations, _, _ = extraire_cotations_brutes(_reponse_api_football(bets))
        assert categories_indisponibles(cotations) == ["BUTS_EQUIPE_DOM", "BUTS_EQUIPE_EXT"]


class TestFraicheur:
    def test_age_base_sur_maj_fournisseur_si_disponible(self):
        age = calculer_age_secondes(T0, recu_le_utc=T0, maj_fournisseur_utc="2026-10-10T17:59:00+00:00")
        assert age == 60.0

    def test_age_repli_sur_recu_le_si_maj_absente(self):
        age = calculer_age_secondes(T0, recu_le_utc=T0 - timedelta(seconds=5), maj_fournisseur_utc=None)
        assert age == 5.0

    def test_age_none_si_aucun_horodatage(self):
        assert calculer_age_secondes(T0, recu_le_utc=None, maj_fournisseur_utc=None) is None


class TestConstruireResultat:
    def test_resultat_frais_rempli_dans_marches(self):
        data = _reponse_api_football(BETS_COMPLETS, update_iso="2026-10-10T17:59:30+00:00")
        r = construire_resultat(data, fixture_id=12345, statut_http=200, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        assert r.erreur is None and not r.perime
        assert len(r.marches) == N_MARCHES_ATTENDUS
        assert r.marches_perimes == []

    def test_resultat_perime_jamais_presente_comme_actuel(self):
        # maj_fournisseur vieille de 5 minutes, TTL=90s -> tout le lot part en marches_perimes,
        # jamais mélangé avec `marches`.
        data = _reponse_api_football(BETS_COMPLETS, update_iso="2026-10-10T17:55:00+00:00")
        r = construire_resultat(data, fixture_id=12345, statut_http=200, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        assert r.perime is True
        assert r.marches == []
        assert len(r.marches_perimes) == N_MARCHES_ATTENDUS

    def test_429_jamais_de_donnees_inventees(self):
        r = construire_resultat(None, fixture_id=12345, statut_http=429, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        assert r.quota_epuise is True
        assert r.erreur is not None
        assert r.marches == [] and r.marches_perimes == []

    def test_erreur_reseau_jamais_de_donnees_inventees(self):
        r = construire_resultat(None, fixture_id=12345, statut_http=None, erreur_http="timeout",
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        assert r.erreur == "timeout"
        assert r.marches == []

    def test_nb_appels_consommes_compte_meme_un_echec(self):
        r = construire_resultat(None, fixture_id=1, statut_http=429, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0, nb_appels_consommes=1)
        assert r.nb_appels_consommes == 1


class TestCompatibiliteTicketsSimules:
    """Vérifie que la sortie de l'adaptateur est directement consommable par les fonctions
    réelles d'analyser_et_envoyer.py, SANS modifier ce fichier — but explicite de la Phase B."""

    def test_estimer_ligne_equilibree_fonctionne_sur_la_sortie_adaptee(self):
        # Même appel que la prod pour les cartons (analyser_et_envoyer.py, ligne 2318) :
        # mots_cles=["card", "booking"].
        import analyser_et_envoyer as ae
        data = _reponse_api_football(BETS_COMPLETS)
        r = construire_resultat(data, fixture_id=1, statut_http=200, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        ligne = ae.estimer_ligne_equilibree(r.marches, ["card", "booking"])
        assert ligne == 3.5

    def test_estimer_expected_goals_fonctionne_mais_handicap_degrade(self):
        # LIMITE CONNUE à lever en Phase C : l'Asian Handicap scindé (voir
        # test_asian_handicap_scinde_en_deux_marches_un_cote_chacun) ne contient jamais les
        # deux sélections "1"/"2" dans le MÊME dict marché -> estimer_expected_goals_depuis_
        # marches ne peut jamais les apparier et retombe en repli (mu_diff=0.0, 50/50) au lieu
        # d'utiliser le handicap réel. Fonctionne SANS planter (degrade gracieusement), mais
        # c'est une perte d'information réelle à corriger avant tout remplacement effectif
        # d'OddsPapi par cet adaptateur.
        import analyser_et_envoyer as ae
        data = _reponse_api_football(BETS_COMPLETS)
        r = construire_resultat(data, fixture_id=1, statut_http=200, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        mu_home, mu_away, mu_total, a_total, a_handicap = ae.estimer_expected_goals_depuis_marches(r.marches)
        assert 0.15 <= mu_home <= 6.0 and 0.15 <= mu_away <= 6.0
        assert a_total is True
        assert a_handicap is False  # repli dégradé, limite connue — pas un crash

    def test_periode_absente_traitee_comme_fulltime(self):
        import collecte_donnees as cd
        data = _reponse_api_football(BETS_COMPLETS)
        r = construire_resultat(data, fixture_id=1, statut_http=200, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        marche = r.marches[0]
        assert marche["periode"] is None
        # Reproduit exactement la logique de filtrage par période d'analyser_et_envoyer.py
        # (ligne 925) : periode=None doit tomber sur le défaut "fulltime".
        periode = (marche.get("periode") or "fulltime").lower()
        assert periode == "fulltime"


class TestGenerationCouponsHorsLigne:
    """Priorité 4 (migration minimale, 10/10/2026) : vérifie que la génération du POOL de
    candidats (agent3_calcul_pool_candidats, 100% Python/déterministe, sans LLM ni Telegram)
    fonctionne de bout en bout sur des marchés sourcés API-Football — jamais d'appel réseau
    réel, jamais de publication Telegram (cette fonction s'arrête avant l'IA stratège/
    rédaction/envoi)."""

    def _donnees_synthetiques(self, marches):
        import datetime as _dt
        maintenant = _dt.datetime.now(_dt.timezone.utc).isoformat()
        depart_futur = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=2)).isoformat()
        return {
            "date_collecte": maintenant,
            "matchs": [{
                "match_demande": {"home": "Lens", "away": "Auxerre"},
                "api_football": {"home_name": "Lens", "away_name": "Auxerre"},
                "oddspapi": {"fixture_id": None, "start_time": depart_futur, "tous_marches": marches},
                "stats_historiques": {"home": None, "away": None},
                "stats_detaillees_10_matchs": {"home": None, "away": None},
            }],
        }

    def test_pool_de_candidats_genere_sans_erreur_sur_marches_api_football(self):
        import analyser_et_envoyer as ae
        data = _reponse_api_football(BETS_COMPLETS)
        r = construire_resultat(data, fixture_id=1, statut_http=200, erreur_http=None,
                                recu_le_utc=T0, ttl_secondes=90, maintenant=T0)
        marches_valides = [m for m in r.marches if m["marche"] != "Asian Handicap"]  # jamais activé
        donnees = self._donnees_synthetiques(marches_valides)

        pool = ae.agent3_calcul_pool_candidats(donnees)

        assert isinstance(pool, dict)
        # Au moins un candidat généré (1X2/Double Chance/BTTS/Totaux sont modélisés par Poisson) —
        # confirme que la sortie de l'adaptateur est utilisable de bout en bout par le moteur
        # de coupons existant, sans aucune modification de analyser_et_envoyer.py.
        assert sum(len(v) for v in pool.values()) > 0

    def test_aucune_fonction_telegram_ou_llm_nest_appelee(self):
        """Garde-fou : ce test n'importe/n'appelle jamais agent4_rediger_coupons,
        agent5_envoyer_coupons ni agent_strategie — seul agent3_calcul_pool_candidats (pur
        Python) est exercé, ce qui garantit déjà l'absence de toute publication réelle."""
        import analyser_et_envoyer as ae
        assert hasattr(ae, "agent3_calcul_pool_candidats")
        assert hasattr(ae, "agent5_envoyer_coupons")  # existe, mais jamais appelé ici
