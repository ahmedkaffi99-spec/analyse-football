"""Tests des DEUX handicaps de buts du Bet Agent (08/11/2026) : Asian Handicap (entier, demi, quart ; gagné, demi-gagné, remboursé, demi-perdu, perdu) et European Handicap (3 voies 1/X/2, score ajusté).
Pour chaque ligne : probabilités, cote juste (Fair Odds), EV et règlement. Aucune dépendance réseau ni clé."""

import itertools

import pytest

import analyser_et_envoyer as ae
import handicaps as hc
import modele_probabilites as mp
import verifier_resultats as vr
from moteur.modeles import marches as m

ISSUES = m.ISSUES
LIGNES_AH = [x / 4 for x in range(-14, 15)]          # -3.5 ... +3.5 par pas de 0,25
LIGNES_EH = [-3, -2, -1, 0, 1, 2, 3]
SCORES = list(itertools.product(range(0, 7), range(0, 7)))


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ASIAN HANDICAP : nature des lignes et règlement
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ligne,genre", [(0, "entiere"), (-1, "entiere"), (2, "entiere"), (-0.5, "demie"), (1.5, "demie"), (-0.25, "quart"), (0.75, "quart"), (-2.75, "quart")])
def test_type_de_ligne_asiatique(ligne, genre):
    assert hc.type_ligne_asiatique(ligne) == genre


@pytest.mark.parametrize("ligne", [0.1, -0.3, 1.2, 0.6])
def test_ligne_asiatique_invalide_refusee(ligne):
    with pytest.raises(ValueError):
        hc.type_ligne_asiatique(ligne)


# (ligne domicile, score, sélection) -> issue attendue
CAS_AH = [
    # ligne entière : remboursement possible
    (-1, (2, 0), "1", "gagne"), (-1, (1, 0), "1", "rembourse"), (-1, (0, 0), "1", "perdu"),
    (-1, (1, 0), "2", "rembourse"), (-1, (0, 0), "2", "gagne"), (-1, (2, 0), "2", "perdu"),
    (0, (1, 1), "1", "rembourse"), (0, (1, 1), "2", "rembourse"), (0, (2, 1), "1", "gagne"), (0, (1, 2), "2", "gagne"),
    # ligne demie : jamais de remboursement
    (-1.5, (2, 0), "1", "gagne"), (-1.5, (1, 0), "1", "perdu"), (-1.5, (1, 0), "2", "gagne"), (0.5, (0, 0), "1", "gagne"), (0.5, (0, 1), "1", "perdu"),
    # quart négatif -0,75 (= -0,5 et -1) : gagne à +2, DEMI-GAIN à +1, perd sinon
    (-0.75, (2, 0), "1", "gagne"), (-0.75, (1, 0), "1", "demi_gagne"), (-0.75, (1, 1), "1", "perdu"),
    (-0.75, (1, 0), "2", "demi_perdu"), (-0.75, (1, 1), "2", "gagne"), (-0.75, (3, 1), "2", "perdu"),
    # quart négatif -0,25 (= 0 et -0,5) : DEMI-PERTE sur le nul
    (-0.25, (1, 0), "1", "gagne"), (-0.25, (1, 1), "1", "demi_perdu"), (-0.25, (0, 1), "1", "perdu"),
    (-0.25, (1, 1), "2", "demi_gagne"), (-0.25, (0, 1), "2", "gagne"),
    # quart positif +0,25 (= 0 et +0,5) : DEMI-GAIN sur le nul
    (0.25, (1, 1), "1", "demi_gagne"), (0.25, (0, 1), "1", "perdu"), (0.25, (2, 1), "1", "gagne"),
    (0.25, (1, 1), "2", "demi_perdu"), (0.25, (0, 1), "2", "gagne"),
    # quart positif +0,75 (= +0,5 et +1) : DEMI-PERTE si l'équipe perd d'un but
    (0.75, (0, 1), "1", "demi_perdu"), (0.75, (0, 2), "1", "perdu"), (0.75, (1, 1), "1", "gagne"),
    (0.75, (0, 1), "2", "demi_gagne"), (0.75, (0, 2), "2", "gagne"),
    # grands quarts
    (-1.25, (2, 0), "1", "gagne"), (-1.25, (1, 0), "1", "demi_perdu"), (-1.25, (0, 0), "1", "perdu"), (-1.25, (2, 1), "1", "demi_perdu"),
    (1.75, (0, 1), "1", "gagne"), (1.75, (0, 2), "1", "demi_perdu"), (1.75, (0, 3), "1", "perdu"),
]


