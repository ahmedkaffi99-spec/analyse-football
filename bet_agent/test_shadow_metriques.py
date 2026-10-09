"""Tests de shadow_metriques.py — données 100% synthétiques (aucun appel réseau), vérifient
la logique d'appariement strict et les calculs de couverture/écarts/quota."""

from datetime import datetime, timedelta, timezone

from shadow_capture import Cotation, RequeteShadow
from shadow_metriques import (associer_matchs, consommation_quota, couverture_matchs,
                              mesurer_ecarts, rapport_complet, repartition_par_seuil)

T0 = datetime(2026, 10, 10, 18, 0, 0, tzinfo=timezone.utc)


def _cotation(fournisseur, fid_op=None, fid_af=None, marche="1X2", selection="1", ligne=None,
             cote=2.0, recu_le=T0, championnat="Premier League"):
    return Cotation(fixture_id_oddspapi=fid_op, fixture_id_api_football=fid_af,
                    championnat=championnat, domicile="H", exterieur="A", bookmaker="1xBet",
                    fournisseur=fournisseur, recu_le_utc=recu_le, maj_api_utc=None,
                    marche=marche, marche_brut=marche, selection=selection, ligne=ligne, cote=cote)


class TestAssociationStricte:
    def test_paire_identique_appariee(self):
        op = _cotation("oddspapi", fid_op="fx1", cote=2.0)
        af = _cotation("api_football", fid_af=100, cote=2.1)
        paires, non_op, non_af = associer_matchs([op], [af], {"fx1": 100})
        assert len(paires) == 1 and not non_op and not non_af

    def test_ligne_differente_jamais_appariee(self):
        op = _cotation("oddspapi", fid_op="fx1", marche="BUTS_TOTAL", selection="Over", ligne=2.5)
        af = _cotation("api_football", fid_af=100, marche="BUTS_TOTAL", selection="Over", ligne=3.5)
        paires, non_op, non_af = associer_matchs([op], [af], {"fx1": 100})
        assert paires == [] and len(non_op) == 1 and len(non_af) == 1

    def test_selection_differente_jamais_appariee(self):
        op = _cotation("oddspapi", fid_op="fx1", selection="1")
        af = _cotation("api_football", fid_af=100, selection="2")
        paires, non_op, non_af = associer_matchs([op], [af], {"fx1": 100})
        assert paires == []

    def test_fixture_sans_correspondance_fournie_jamais_appariee(self):
        op = _cotation("oddspapi", fid_op="fx1")
        af = _cotation("api_football", fid_af=100)
        paires, non_op, non_af = associer_matchs([op], [af], {})  # pas de correspondance fournie
        assert paires == [] and len(non_op) == 1


class TestMesureEcarts:
    def test_ecart_absolu_et_relatif(self):
        op = _cotation("oddspapi", fid_op="fx1", cote=2.0, recu_le=T0)
        af = _cotation("api_football", fid_af=100, cote=2.2, recu_le=T0 + timedelta(seconds=30))
        paires, _, _ = associer_matchs([op], [af], {"fx1": 100})
        mesures = mesurer_ecarts(paires)
        assert mesures[0]["ecart_absolu"] == 0.2
        assert mesures[0]["ecart_relatif"] == 0.1
        assert mesures[0]["delai_secondes"] == 30.0

    def test_repartition_par_seuil(self):
        mesures = [{"ecart_relatif": 0.005}, {"ecart_relatif": 0.02}, {"ecart_relatif": 0.04},
                  {"ecart_relatif": 0.10}]
        rep = repartition_par_seuil(mesures)
        assert rep[">1%"] == 3  # 0.02, 0.04, 0.10
        assert rep[">3%"] == 2  # 0.04, 0.10
        assert rep[">5%"] == 1  # 0.10


class TestCouvertureEtQuota:
    def test_couverture_matchs(self):
        req_op = [RequeteShadow("oddspapi", "fx1", 200, None, 50, T0),
                 RequeteShadow("oddspapi", "fx2", None, "timeout", 0, T0)]
        req_af = [RequeteShadow("api_football", "fx1", 200, None, 10, T0)]
        couv = couverture_matchs(["fx1", "fx2"], req_op, req_af)
        assert couv["total_matchs_vises"] == 2
        assert couv["oddspapi_couverts"] == 1
        assert couv["api_football_couverts"] == 1
        assert couv["couverts_par_les_deux"] == 1

    def test_consommation_quota_compte_les_echecs_aussi(self):
        req_op = [RequeteShadow("oddspapi", "fx1", 200, None, 50, T0),
                 RequeteShadow("oddspapi", "fx2", 429, "quota épuisé", 0, T0)]
        req_af = [RequeteShadow("api_football", "fx1", 200, None, 10, T0)]
        q = consommation_quota(req_op, req_af)
        assert q["oddspapi_appels"] == 2  # l'échec compte aussi : c'est un vrai appel dépensé
        assert q["api_football_appels"] == 1


class TestRapportComplet:
    def test_rapport_assemble_toutes_les_sections(self):
        op = _cotation("oddspapi", fid_op="fx1", cote=2.0, recu_le=T0)
        af = _cotation("api_football", fid_af=100, cote=2.1, recu_le=T0 + timedelta(seconds=10))
        paires, _, _ = associer_matchs([op], [af], {"fx1": 100})
        mesures = mesurer_ecarts(paires)
        req_op = [RequeteShadow("oddspapi", "fx1", 200, None, 1, T0)]
        req_af = [RequeteShadow("api_football", 100, 200, None, 1, T0)]
        rapport = rapport_complet(mesures, req_op, req_af, ["fx1"])
        assert rapport["n_paires_comparees"] == 1
        assert set(rapport) == {"couverture", "quota", "marches_par_match_oddspapi",
                                "marches_par_match_api_football", "ecarts_par_seuil",
                                "par_championnat", "par_marche", "n_paires_comparees"}
