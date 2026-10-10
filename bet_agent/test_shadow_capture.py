"""Tests de normalisation shadow_capture.py — aucun appel réseau (les fonctions capturer_*
ne sont jamais appelées ici, seulement la normalisation pure)."""

from shadow_capture import (CATEGORIES_ODDSPAPI, CATEGORIES_SANS_LIGNE, MAPPING_API_FOOTBALL,
                            _normaliser_ligne_oddspapi, _normaliser_selection_api_football)


class TestNormalisationApiFootballStricte:
    def test_1x2_reconnu(self):
        assert _normaliser_selection_api_football("1X2", "Home") == ("1", None)
        assert _normaliser_selection_api_football("1X2", "Draw") == ("X", None)
        assert _normaliser_selection_api_football("1X2", "Away") == ("2", None)

    def test_1x2_valeur_inconnue_jamais_devinee(self):
        assert _normaliser_selection_api_football("1X2", "Quelquechose") == (None, None)

    def test_double_chance(self):
        assert _normaliser_selection_api_football("DOUBLE_CHANCE", "Home/Draw") == ("1X", None)
        assert _normaliser_selection_api_football("DOUBLE_CHANCE", "Home/Away") == ("12", None)
        assert _normaliser_selection_api_football("DOUBLE_CHANCE", "Draw/Away") == ("2X", None)

    def test_handicap_asiatique_extrait_la_ligne(self):
        assert _normaliser_selection_api_football("HANDICAP_ASIATIQUE", "Home -1.25") == ("1", -1.25)
        assert _normaliser_selection_api_football("HANDICAP_ASIATIQUE", "Away +0.25") == ("2", 0.25)

    def test_handicap_asiatique_format_invalide_jamais_devine(self):
        assert _normaliser_selection_api_football("HANDICAP_ASIATIQUE", "Home") == (None, None)

    def test_buts_total_extrait_over_under_et_ligne(self):
        assert _normaliser_selection_api_football("BUTS_TOTAL", "Over 2.5") == ("Over", 2.5)
        assert _normaliser_selection_api_football("BUTS_TOTAL", "Under 2.5") == ("Under", 2.5)

    def test_buts_equipe_meme_logique_que_buts_total(self):
        assert _normaliser_selection_api_football("BUTS_EQUIPE_DOM", "Over 1.5") == ("Over", 1.5)
        assert _normaliser_selection_api_football("CORNERS_TOTAL", "Under 9.5") == ("Under", 9.5)

    def test_cartons_et_tirs_meme_logique_que_buts_total(self):
        assert _normaliser_selection_api_football("CARTONS_TOTAL", "Over 4.5") == ("Over", 4.5)
        assert _normaliser_selection_api_football("TIRS_TOTAL", "Under 22.5") == ("Under", 22.5)

    def test_btts(self):
        assert _normaliser_selection_api_football("BTTS", "Yes") == ("Yes", None)
        assert _normaliser_selection_api_football("BTTS", "No") == ("No", None)

    def test_categorie_non_mappee_jamais_devinee(self):
        assert _normaliser_selection_api_football("HT/FT Double", "Home/Home") == (None, None)


class TestNormalisationLigneOddspapi:
    """Bug réel découvert le 10/10/2026 (test à 4 matchs) : OddsPapi renvoie handicap=0.0 pour
    1X2/Double Chance/BTTS (une valeur de remplissage, SANS signification de ligne), alors
    qu'API-Football ne porte structurellement aucune ligne pour ces mêmes paris (None) — 387
    paires comparées, mais 0 sur ces 3 catégories, uniquement parce que 0.0 != None."""

    def test_1x2_double_chance_btts_toujours_normalisees_a_none(self):
        assert _normaliser_ligne_oddspapi("1X2", 0.0) is None
        assert _normaliser_ligne_oddspapi("DOUBLE_CHANCE", 0.0) is None
        assert _normaliser_ligne_oddspapi("BTTS", 0.0) is None

    def test_une_ligne_de_handicap_reelle_nest_jamais_effacee(self):
        # Exigence explicite : ne jamais supprimer une ligne significative d'un handicap ou
        # d'un total, même quand sa valeur est 0.0 (ex: Asian Handicap pick'em).
        assert _normaliser_ligne_oddspapi("HANDICAP_ASIATIQUE", 0.0) == 0.0
        assert _normaliser_ligne_oddspapi("HANDICAP_EUROPEEN", 0.0) == 0.0
        assert _normaliser_ligne_oddspapi("BUTS_TOTAL", 0.0) == 0.0
        assert _normaliser_ligne_oddspapi("CORNERS_TOTAL", 2.5) == 2.5

    def test_categories_sans_ligne_couvre_exactement_les_3_cas_reels(self):
        assert CATEGORIES_SANS_LIGNE == {"1X2", "DOUBLE_CHANCE", "BTTS"}


class TestMappingExplicite:
    def test_european_handicap_absent_du_mapping_jamais_invente(self):
        # Confirmé par le test réel du 09/10/2026 : API-Football n'expose pas de handicap à
        # 3 voies pour 1xBet — volontairement absent de MAPPING_API_FOOTBALL (pas un oubli).
        # L'Asian Handicap n'est jamais considéré comme équivalent (demande explicite).
        assert "European Handicap" not in MAPPING_API_FOOTBALL
        assert MAPPING_API_FOOTBALL["Asian Handicap"] != "HANDICAP_EUROPEEN"

    def test_tous_les_marches_mappes_couvrent_les_10_categories_testees(self):
        attendues = {"1X2", "DOUBLE_CHANCE", "HANDICAP_ASIATIQUE", "BUTS_TOTAL",
                    "BUTS_EQUIPE_DOM", "BUTS_EQUIPE_EXT", "BTTS", "CORNERS_TOTAL",
                    "CARTONS_TOTAL", "TIRS_TOTAL"}
        assert set(MAPPING_API_FOOTBALL.values()) == attendues

    def test_handicap_europeen_present_cote_oddspapi_seulement(self):
        assert CATEGORIES_ODDSPAPI["European Handicap"] == "HANDICAP_EUROPEEN"
        assert "HANDICAP_EUROPEEN" not in MAPPING_API_FOOTBALL.values()
