"""Améliorations du 07/11/2026 (côté agent et moteurs) : jambes de remplissage, plafond de coupons par match, matchs commencés, fraîcheur des cotes. Aucune API."""
from datetime import datetime, timedelta, timezone

import pytest

import agent_strategie as st
import matchs_a_venir as mav
import moteur_deterministe as md
import profils_smart
from moteur import profils_risque as pr


# ---- jambes de remplissage ----------------------------------------------------------------------------------------------------------------------------------------
def test_jambes_de_remplissage_comptees_et_limitees(monkeypatch):
    monkeypatch.setattr(st, "COTE_JAMBE_REMPLISSAGE", 1.22)
    monkeypatch.setattr(st, "MAX_JAMBES_REMPLISSAGE", 2)
    assert st.jambes_de_remplissage([1.20, 1.22, 1.23, 1.5, None]) == 2
    monkeypatch.setattr(pr, "COTE_JAMBE_REMPLISSAGE", 1.22)
    monkeypatch.setattr(pr, "MAX_JAMBES_REMPLISSAGE", 2)

    def jambe(i, cote):
        cat, sel = (("Total", "Over"), ("Double Chance", "1X"), ("BTTS", "Yes"), ("Corners", "Under"), ("Total", "Under"), ("Cartons", "Over"))[i % 6]
        return {"match": f"M{i}", "competition": f"L{i}", "categorie": cat, "selection": sel, "p": 0.7, "cote": cote}
    assert pr.regles_coupon([jambe(i, 1.2) for i in range(2)] + [jambe(i + 2, 1.4) for i in range(4)]) == []             # 2 jambes de remplissage : accepté
    problemes = pr.regles_coupon([jambe(i, 1.2) for i in range(3)] + [jambe(i + 3, 1.4) for i in range(3)])
    assert any("remplissage" in p for p in problemes)                                                                 # 3 : refusé
    monkeypatch.setattr(pr, "MAX_JAMBES_REMPLISSAGE", 0)
    assert pr.regles_coupon([jambe(i, 1.2) for i in range(6)]) == []                                                   # 0 = pas de limite


def test_l_agent_refuse_trop_de_jambes_de_remplissage(monkeypatch):
    monkeypatch.setattr(st, "MAX_JAMBES_REMPLISSAGE", 2)
    monkeypatch.setattr(st, "COTE_JAMBE_REMPLISSAGE", 1.22)
    cotes = [1.20, 1.21, 1.22, 1.40, 1.45]
    pool = {f"M{i} - X{i}": [{"match": f"M{i} - X{i}", "competition": "L1",
                              "pick": {"categorie": "Total", "marche": "Over Under Full Time (2.5)", "selection": "Over", "handicap": 2.5, "cote": c,
                                       "proba_modele_pct": 75.0, "edge_pct": 1.0, "marche_affichage": "Total"}}] for i, c in enumerate(cotes)}
    catalogue, _ = st.construire_catalogue(pool, seuil_proba=0)
    ids = list(catalogue)
    profil = dict(profils_smart.profils(contraintes=False)[0], nb_jambes_min=5, nb_jambes=12)
    proposition = {"coupons": [{"profil": "coupon1", "strategie": "s", "jambes": [{"id": i, "raison": "r"} for i in ids]}]}
    acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])
    assert "coupon1" not in acceptes and "remplissage" in " ".join(problemes)
    monkeypatch.setattr(st, "MAX_JAMBES_REMPLISSAGE", 3)
    acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])
    assert "coupon1" in acceptes, problemes


# ---- plafond de coupons par match ---------------------------------------------------------------------------------------------------------------------------------
def test_profils_par_defaut_plafonnent_a_deux_coupons_par_match(monkeypatch):
    assert all(p["max_coupons_par_match"] == 2 for p in profils_smart.profils())
    assert all("max_coupons_par_match" not in p for p in profils_smart.profils(contraintes=False))
    monkeypatch.setenv("MAX_COUPONS_PAR_MATCH", "0")
    assert all("max_coupons_par_match" not in p for p in profils_smart.profils())
    assert all(p["max_coupons_par_match"] == 3 for p in profils_smart.profils(max_coupons_par_match=3))


