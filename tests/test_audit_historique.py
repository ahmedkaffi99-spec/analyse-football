"""Tests de scripts/audit_historique/audit_couverture.py — uniquement les fonctions PURES
(detecter_doublons, champs_manquants), sans connexion à une base réelle (ni Supabase, ni
SQLite) : ces tests valident la LOGIQUE de détection sur des lignes synthétiques construites
pour l'occasion, jamais présentées comme des données de matchs réelles. Les fonctions qui
interrogent réellement la base (matrice_couverture, verifier_doublons_hist_matchs) ne sont pas
testées ici : elles n'ont de sens que contre la vraie Supabase (lecture seule), voir
docs/audit_bases_donnees.md pour les résultats réels obtenus en l'interrogeant directement."""

import importlib.util
import sys
from pathlib import Path

CHEMIN_MODULE = Path(__file__).resolve().parents[1] / "scripts" / "audit_historique" / "audit_couverture.py"
spec = importlib.util.spec_from_file_location("audit_couverture", CHEMIN_MODULE)
audit_couverture = importlib.util.module_from_spec(spec)
sys.modules["audit_couverture"] = audit_couverture
spec.loader.exec_module(audit_couverture)

detecter_doublons = audit_couverture.detecter_doublons
champs_manquants = audit_couverture.champs_manquants


class TestDetecterDoublons:
    def test_aucun_doublon_sur_des_lignes_toutes_distinctes(self):
        lignes = [
            {"home_id": 1, "away_id": 2, "date": "2024-01-01"},
            {"home_id": 3, "away_id": 4, "date": "2024-01-01"},
        ]
        assert detecter_doublons(lignes, ("home_id", "away_id", "date")) == []

    def test_detecte_un_doublon_exact(self):
        lignes = [
            {"home_id": 1, "away_id": 2, "date": "2024-01-01", "match_id": 100},
            {"home_id": 1, "away_id": 2, "date": "2024-01-01", "match_id": 101},
        ]
        doublons = detecter_doublons(lignes, ("home_id", "away_id", "date"))
        assert len(doublons) == 1
        cle, groupe = doublons[0]
        assert cle == (1, 2, "2024-01-01")
        assert len(groupe) == 2

    def test_cle_partiellement_differente_nest_pas_un_doublon(self):
        lignes = [
            {"home_id": 1, "away_id": 2, "date": "2024-01-01"},
            {"home_id": 1, "away_id": 2, "date": "2024-01-02"},  # date différente -> pas un doublon
        ]
        assert detecter_doublons(lignes, ("home_id", "away_id", "date")) == []

    def test_liste_vide_ne_plante_pas(self):
        assert detecter_doublons([], ("home_id",)) == []

    def test_valeur_manquante_dans_la_cle_nest_pas_ignoree(self):
        # Deux lignes sans "away_id" du tout partagent (home_id, None) -> comptées comme un
        # doublon potentiel (None traité comme une valeur de clé comme une autre, jamais
        # silencieusement écarté) : mieux vaut signaler un faux positif à vérifier manuellement
        # qu'escamoter un vrai doublon sur une donnée incomplète.
        lignes = [{"home_id": 1}, {"home_id": 1}]
        doublons = detecter_doublons(lignes, ("home_id", "away_id"))
        assert len(doublons) == 1


class TestChampsManquants:
    def test_compte_les_none_et_les_champs_absents(self):
        lignes = [{"xg": None}, {"xg": 1.2}, {}]
        assert champs_manquants(lignes, "xg") == 2

    def test_aucun_champ_manquant(self):
        lignes = [{"xg": 1.0}, {"xg": 2.0}]
        assert champs_manquants(lignes, "xg") == 0

    def test_liste_vide(self):
        assert champs_manquants([], "xg") == 0
