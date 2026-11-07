"""Phase 3 (06/11/2026) : coûts et tokens du vote enregistrés, vainqueur conservé, budget journalier jamais dépassé en silence."""
import json
from unittest import mock

import pytest

import agent_pilote as pilote
import analyser_et_envoyer as ae
import budget_ia
import collecte_donnees as cd
import vote
from test_agent_pilote import DONNEES_FACTICES, POOL_SIX_MATCHS, PROFIL_1, _msg_outil


# ---------- budget_ia (pur) ----------
def test_lire_budget():
    assert budget_ia.lire_budget(None) is None and budget_ia.lire_budget("") is None and budget_ia.lire_budget("aucun") is None
    assert budget_ia.lire_budget("3") == 3.0 and budget_ia.lire_budget("2,5 $") == 2.5 and budget_ia.lire_budget("0") == 0.0
    assert budget_ia.lire_budget("abc") == 0.0 and budget_ia.lire_budget("-1") == 0.0   # mal saisi : prudence, jamais « illimité »


def test_repartition_sans_plafond_ni_manque():
    assert budget_ia.repartir(None, ["a", "b"], 0.6) == ({"a": 0.6, "b": 0.6}, [])
    budgets, ignores = budget_ia.repartir(2.0, ["a", "b"], 0.6, minimum=0.1)
    assert budgets == {"a": 0.6, "b": 0.6} and ignores == []
    budgets, _ = budget_ia.repartir(0.8, ["a", "b"], 0.6, minimum=0.1)
    assert budgets == {"a": 0.4, "b": 0.4}              # la part ne dépasse jamais le restant


def test_repartition_budget_insuffisant_retient_moins_de_modeles():
    budgets, ignores = budget_ia.repartir(0.15, ["a", "b", "c"], 0.6, minimum=0.1)
    assert list(budgets) == ["a"] and budgets["a"] == pytest.approx(0.15)
    assert [m for m, _ in ignores] == ["b", "c"] and "insuffisant" in ignores[0][1]
    budgets, ignores = budget_ia.repartir(0.0, ["a", "b"], 0.6)
    assert budgets == {} and all("plafond journalier atteint" in r for _, r in ignores)
    assert budget_ia.repartir(0.05, ["a"], 0.6, minimum=0.1)[0] == {}


def test_bilan_couts_tokens_cout_gagnants_et_depassement():
    resultats = [{"modele": "gpt", "tokens_entree": 100, "tokens_sortie": 50, "cout_usd": 0.30, "appels": 2, "erreur": None,
                  "coupons": [{"dans_la_bande": True}, {"dans_la_bande": False}]},
                 {"modele": "gemini", "tokens_entree": 80, "tokens_sortie": 20, "cout_usd": 0.20, "appels": 1, "erreur": "délai",
                  "coupons": []}]
    b = budget_ia.bilan_couts({"tokens_entree": 5, "tokens_sortie": 1, "cout_usd": 0.0}, resultats, {"c1": "gpt", "c2": "gpt"}, 0.4, [])
    assert b["total_usd"] == 0.5 and b["depassement_usd"] == 0.1 and "dépassement" in b["alerte"]
    gpt = next(m for m in b["vote"] if m["modele"] == "gpt")
    assert (gpt["tokens_entree"], gpt["tokens_sortie"], gpt["cout_usd"], gpt["coupons_valides"], gpt["coupons_retenus"]) == (100, 50, 0.3, 1, 2)
    assert next(m for m in b["vote"] if m["modele"] == "gemini")["erreur"] == "délai"
    assert b["gagnants"] == {"c1": "gpt", "c2": "gpt"}
    sans_plafond = budget_ia.bilan_couts({}, resultats, {}, None, [])
    assert "depassement_usd" not in sans_plafond and "alerte" not in sans_plafond


def test_vote_conserve_le_modele_gagnant_par_profil():
    p = [{"cle": "c1"}]
    faible = [{"match": "A", "pick": {"proba_modele_pct": 60.0, "marche": "m", "selection": "s"}}]
    fort = [{"match": "B", "pick": {"proba_modele_pct": 90.0, "marche": "m", "selection": "s"}}]
    res, journal, gagnants = vote.choisir_detail(
        p, [{"profil": p[0], "selections": faible}],
        [{"modele": "gpt", "coupons": [{"profil": "c1", "dans_la_bande": True, "selections": fort}]}])
    assert gagnants == {"c1": "gpt"} and res[0]["selections"] == fort
    assert vote.choisir(p, [{"profil": p[0], "selections": faible}], [])[0][0]["selections"] == faible   # ancien appel inchangé
    assert vote.choisir_detail(p, [{"profil": p[0], "selections": faible}], [])[2] == {"c1": "pilote"}