@pytest.mark.parametrize("ligne,score,sel,attendu", CAS_AH)
def test_reglement_asiatique_cinq_issues(ligne, score, sel, attendu):
    assert hc.issue_asiatique(score[0], score[1], ligne, sel) == attendu
    # la vérification de production (verifier_resultats) rend le même verdict (« rembourse » s'appelle « push » côté base)
    verdict = vr.juger_handicap(ligne, sel, score[0], score[1])
    assert verdict == {"rembourse": "push"}.get(attendu, attendu)


def test_profits_selon_l_issue():
    cote = 1.9
    assert hc.reglement_asiatique(2, 0, -1, "1", cote) == {"issue": "gagne", "profit": pytest.approx(0.9), "retour": pytest.approx(1.9)}
    assert hc.reglement_asiatique(1, 0, -1, "1", cote)["profit"] == 0.0 and hc.reglement_asiatique(1, 0, -1, "1", cote)["retour"] == 1.0
    assert hc.reglement_asiatique(1, 0, -0.75, "1", cote)["profit"] == pytest.approx(0.45)          # demi-gain : la moitié de (cote - 1)
    assert hc.reglement_asiatique(1, 1, -0.25, "1", cote)["profit"] == pytest.approx(-0.5)          # demi-perte : la moitié de la mise
    assert hc.reglement_asiatique(0, 2, -1, "1", cote)["profit"] == -1.0
    assert hc.reglement_asiatique(2, 0, -1, "1", cote, mise=10)["profit"] == pytest.approx(9.0)      # mise 10


@pytest.mark.parametrize("ligne", LIGNES_AH)
def test_deux_implementations_du_reglement_asiatique_ne_divergent_jamais(ligne):
    for (h, a), sel in itertools.product(SCORES, ("1", "2")):
        voulu = m.issue_buts("handicap", ligne, sel, h, a)
        assert vr.juger_handicap(ligne, sel, h, a) == {"rembourse": "push"}.get(voulu, voulu), (ligne, sel, h, a)


@pytest.mark.parametrize("ligne", LIGNES_AH)
def test_asiatique_cotes_opposees_se_compensent_a_chaque_score(ligne):
    """Les deux côtés d'une même ligne sont des issues miroir : gagne <-> perdu, demi-gagne <-> demi-perdu, remboursé <-> remboursé."""
    miroir = {"gagne": "perdu", "perdu": "gagne", "demi_gagne": "demi_perdu", "demi_perdu": "demi_gagne", "rembourse": "rembourse"}
    for h, a in SCORES:
        assert hc.issue_asiatique(h, a, ligne, "2") == miroir[hc.issue_asiatique(h, a, ligne, "1")]


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ASIAN HANDICAP : probabilités, cote juste, EV
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ligne", LIGNES_AH)
def test_asiatique_probabilites_somment_a_un_et_ev_nulle_a_la_cote_juste(ligne):
    res = hc.analyser_ligne_asiatique(1.6, 1.1, ligne)
    for sel, d in res["selections"].items():
        assert sum(d["issues"].values()) == pytest.approx(1.0, abs=1e-9)
        if d["cote_juste"] is not None:
            assert m.esperance(d["issues"], d["cote_juste"]) == pytest.approx(0.0, abs=1e-9)    # à la cote juste, l'EV est nulle


def test_ligne_demie_cote_juste_est_l_inverse_de_la_probabilite():
    d = hc.analyser_ligne_asiatique(1.6, 1.1, -1.5)["selections"]["1"]
    assert d["issues"]["rembourse"] == 0 and d["issues"]["demi_gagne"] == 0
    assert d["cote_juste"] == pytest.approx(1 / d["issues"]["gagne"])


