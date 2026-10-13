"""Tests dédiés à la fonctionnalité du 11/10/2026 : "génération dynamique de coupons
quotidiens sans doublons". Couvre les scénarios obligatoires de la mission :
jour chargé, jour creux, zéro match éligible, match dupliqué (plusieurs sources), plusieurs
marchés disponibles pour un même match, absence totale de recouvrement entre coupons,
fuseau horaire/changement de jour/matchs proches de minuit, et rejeu du workflow sans
doublon ni accumulation entre deux runs indépendants.

python -m unittest test_generation_dynamique_coupons
"""
import unittest
from unittest import mock

import analyser_et_envoyer as ae
import collecte_donnees as cd


def _selection(match, categorie, selection, cote, edge=8.0, proba=70.0):
    return {"match": match, "home_nom": match.split(" vs ")[0], "away_nom": match.split(" vs ")[1],
            "fixture_id_oddspapi": match,
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "handicap": 2.5, "selection": selection,
                     "cote": cote, "proba_modele_pct": proba, "edge_pct": edge, "guide": None, "onglet": "onglet"}}


def _fixture(p1, p2, tournoi="Premier League", pays="England", depart="2099-01-01T15:00:00Z", fid=None):
    return {"participant1Name": p1, "participant2Name": p2, "tournamentName": tournoi, "categoryName": pays,
            "hasOdds": True, "statusName": "Pre-Game", "startTime": depart,
            "fixtureId": fid or f"{p1}-{p2}"}


def _toutes_les_selections_des_coupons(resultats):
    return [s for item in resultats for s in item["selections"]]


class TestVolumeDynamiqueMatchs(unittest.TestCase):
    """Règles 3/4/7 de la mission : le nombre et la taille des coupons s'adaptent au nombre
    RÉEL de matchs éligibles ce jour-là — jamais un chiffre fixé à l'avance (ni 24, ni aucun
    autre), et jamais de match inventé pour compléter un quota."""

    def test_jour_charge_cinq_coupons_dynamiques(self):
        # 25 matchs éligibles (>= au palier de 20 de PALIERS_NB_COUPONS_DYNAMIQUE) → 5 coupons.
        pool = {f"M{i} vs A{i}": [_selection(f"M{i} vs A{i}", "Total", "Over", 1.12)] for i in range(25)}
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", False):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(len(resultats), 5)
        toutes_selections = _toutes_les_selections_des_coupons(resultats)
        matchs_utilises = [s["match"] for s in toutes_selections]
        self.assertEqual(len(matchs_utilises), len(set(matchs_utilises)))  # aucun doublon
        self.assertLessEqual(len(matchs_utilises), 25)  # jamais plus de matchs que le pool réel

    def test_jour_creux_un_seul_coupon(self):
        # 4 matchs éligibles seulement (sous le 1er palier à 6) → un seul coupon, pas 24.
        pool = {f"M{i} vs A{i}": [_selection(f"M{i} vs A{i}", "Total", "Over", 1.3)] for i in range(4)}
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", False):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(len(resultats), 1)
        toutes_selections = _toutes_les_selections_des_coupons(resultats)
        self.assertLessEqual(len(toutes_selections), 4)

    def test_zero_match_eligible_aucun_coupon_jamais_invente(self):
        # Règle 7 explicite : "ne jamais inventer de matchs" — zéro match éligible doit
        # produire zéro coupon, jamais une erreur ni un coupon vide fabriqué.
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value={}), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", False):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(resultats, [])