# ---------- intégration pilote ----------
def _lancer(monkeypatch, restant, composer, modeles="gpt,gemini"):
    import ombre
    monkeypatch.setenv("DEEPSEEK_API_KEY", "cle-test")
    monkeypatch.setenv("MODELES_VOTE", modeles)
    monkeypatch.setenv("OMBRE_BUDGET_USD", "0.6")
    reponses = [_msg_outil("collecter_donnees", {}), _msg_outil("voir_catalogue", {}),
                _msg_outil("proposer_coupon", {"strategie": "s", "jambes": [{"id": "P1", "raison": "r"}]}),
                _msg_outil("envoyer_telegram", {})]
    for r in reponses:   # le pilote consomme aussi des tokens : ils doivent être comptés
        r["usage"] = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200, "cost": 0.0}   # coût 0 RENVOYÉ par le fournisseur (un coût absent n'est plus gratuit : Phase 4)
    with mock.patch.object(cd, "collecter_donnees", return_value=None), \
            mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
            mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
            mock.patch.object(ombre, "composer_ombre", side_effect=composer) as appel_ombre, \
            mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True), \
            mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
        return pilote.executer(telegram=True, profils=[PROFIL_1], budget_restant_usd=restant), appel_ombre


def _composer_fort(pool, profils, catalogue, texte, modeles, **k):
    lignes = [v[0] for v in POOL_SIX_MATCHS.values()]
    fort = {"match": lignes[5]["match"], "pick": dict(lignes[5]["pick"], proba_modele_pct=90.0)}
    return [{"modele": m, "erreur": None, "tokens_entree": 100 * (i + 1), "tokens_sortie": 10 * (i + 1), "cout_usd": 0.05 * (i + 1),
             "appels": 1, "secondes": 3,
             "coupons": [{"profil": profils[0]["cle"], "dans_la_bande": True, "selections": [fort]}]} for i, m in enumerate(modeles)]


def test_run_enregistre_couts_tokens_et_gagnant_du_vote(monkeypatch):
    resultat, appel = _lancer(monkeypatch, None, _composer_fort)
    couts = resultat["journal"]["couts"]
    assert resultat["couts"] == couts
    assert [m["modele"] for m in couts["vote"]] == ["gpt", "gemini"]
    assert [m["cout_usd"] for m in couts["vote"]] == [0.05, 0.1] and couts["total_usd"] == 0.15
    assert couts["vote"][1]["tokens_entree"] == 200 and couts["vote"][1]["tokens_sortie"] == 20
    assert couts["gagnants"] == {PROFIL_1["cle"]: "gpt"}                       # égalité de proba : premier modèle devant
    assert couts["pilote"]["tokens_entree"] == 4000 and couts["pilote"]["tokens_sortie"] == 800   # 4 appels du pilote
    assert resultat["journal"]["vote"][0].startswith(f"{PROFIL_1['cle']} :")       # résultat du vote conservé
    assert "alerte" not in couts and appel.call_args.kwargs["budgets_par_modele"] is None   # pas de plafond configuré : comportement inchangé


def test_budget_epuise_aucun_appel_payant_du_tout(monkeypatch):
    """Décision du 06/11/2026 : budget épuisé = AUCUN appel payant (ni pilote, ni vote). Arrêt explicite, jamais silencieux."""
    import ombre
    monkeypatch.setenv("DEEPSEEK_API_KEY", "cle-test")
    monkeypatch.setenv("MODELES_VOTE", "gpt,gemini")
    with mock.patch.object(cd, "collecter_donnees", return_value=None), \
            mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
            mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
            mock.patch.object(ombre, "composer_ombre") as vote_ia, mock.patch.object(pilote, "_appel_api") as pilote_ia, \
            mock.patch.object(ae, "agent5_envoyer_coupons") as envoi:
        resultat = pilote.executer(telegram=True, profils=[PROFIL_1], budget_restant_usd=0.0)
    vote_ia.assert_not_called()
    pilote_ia.assert_not_called()
    envoi.assert_not_called()
    assert resultat["envoye"] is False and "budget IA du jour épuisé" in resultat["raison_abandon"]
    assert "plafond journalier atteint" in resultat["journal"]["couts"]["alerte"] and resultat["couts"]["total_usd"] == 0