def test_ligne_de_quart_a_des_demi_issues_et_une_cote_juste_differente_de_1_sur_p():
    d = hc.analyser_ligne_asiatique(1.6, 1.1, -0.75)["selections"]["1"]
    assert d["issues"]["demi_gagne"] > 0 and d["issues"]["demi_perdu"] == 0
    assert d["cote_juste"] != pytest.approx(1 / d["issues"]["gagne"])


def test_ev_avec_cote_negative_ou_positive():
    res = hc.analyser_ligne_asiatique(1.6, 1.1, -0.75, cote_home=1.9, cote_away=1.9)
    cote_home, cote_away = res["selections"]["1"], res["selections"]["2"]
    assert cote_home["ev"] == pytest.approx(m.esperance(cote_home["issues"], 1.9), abs=1e-6)
    assert cote_home["ev"] < 0 < cote_away["ev"]            # le favori (domicile) à -0,75 à 1,90 est surcoté dans ce scénario
    sans_cote = hc.analyser_ligne_asiatique(1.6, 1.1, -0.75)
    assert sans_cote["selections"]["1"]["ev"] is None


@pytest.mark.parametrize("ligne", [-1.5, -1, -0.75, -0.25, 0, 0.25, 0.75, 1, 1.5])
def test_ev_de_la_distribution_egale_ev_du_reglement_score_par_score(ligne):
    matrice = hc.matrice_scores(1.6, 1.1)
    for sel in ("1", "2"):
        verif = hc.verifier_reglement(matrice, "AH", ligne, sel, 1.93)
        assert verif["coherent"], verif


def test_probabilites_independantes_de_la_methode_de_calcul():
    """issues_handicap (production) et la matrice de scores donnent les mêmes distributions."""
    matrice = hc.matrice_scores(1.4, 0.9)
    for ligne in (-1, -0.75, 0, 0.25, 1.5):
        a = mp.issues_handicap(1.4, 0.9, ligne)
        b = m.distribution_buts(matrice, "handicap", ligne, "1")
        for cle in ISSUES:
            assert a[cle] == pytest.approx(b[cle], abs=1e-9)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
# EUROPEAN HANDICAP : score ajusté et règlement
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ligne,score,resultat", [
    (-1, (2, 1), "X"), (-1, (3, 1), "1"), (-1, (1, 1), "2"), (-1, (0, 0), "2"),
    (-2, (4, 1), "1"), (-2, (3, 1), "X"), (-2, (1, 1), "2"),
    (1, (0, 1), "X"), (1, (0, 2), "2"), (1, (1, 1), "1"), (0, (1, 1), "X"), (0, (2, 1), "1"), (0, (1, 2), "2"),
    (2, (0, 2), "X"), (2, (0, 3), "2"), (2, (0, 1), "1"),
])
def test_resultat_handicap_europeen_sur_score_ajuste(ligne, score, resultat):
    assert m.resultat_handicap_europeen(score[0], score[1], ligne) == resultat
    assert hc.score_ajuste(score[0], ligne) == score[0] + ligne
    for sel in ("1", "X", "2"):
        assert hc.issue_europeenne(score[0], score[1], ligne, sel) == ("gagne" if sel == resultat else "perdu")


def test_le_nul_n_est_jamais_rembourse_en_europeen():
    for ligne in LIGNES_EH:
        for h, a in SCORES:
            issues = {hc.issue_europeenne(h, a, ligne, s) for s in ("1", "X", "2")}
            assert issues == {"gagne", "perdu"}            # exactement une sélection gagne, jamais de remboursement ni de demi-issue


def test_handicap_europeen_zero_est_le_1x2():
    for h, a in SCORES:
        assert m.resultat_handicap_europeen(h, a, 0) == ("1" if h > a else "X" if h == a else "2")