def _pool(n=19):
    return {f"M{i}": [{"match": f"M{i}", "competition": f"L{i % 4}",
                       "pick": {"categorie": cat, "selection": sel, "cote": cote, "proba_modele_pct": p, "edge_pct": 5.0, "marche": cat}}
                      for cat, sel, cote, p in (("Total", "Over", 1.55, 66), ("Double Chance", "1X", 1.35, 75), ("BTTS", "Yes", 2.0, 52), ("Corners", "Under", 1.7, 60))]
            for i in range(n)}


def test_le_moteur_deterministe_respecte_le_plafond_de_coupons_par_match():
    res = md.composer(_pool(), profils_smart.profils(max_coupons_par_match=1))
    matchs = [s["match"] for r in res for s in r["selections"]]
    assert len(matchs) == len(set(matchs))                                    # plafond 1 : aucun match dans deux coupons
    res = md.composer(_pool(), profils_smart.profils(max_coupons_par_match=2))
    from collections import Counter
    assert max(Counter(s["match"] for r in res for s in r["selections"]).values()) <= 2


def test_le_moteur_central_respecte_le_plafond_de_coupons_par_match():
    from moteur_central.profils import selectionner_profils
    from moteur_central.score_central import CandidatCentral
    cands = [CandidatCentral(match=f"M{i}", marche=cat, selection=sel, cote=cote, moteur_responsable="x", proba_pct=p, categorie=cat, competition=f"L{i % 4}")
             for i in range(19) for cat, sel, cote, p in (("Total", "Over", 1.55, 66), ("Double Chance", "1X", 1.35, 75), ("BTTS", "Yes", 2.0, 52), ("Corners", "Under", 1.7, 60))]
    from collections import Counter
    sortie = selectionner_profils(cands, profils_smart.profils(max_coupons_par_match=2))
    comptes = Counter(c.match for r in sortie for c in r["jambes"])
    assert comptes and max(comptes.values()) <= 2
    assert pr.regles_entre_coupons([[{"match": "A", "categorie": "x", "selection": "1"}], [{"match": "A", "categorie": "x", "selection": "2"}],
                                    [{"match": "A", "categorie": "x", "selection": "3"}]], True, 2) != []


# ---- paramètres du formulaire ---------------------------------------------------------------------------------------------------------------------------------------
def test_intervalles_du_formulaire():
    assert profils_smart.analyser_intervalle("5-12", entier=True) == (5, 12)
    assert profils_smart.analyser_intervalle(" 3 - 6 ", entier=True) == (3, 6)
    assert profils_smart.analyser_intervalle("5-10") == (5.0, 10.0)
    assert profils_smart.analyser_intervalle("10-5") is None and profils_smart.analyser_intervalle("abc") is None and profils_smart.analyser_intervalle("") is None
    assert profils_smart.analyser_intervalle("0-5") is None


# ---- matchs commencés et fraîcheur des cotes ------------------------------------------------------------------------------------------------------------------
def _match(nom, debut, source="api_football"):
    m = {"match_demande": {"home": nom, "away": "X"}, "oddspapi": {"tous_marches": [1, 2], "start_time": None}, "api_football": {}}
    if source == "api_football":
        m["api_football"] = {"home_name": nom, "away_name": "X", "fixture_date": debut}
    else:
        m["oddspapi"]["start_time"] = debut
    return m


def test_les_matchs_commences_sont_retires_sans_modifier_l_entree(monkeypatch):
    monkeypatch.delenv("FILTRER_MATCHS_COMMENCES", raising=False)
    maintenant = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)
    donnees = {"nb_matchs_demandes": 4, "nb_matchs_avec_marches": 4, "nb_marches_total": 8, "matchs": [
        _match("Leeds", "2026-11-07T12:30:00+00:00"),                    # commencé
        _match("Torino", "2026-11-07T14:05:00+00:00"),                   # dans 5 minutes : sous la marge de 10 minutes
        _match("Arsenal", "2026-11-07T15:00:00+00:00"),                  # à venir
        _match("Roma", "2026-11-07T19:45:00Z", source="oddspapi"),       # à venir, coup d'envoi OddsPapi
    ]}
    filtrees, retires = mav.retirer_matchs_commences(donnees, maintenant=maintenant)
    assert retires == ["Leeds - X", "Torino - X"] and [m["match_demande"]["home"] for m in filtrees["matchs"]] == ["Arsenal", "Roma"]
    assert filtrees["nb_matchs_avec_marches"] == 2 and filtrees["nb_matchs_demandes"] == 2 and filtrees["nb_marches_total"] == 4
    assert len(donnees["matchs"]) == 4                                   # l'entrée n'est pas modifiée