class TestUniciteCroiseeMatchsEtMarches(unittest.TestCase):
    """Règles 5/6/8 de la mission : un même match ne doit jamais apparaître dans plusieurs
    coupons, même via un marché différent ; un contrôle final bloque toute publication en cas
    de doublon détecté."""

    def test_aucun_recouvrement_entre_coupons_sur_un_run_complet(self):
        pool = {f"M{i} vs A{i}": [_selection(f"M{i} vs A{i}", "Total", "Over", 1.15)] for i in range(12)}
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", False):
            resultats = ae.generer_coupons({"matchs": []})
        vus = set()
        for item in resultats:
            for s in item["selections"]:
                self.assertNotIn(s["match"], vus, "un match réapparaît dans un autre coupon")
                vus.add(s["match"])

    def test_un_seul_marche_choisi_par_match_meme_si_plusieurs_disponibles(self):
        # "A vs B" propose DEUX marchés (Total ET BTTS) : une fois qu'un coupon a pris l'un
        # des deux, l'AUTRE marché du même match ne doit plus être disponible pour un coupon
        # suivant — le match entier sort du pool disponible, pas seulement le marché choisi.
        pool = {
            "A vs B": [_selection("A vs B", "Total", "Over", 1.3), _selection("A vs B", "BTTS", "Yes", 1.3)],
            "C vs D": [_selection("C vs D", "Total", "Over", 1.3)],
            "E vs F": [_selection("E vs F", "Total", "Over", 1.3)],
        }
        profils = [
            {"cle": "p1", "nom": "🛡️ COUPON 1", "cote_min": 1.1, "cote_max": 2.1, "nb_jambes_min": 1, "nb_jambes": 1},
            {"cle": "p2", "nom": "⚖️ COUPON 2", "cote_min": 1.1, "cote_max": 2.1, "nb_jambes_min": 1, "nb_jambes": 1},
            {"cle": "p3", "nom": "🔥 COUPON 3", "cote_min": 1.1, "cote_max": 2.1, "nb_jambes_min": 1, "nb_jambes": 1},
        ]
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "construire_profils_dynamiques", return_value=profils), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", False):
            resultats = ae.generer_coupons({"matchs": []})
        toutes_selections = _toutes_les_selections_des_coupons(resultats)
        matchs_utilises = [s["match"] for s in toutes_selections]
        # 3 matchs distincts au total (peu importe que "A vs B" en ait 2 marchés) → au plus
        # 3 jambes au total, "A vs B" présent au plus une fois.
        self.assertLessEqual(matchs_utilises.count("A vs B"), 1)
        self.assertEqual(len(matchs_utilises), len(set(matchs_utilises)))
        self.assertLessEqual(len(matchs_utilises), 3)

    def test_garde_fou_final_bloque_un_doublon_construit_a_la_main(self):
        # Vérifie le filet de sécurité lui-même (verifier_unicite_matchs_coupons), indépendamment
        # du mécanisme proactif (matchs_utilises) — règle 8 : "bloquer la publication" si un
        # doublon est détecté, jamais le corriger silencieusement.
        resultats_avec_doublon = [
            {"profil": {"cle": "p1"}, "selections": [_selection("A vs B", "Total", "Over", 1.3)]},
            {"profil": {"cle": "p2"}, "selections": [_selection("A vs B", "BTTS", "Yes", 1.3)]},
        ]
        with self.assertRaises(ValueError):
            ae.verifier_unicite_matchs_coupons(resultats_avec_doublon)

    def test_garde_fou_final_ne_se_declenche_pas_sans_doublon(self):
        resultats_propres = [
            {"profil": {"cle": "p1"}, "selections": [_selection("A vs B", "Total", "Over", 1.3)]},
            {"profil": {"cle": "p2"}, "selections": [_selection("C vs D", "Total", "Over", 1.3)]},
        ]
        ae.verifier_unicite_matchs_coupons(resultats_propres)  # ne doit lever aucune exception


class TestDedoublonnageMultiSources(unittest.TestCase):
    """Règle 2 de la mission : un même match renvoyé plusieurs fois (OddsPapi renvoie parfois
    deux fois le même vrai match, constaté en pratique) ne doit jamais être compté deux fois
    dans la sélection du jour."""

    def test_match_renvoye_deux_fois_dedoublonne(self):
        fixtures = [
            _fixture("Chelsea", "Arsenal", fid="source-1"),
            _fixture("Chelsea", "Arsenal", fid="source-2"),  # même rencontre, entrée distincte
            _fixture("Liverpool", "Everton", fid="source-3"),
        ]
        matchs = cd.selectionner_matchs_du_jour(fixtures)
        self.assertEqual(matchs.count(("Chelsea", "Arsenal")), 1)
        self.assertIn(("Liverpool", "Everton"), matchs)
        self.assertEqual(len(matchs), 2)