@pytest.mark.parametrize("ligne", [0.5, -1.5, 0.25, -0.75, 2.5])
def test_ligne_europeenne_non_entiere_refusee(ligne):
    assert not m.ligne_europeenne_valide(ligne)
    with pytest.raises(ValueError):
        m.resultat_handicap_europeen(1, 0, ligne)
    with pytest.raises(ValueError):
        mp.proba_handicap_europeen(1.5, 1.0, ligne)
    assert vr.juger_handicap_europeen(ligne, "1", 1, 0) is None


def test_selection_europeenne_invalide():
    with pytest.raises(ValueError):
        m.issue_handicap_europeen(1, 0, -1, "home")
    assert vr.juger_handicap_europeen(-1, "home", 1, 0) is None
    assert vr.juger_handicap_europeen(None, "1", 1, 0) is None


def test_reglement_europeen_profit():
    gagne = hc.reglement_europeen(3, 1, -1, "1", 2.5)
    assert gagne["issue"] == "gagne" and gagne["profit"] == pytest.approx(1.5) and gagne["retour"] == pytest.approx(2.5) and gagne["resultat_ajuste"] == "1"
    perdu = hc.reglement_europeen(2, 1, -1, "1", 2.5)
    assert perdu["issue"] == "perdu" and perdu["profit"] == -1.0 and perdu["retour"] == 0.0 and perdu["resultat_ajuste"] == "X"


def test_cas_reels_des_tickets_en_base_sont_maintenant_verifiables():
    """Jambes réelles restées « non_verifiable » : Uzbekistan 4-1 Syria, EH(-2) « 2 » (perdu : 4-2 > 1) et EH(-1) « 1 » (gagné : 4-1-1 > 1) ; Japan 0-0 Ecuador, EH(-1) « 1 » (perdu)."""
    assert vr.grader_pick({"categorie": "European Handicap", "selection": "2", "handicap": -2}, 4, 1) == "perdu"
    assert vr.grader_pick({"categorie": "European Handicap", "selection": "1", "handicap": -1}, 4, 1) == "gagne"
    assert vr.grader_pick({"categorie": "European Handicap", "selection": "1", "handicap": -1}, 0, 0) == "perdu"


def test_asian_et_european_restent_deux_marches_distincts_au_reglement():
    """Même ligne -1, même score 1-0, même sélection « 1 » : remboursé en asiatique, perdu en européen (le nul ajusté n'est pas un remboursement)."""
    assert vr.grader_pick({"categorie": "Handicap", "selection": "1", "handicap": -1}, 1, 0) == "push"
    assert vr.grader_pick({"categorie": "European Handicap", "selection": "1", "handicap": -1}, 1, 0) == "perdu"
    assert vr.grader_pick({"categorie": "European Handicap", "selection": "X", "handicap": -1}, 1, 0) == "gagne"