def test_un_coup_d_envoi_inconnu_garde_le_match_et_le_filtre_est_desactivable(monkeypatch):
    maintenant = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)
    donnees = {"matchs": [_match("Inconnu", None), _match("Leeds", "2026-11-07T12:30:00+00:00")]}
    monkeypatch.delenv("FILTRER_MATCHS_COMMENCES", raising=False)
    assert [m["match_demande"]["home"] for m in mav.retirer_matchs_commences(donnees, maintenant=maintenant)[0]["matchs"]] == ["Inconnu"]
    monkeypatch.setenv("FILTRER_MATCHS_COMMENCES", "0")
    assert mav.retirer_matchs_commences(donnees, maintenant=maintenant) == (donnees, [])


def test_ligne_de_fraicheur_des_cotes():
    donnees = {"date_collecte": "2026-11-07T06:25:39+00:00", "matchs": [_match("Arsenal", "2026-11-07T15:00:00+00:00"), _match("Leeds", "2026-11-07T12:30:00+00:00")]}
    ligne = mav.ligne_fraicheur(donnees, maintenant=datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc))
    assert "06:25 UTC" in ligne and "prochain match à 15:00 UTC" in ligne and "1xBet" in ligne
    assert mav.ligne_fraicheur({}, maintenant=datetime.now(timezone.utc)) == ""
    assert "prochain match" not in mav.ligne_fraicheur({"date_collecte": "2026-11-07T06:25:39+00:00", "matchs": []}, maintenant=datetime.now(timezone.utc))


# ---- intégration dans l'agent pilote ------------------------------------------------------------------------------------------------------------------------------
def test_l_agent_n_utilise_que_des_matchs_a_venir_et_ajoute_la_fraicheur_des_cotes(monkeypatch):
    import agent_pilote as pilote
    import analyser_et_envoyer as ae
    from unittest import mock
    from test_agent_pilote import POOL_SIX_MATCHS, PROFIL_1, _msg_outil
    monkeypatch.setenv("FILTRER_MATCHS_COMMENCES", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "cle-test")
    futur = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    donnees = {"date_collecte": "2026-11-07T06:25:39+00:00", "nb_matchs_demandes": 2, "nb_matchs_avec_marches": 2, "nb_marches_total": 4,
               "matchs": [_match("Passe", "2020-01-01T10:00:00+00:00"), _match("Futur", futur)]}
    reponses = [_msg_outil("collecter_donnees", {}), _msg_outil("voir_catalogue", {}),
                _msg_outil("proposer_coupon", {"strategie": "s", "jambes": [{"id": "P1", "raison": "r"}]}), _msg_outil("envoyer_telegram", {})]
    with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
            mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
            mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
        resultat = pilote.executer(telegram=True, profils=[PROFIL_1], donnees_reprises=donnees)
    assert [m["match_demande"]["home"] for m in resultat["donnees"]["matchs"]] == ["Futur"]
    textes = envoi.call_args[0][0]
    assert any("Cotes relevées à 06:25 UTC" in t and "prochain match à" in t for t in textes)


def test_tous_les_matchs_commences_aucun_appel_ia(monkeypatch):
    import agent_pilote as pilote
    from unittest import mock
    from test_agent_pilote import PROFIL_1
    monkeypatch.setenv("FILTRER_MATCHS_COMMENCES", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "cle-test")
    donnees = {"nb_matchs_demandes": 1, "nb_matchs_avec_marches": 1, "nb_marches_total": 2, "matchs": [_match("Passe", "2020-01-01T10:00:00+00:00")]}
    with mock.patch.object(pilote, "_appel_api") as appel:
        resultat = pilote.executer(telegram=True, profils=[PROFIL_1], donnees_reprises=donnees)
    appel.assert_not_called()
    assert "aucun match" in resultat["raison_abandon"]