def test_cout_du_pilote_mesure_ou_estime(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_PRIX_ENTREE_USD_M", raising=False)
    monkeypatch.delenv("DEEPSEEK_PRIX_SORTIE_USD_M", raising=False)
    assert pilote._cout_appel({"cost": 0.0123, "prompt_tokens": 5}) == 0.0123                 # coût renvoyé par le fournisseur
    assert pilote._cout_appel({"prompt_tokens": 1000, "completion_tokens": 500}) == pytest.approx(0.0105)   # Phase 4 : ni coût ni prix = estimation PRUDENTE (3 et 15 $/M), jamais 0
    monkeypatch.setenv("DEEPSEEK_PRIX_ENTREE_USD_M", "0.5")
    monkeypatch.setenv("DEEPSEEK_PRIX_SORTIE_USD_M", "2")
    assert pilote._cout_appel({"prompt_tokens": 1_000_000, "completion_tokens": 500_000}) == pytest.approx(1.5)
    monkeypatch.setenv("DEEPSEEK_PRIX_ENTREE_USD_M", "abc")
    assert pilote._cout_appel({"prompt_tokens": 10}) == pytest.approx(3e-05)                   # prix illisible : jamais d'exception, estimation prudente (pas 0)


def test_le_pilote_openrouter_demande_le_cout_reel(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "cle")
    monkeypatch.setenv("PILOTE_MODELE", "openai/gpt-6.1-sol")
    courses = pilote._fournisseurs_secours()
    assert courses and courses[0][4].get("usage") == {"include": True}


def test_budget_partiel_reduit_le_vote_et_plafonne_chaque_modele(monkeypatch):
    resultat, appel = _lancer(monkeypatch, 0.15, _composer_fort)
    assert appel.call_args.args[4] == ["gpt"]                                                   # un seul modèle retenu
    assert appel.call_args.kwargs["budgets_par_modele"]["gpt"] == pytest.approx(0.15)
    couts = resultat["journal"]["couts"]
    assert [m["modele"] for m in couts["modeles_ignores"]] == ["gemini"] and "insuffisant" in couts["alerte"]


def test_depassement_du_dernier_appel_est_mesure_et_signale(monkeypatch):
    def composer_cher(pool, profils, catalogue, texte, modeles, **k):
        return [{"modele": modeles[0], "erreur": None, "tokens_entree": 1, "tokens_sortie": 1, "cout_usd": 0.50, "appels": 3,
                 "coupons": []}]
    resultat, _ = _lancer(monkeypatch, 0.30, composer_cher, modeles="gpt")
    couts = resultat["journal"]["couts"]
    assert couts["depassement_usd"] == pytest.approx(0.2) and "dépassement" in couts["alerte"]


def test_modele_indisponible_le_vote_continue_avec_les_autres(monkeypatch):
    def composer_un_en_panne(pool, profils, catalogue, texte, modeles, **k):
        sortie = _composer_fort(pool, profils, catalogue, texte, modeles)
        sortie[0].update(erreur="HTTP 503", coupons=[], cout_usd=None)
        return sortie
    resultat, _ = _lancer(monkeypatch, 3.0, composer_un_en_panne)
    couts = resultat["journal"]["couts"]
    assert couts["vote"][0]["erreur"] == "HTTP 503" and couts["gagnants"] == {PROFIL_1["cle"]: "gemini"}
    assert resultat["envoye"] is True


def test_mode_modele_seul_budget_insuffisant_abandonne_explicitement(monkeypatch):
    import ombre
    monkeypatch.setenv("DEEPSEEK_API_KEY", "cle-test")
    monkeypatch.setenv("COMPOSITEUR_MODELE", "gpt")
    with mock.patch.object(cd, "collecter_donnees", return_value=None), \
            mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
            mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
            mock.patch.object(ombre, "composer_ombre") as appel, mock.patch.object(ae, "agent5_envoyer_coupons") as envoi:
        resultat = pilote.executer(telegram=True, profils=[PROFIL_1], budget_restant_usd=0.0)
    appel.assert_not_called()
    envoi.assert_not_called()
    assert resultat["envoye"] is False and "budget IA" in resultat["raison_abandon"]
    assert "plafond journalier atteint" in resultat["journal"]["couts"]["alerte"]