def test_ancienne_categorie_handicap_europeen_reste_jugee_comme_asiatique_pour_les_vieux_tickets():
    """Compatibilité : le libellé « Handicap Européen » (renommage bref du 01/10/2026) est un alias de l'Asian Handicap sur d'éventuels vieux tickets ; son règlement ne change pas."""
    assert vr.grader_pick({"categorie": "Handicap Européen", "selection": "1", "handicap": -1}, 1, 0) == "push"


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
# EUROPEAN HANDICAP : probabilités, cote juste, EV
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ligne", LIGNES_EH)
def test_europeen_probabilites_somment_a_un(ligne):
    probas = mp.proba_handicap_europeen(1.7, 1.0, ligne)
    assert set(probas) == {"1", "X", "2"}
    assert sum(probas.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(p >= 0 for p in probas.values())


def test_europeen_ligne_zero_egale_proba_1x2_du_modele():
    p1, px, p2 = mp.proba_1x2(1.7, 1.0)
    probas = mp.proba_handicap_europeen(1.7, 1.0, 0)
    assert probas["1"] == pytest.approx(p1, abs=2e-3) and probas["X"] == pytest.approx(px, abs=2e-3) and probas["2"] == pytest.approx(p2, abs=2e-3)


def test_europeen_handicap_negatif_defavorise_le_domicile():
    sans = mp.proba_handicap_europeen(1.7, 1.0, 0)
    avec = mp.proba_handicap_europeen(1.7, 1.0, -1)
    assert avec["1"] < sans["1"] and avec["2"] > sans["2"]


def test_europeen_cote_juste_ev_et_marge():
    cotes = {"1": 2.0, "X": 3.42, "2": 2.75}
    res = hc.analyser_ligne_europeenne(1.6, 1.1, -1, cotes)
    for sel, d in res["selections"].items():
        assert d["cote_juste"] == pytest.approx(100 / d["proba_pct"], rel=1e-3)
        assert d["ev"] == pytest.approx(d["proba_pct"] / 100 * cotes[sel] - 1, abs=1e-3)      # proba_pct est arrondie à 2 décimales
    assert res["marge_bookmaker_pct"] == pytest.approx((1 / 2.0 + 1 / 3.42 + 1 / 2.75 - 1) * 100, abs=0.01)
    assert hc.analyser_ligne_europeenne(1.6, 1.1, -1)["selections"]["1"]["ev"] is None       # sans cote : pas d'EV


@pytest.mark.parametrize("ligne", LIGNES_EH)
def test_europeen_ev_distribution_egale_ev_reglement(ligne):
    matrice = hc.matrice_scores(1.6, 1.1)
    for sel in ("1", "X", "2"):
        assert hc.verifier_reglement(matrice, "EH", ligne, sel, 3.1)["coherent"]


def test_verifier_reglement_detecte_une_incoherence_et_refuse_une_matrice_vide():
    with pytest.raises(ValueError):
        hc.verifier_reglement([], "AH", -1, "1", 2.0)
    matrice = hc.matrice_scores(1.6, 1.1)
    faux = hc.verifier_reglement(matrice, "AH", -0.75, "1", 1.9, tolerance=-1.0)             # tolérance impossible : le contrôle sait dire « incohérent »
    assert faux["coherent"] is False


def test_tableau_handicaps_une_entree_par_ligne():
    t = hc.tableau_handicaps(1.6, 1.1, lignes_asiatiques=(-1, -0.75, -0.5), lignes_europeennes=(-1, 0, 1))
    assert [e["type"] for e in t] == ["AH"] * 3 + ["EH"] * 3
    assert [e["ligne"] for e in t] == [-1, -0.75, -0.5, -1, 0, 1]


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
# INTÉGRATION AU PIPELINE (catalogue, formatage, familles)
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
MARCHES = [
    {"marche": "Asian Handicap", "handicap": -0.75, "periode": "fulltime", "selections": [{"selection": "1", "cote": 2.1}, {"selection": "2", "cote": 1.75}]},
    {"marche": "Asian Handicap", "handicap": -1, "periode": "fulltime", "selections": [{"selection": "1", "cote": 2.3}, {"selection": "2", "cote": 1.65}]},
    {"marche": "European Handicap", "handicap": -1, "periode": "fulltime", "selections": [{"selection": "1", "cote": 2.0}, {"selection": "X", "cote": 3.42}, {"selection": "2", "cote": 2.75}]},
]


def test_pipeline_produit_ah_entier_ah_quart_et_eh_avec_cote_juste_et_ev():
    cands = ae.evaluer_marches_toutes(MARCHES, 1.6, 1.1)
    par = {(c["categorie"], c["marche"], c["selection"]): c for c in cands}
    assert ("Handicap", "Asian Handicap (-1)", "1") in par and ("Handicap Asiatique", "Asian Handicap (-0.75)", "1") in par
    assert ("European Handicap", "European Handicap (-1)", "X") in par
    for c in cands:
        assert c["cote_juste"] is not None and c["ev_pct"] is not None
        assert c["proba_modele_pct"] is not None and c["edge_pct"] is not None


def test_pipeline_quart_asiatique_proba_equivalente_et_ev_exacts():
    marches = [MARCHES[0]]
    c = next(x for x in ae._evaluer_marches_brut(marches, 1.6, 1.1) if x["selection"] == "1")
    issues = mp.issues_handicap(1.6, 1.1, -0.75)
    assert c["ev_pct"] == pytest.approx(round(m.esperance(issues, 2.1) * 100, 1), abs=0.05)
    assert c["cote_juste"] == pytest.approx(m.cote_juste(issues), abs=1e-3)


def test_pipeline_ligne_europeenne_non_entiere_ignoree():
    marches = [{"marche": "European Handicap", "handicap": -1.5, "periode": "fulltime", "selections": [{"selection": "1", "cote": 2.0}, {"selection": "X", "cote": 3.4}, {"selection": "2", "cote": 2.7}]}]
    assert ae._evaluer_marches_brut(marches, 1.6, 1.1) == []


def test_pipeline_quarts_desactivables():
    marches = [MARCHES[0]]
    avant = ae.HANDICAP_ASIATIQUE_QUARTS
    try:
        ae.HANDICAP_ASIATIQUE_QUARTS = False
        assert ae._evaluer_marches_brut(marches, 1.6, 1.1) == []
    finally:
        ae.HANDICAP_ASIATIQUE_QUARTS = avant


def test_aucun_handicap_d_equipe_ni_de_statistique_n_est_confondu_avec_l_asian_handicap():
    """Corners / cartons / fautes / tirs / hors-jeux : leur « Asian Handicap » ne passe jamais par la branche des buts (elle garde sa catégorie dédiée, calcul inchangé)."""
    marches = [{"marche": "Corners - Asian Handicap", "handicap": -1, "periode": "fulltime", "selections": [{"selection": "1", "cote": 1.9}, {"selection": "2", "cote": 1.9}]}]
    sans_stats = ae._evaluer_marches_brut(marches, 1.6, 1.1)
    assert sans_stats == []                                   # sans mu de corners : aucun candidat (jamais évalué avec les buts)
    avec_stats = ae._evaluer_marches_brut(marches, 1.6, 1.1, mu_corners_equipes=(5.6, 4.4))
    assert {c["categorie"] for c in avec_stats} == {"Handicap Corners"}
    marches_eh = [{"marche": "Corners - European Handicap", "handicap": -1, "periode": "fulltime", "selections": [{"selection": "1", "cote": 2.0}, {"selection": "X", "cote": 3.4}, {"selection": "2", "cote": 2.7}]}]
    eh_stats = ae._evaluer_marches_brut(marches_eh, 1.6, 1.1, mu_corners_equipes=(5.6, 4.4))
    assert "European Handicap" not in {c["categorie"] for c in eh_stats}                         # jamais traité comme l'EH des buts (branche des statistiques, inchangée)


def test_les_marches_non_handicap_ne_changent_pas():
    marches = [{"marche": "Over Under Full Time", "handicap": 2.5, "periode": "fulltime", "selections": [{"selection": "Over", "cote": 1.9}, {"selection": "Under", "cote": 1.9}]}]
    cands = ae._evaluer_marches_brut(marches, 1.6, 1.1)
    assert {c["categorie"] for c in cands} == {"Total"} and all("cote_juste" not in c for c in cands)


def test_european_handicap_appartient_a_la_famille_handicap_et_a_l_event_principal():
    import agent_strategie as st
    import agents_familles as af
    assert af.famille_de("European Handicap")[0] == "handicap"
    assert st._event_du_pari({"pick": {"categorie": "European Handicap"}}) == "jeu principal"


def test_libelles_europeens_en_francais():
    import formatage_tickets as ft
    pick = {"categorie": "European Handicap", "marche": "European Handicap (-1)", "marche_affichage": "European Handicap (-1)", "handicap": -1, "cote": 2.0}
    base = {"match": "Inter vs Como", "pick": pick}
    assert "Inter gagne avec handicap -1 (handicap européen)" in ft._libelle_pari_court({**base, "pick": {**pick, "selection": "1"}})
    assert "Match nul avec handicap -1 du domicile (handicap européen)" in ft._libelle_pari_court({**base, "pick": {**pick, "selection": "X"}})
    assert "Como gagne avec handicap +1 (handicap européen)" in ft._libelle_pari_court({**base, "pick": {**pick, "selection": "2"}})
    guide, onglet = ft.expliquer_marche("European Handicap", "X", -1)
    assert "NUL" in guide and onglet == "onglet European Handicap"