class TestFuseauHoraireEtMinuit(unittest.TestCase):
    """Règle 1 + tests obligatoires "gestion des fuseaux horaires, changement de date, matchs
    proches de minuit" : assez_tot_avant_coup_envoi/selectionner_matchs_du_jour comparent des
    horodatages UTC absolus (jamais une heure locale ambiguë), donc un passage de minuit ne
    change rien au calcul du délai réel avant le coup d'envoi."""

    def test_match_juste_apres_minuit_UTC_reste_filtre_par_le_delai_normal(self):
        maintenant = "2099-01-01T23:50:00+00:00"
        depart_trop_proche = "2099-01-02T00:10:00Z"  # 20 min plus tard, après minuit UTC
        depart_assez_loin = "2099-01-02T00:40:00Z"    # 50 min plus tard, après minuit UTC
        from datetime import datetime
        maintenant_dt = datetime.fromisoformat(maintenant)
        self.assertFalse(cd.assez_tot_avant_coup_envoi(depart_trop_proche, maintenant_dt))
        self.assertTrue(cd.assez_tot_avant_coup_envoi(depart_assez_loin, maintenant_dt))

    def test_match_deja_commence_exclu_meme_proche_de_minuit(self):
        fixtures = [
            _fixture("Chelsea", "Arsenal", depart="2099-01-01T23:59:00Z"),
        ]
        for fx in fixtures:
            fx["statusName"] = "Live"  # déjà en cours, quel que soit le délai
        matchs = cd.selectionner_matchs_du_jour(fixtures)
        self.assertEqual(matchs, [])

    def test_horodatage_avec_offset_non_utc_reste_compare_correctement(self):
        # +02:00 au lieu de Z : assez_tot_avant_coup_envoi convertit tout en absolu (timedelta
        # entre deux datetime timezone-aware), jamais une comparaison de chaînes ou d'heures
        # locales nues qui se tromperait au changement de jour.
        maintenant = "2099-01-01T22:00:00+00:00"
        depart_avec_offset = "2099-01-02T01:00:00+02:00"  # = 2099-01-01T23:00:00Z, 1h plus tard
        from datetime import datetime
        maintenant_dt = datetime.fromisoformat(maintenant)
        self.assertTrue(cd.assez_tot_avant_coup_envoi(depart_avec_offset, maintenant_dt))


class TestRejeuSansDoublonNiAccumulation(unittest.TestCase):
    """Test obligatoire "rejeu du workflow sans génération ou publication de doublon
    accidentelle" : matchs_utilises est une variable LOCALE à generer_coupons (jamais un état
    de module persistant) — deux runs indépendants sur le même pool ne doivent ni se bloquer
    l'un l'autre, ni accumuler un historique de matchs "déjà utilisés" entre deux exécutions
    séparées du pipeline (seul CE run contrôle sa propre unicité)."""

    def test_deux_runs_independants_retrouvent_le_meme_resultat_deterministe(self):
        pool = {
            "A vs B": [_selection("A vs B", "Total", "Over", 1.3)],
            "C vs D": [_selection("C vs D", "Total", "Over", 1.3)],
            "E vs F": [_selection("E vs F", "Total", "Over", 1.3)],
        }
        donnees = {"matchs": [], "mode_manuel": True}
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool):
            resultats_run1 = ae.generer_coupons(donnees)
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool):
            resultats_run2 = ae.generer_coupons(donnees)
        matchs_run1 = sorted(s["match"] for s in resultats_run1[0]["selections"])
        matchs_run2 = sorted(s["match"] for s in resultats_run2[0]["selections"])
        # Le run 2 retrouve l'intégralité du pool (mode manuel: exiger_tous_les_matchs=True) —
        # rien du run 1 n'est resté "verrouillé" en mémoire pour bloquer le run 2.
        self.assertEqual(matchs_run1, ["A vs B", "C vs D", "E vs F"])
        self.assertEqual(matchs_run2, ["A vs B", "C vs D", "E vs F"])

    def test_unicite_verifiee_independamment_a_chaque_appel(self):
        pool = {f"M{i} vs A{i}": [_selection(f"M{i} vs A{i}", "Total", "Over", 1.2)] for i in range(8)}
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", False):
            resultats_run1 = ae.generer_coupons({"matchs": []})
            resultats_run2 = ae.generer_coupons({"matchs": []})
        for resultats in (resultats_run1, resultats_run2):
            vus = set()
            for item in resultats:
                for s in item["selections"]:
                    self.assertNotIn(s["match"], vus)
                    vus.add(s["match"])


if __name__ == "__main__":
    unittest.main()
