"""Tests du moteur central (métriques, choix du meilleur moteur, score central, sélection
adaptative 2-5, mode shadow) — données FABRIQUÉES ici volontairement (comme dans
moteur/tests/*) pour vérifier la LOGIQUE, jamais pour produire un backtest réel : aucune de ces
lignes n'est injectée dans hist_cotes ni présentée comme un résultat de production."""

from moteur_central.agent35_central import proposer_alternative_ia, verifier_coherence
from moteur_central.choix_moteur import comparer, choisir_par_marche
from moteur_central.metriques import calculer_metriques
from moteur_central.score_central import CandidatCentral, score_central
from moteur_central.selection import selectionner
from moteur_central.shadow import calculer_shadow, construire_pool_central


def _ligne(proba_pct, cote, resultat, marche="buts_total", competition="Ligue Test", jour="2026-01-01"):
    return {"proba_pct": proba_pct, "cote": cote, "resultat": resultat, "marche": marche,
            "competition": competition, "jour": jour}


def _lignes_gagnantes(n, proba_pct=70.0, cote=1.6, marche="buts_total", jour_base="2026-01"):
    return [_ligne(proba_pct, cote, "gagne", marche, jour=f"{jour_base}-{(i % 27) + 1:02d}") for i in range(n)]


def _lignes_perdantes(n, proba_pct=70.0, cote=1.6, marche="buts_total", jour_base="2026-01"):
    return [_ligne(proba_pct, cote, "perdu", marche, jour=f"{jour_base}-{(i % 27) + 1:02d}") for i in range(n)]


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def test_metriques_indisponibles_sous_le_seuil_minimal():
    m = calculer_metriques(_lignes_gagnantes(5), n_min=8)
    assert m["disponible"] is False
    assert m["n"] == 5


def test_metriques_disponibles_au_dessus_du_seuil_et_roi_correct():
    lignes = _lignes_gagnantes(10, proba_pct=60.0, cote=2.0)
    m = calculer_metriques(lignes, n_min=8)
    assert m["disponible"] is True
    assert m["win_rate"] == 1.0
    assert m["roi"] == 1.0  # cote 2.0, toujours gagnant -> +100%
    assert m["brier"] is not None and m["log_loss"] is not None


def test_metriques_ignorent_les_lignes_non_verifiables():
    lignes = _lignes_gagnantes(8) + [_ligne(70.0, 1.6, "non_verifiable"), _ligne(70.0, 1.6, None)]
    m = calculer_metriques(lignes, n_min=8)
    assert m["n"] == 8  # les 2 non jugées ne comptent pas


# ---------------------------------------------------------------------------
# Choix du meilleur moteur (jamais sur le seul win rate, validation temporelle)
# ---------------------------------------------------------------------------

def test_comparer_insuffisant_si_historique_trop_petit():
    r = comparer(_lignes_gagnantes(5), _lignes_gagnantes(5), n_min=30)
    assert r["decision"] == "indisponible"


def test_comparer_choisit_bet_agent_quand_roi_nettement_meilleur():
    # bet_agent : ROI élevé et stable. moteur : ROI nettement inférieur.
    ba = _lignes_gagnantes(40, proba_pct=65.0, cote=1.9)
    mo = _lignes_perdantes(30, proba_pct=65.0, cote=1.9) + _lignes_gagnantes(10, proba_pct=65.0, cote=1.9)
    r = comparer(ba, mo, n_min=30)
    assert r["decision"] == "bet_agent"
    assert r["metriques_bet_agent"]["roi"] > r["metriques_moteur"]["roi"]


def test_comparer_choisit_moteur_quand_roi_nettement_meilleur():
    ba = _lignes_perdantes(30, proba_pct=65.0, cote=1.9) + _lignes_gagnantes(10, proba_pct=65.0, cote=1.9)
    mo = _lignes_gagnantes(40, proba_pct=65.0, cote=1.9)
    r = comparer(ba, mo, n_min=30)
    assert r["decision"] == "moteur"


def test_comparer_egalite_quand_roi_quasi_identiques():
    ba = _lignes_gagnantes(20, cote=1.5) + _lignes_perdantes(20, cote=1.5)
    mo = _lignes_gagnantes(20, cote=1.5) + _lignes_perdantes(20, cote=1.5)
    r = comparer(ba, mo, n_min=30)
    assert r["decision"] == "egalite"


def test_comparer_jamais_sur_le_seul_win_rate():
    # bet_agent : win rate élevé mais sur une cote si basse que le ROI réel est négatif.
    ba = _lignes_gagnantes(35, proba_pct=90.0, cote=1.05) + _lignes_perdantes(5, proba_pct=90.0, cote=1.05)
    # moteur : win rate plus faible mais cote généreuse -> ROI positif malgré moins de gagnants.
    mo = _lignes_gagnantes(20, proba_pct=55.0, cote=2.5) + _lignes_perdantes(20, proba_pct=55.0, cote=2.5)
    r = comparer(ba, mo, n_min=30)
    roi_ba, roi_mo = r["metriques_bet_agent"]["roi"], r["metriques_moteur"]["roi"]
    # Le win rate de bet_agent (87.5%) est supérieur à celui du moteur (50%), mais la décision
    # doit suivre le ROI, pas le win rate.
    assert r["decision"] == ("moteur" if roi_mo > roi_ba else "bet_agent")
    assert r["metriques_bet_agent"]["win_rate"] > r["metriques_moteur"]["win_rate"]


def test_comparer_detecte_une_decision_instable_dans_le_temps():
    # 1re moitié (janvier) : bet_agent largement meilleur. 2nde moitié (février) : inversé.
    ba = ([_ligne(70, 1.9, "gagne", jour=f"2026-01-{i:02d}") for i in range(1, 21)]
          + [_ligne(70, 1.9, "perdu", jour=f"2026-02-{i:02d}") for i in range(1, 21)])
    mo = ([_ligne(70, 1.9, "perdu", jour=f"2026-01-{i:02d}") for i in range(1, 21)]
          + [_ligne(70, 1.9, "gagne", jour=f"2026-02-{i:02d}") for i in range(1, 21)])
    r = comparer(ba, mo, n_min=20)
    assert r["stable"] is False


def test_choisir_par_marche_couvre_les_marches_des_deux_moteurs():
    choix = choisir_par_marche(
        {"buts_total": _lignes_gagnantes(35, cote=1.9)},
        {"btts": _lignes_gagnantes(35, cote=1.9)},
        n_min=30)
    assert set(choix) == {"buts_total", "btts"}
    assert choix["buts_total"]["decision"] == "indisponible"  # pas d'historique moteur sur ce marché
    assert choix["btts"]["decision"] == "indisponible"  # pas d'historique bet_agent sur ce marché


# ---------------------------------------------------------------------------
# Score central : seuls les indicateurs disponibles sont utilisés
# ---------------------------------------------------------------------------

def test_score_central_sans_aucun_historique_ni_edge():
    c = CandidatCentral(match="A vs B", marche="buts_total", selection="Over", cote=1.9,
                        moteur_responsable="bet_agent", proba_pct=60.0)
    score, detail = score_central(c)
    assert 0 <= score <= 1
    cles = [d[0] for d in detail]
    assert "edge_pct" in cles and "historique_marche" in cles
    assert dict(detail)["edge_pct"] == "indisponible"


def test_score_central_utilise_la_probabilite_calibree_si_fournie():
    c_brute = CandidatCentral(match="A vs B", marche="buts_total", selection="Over", cote=1.9,
                              moteur_responsable="moteur", proba_pct=55.0)
    c_calibree = CandidatCentral(match="A vs B", marche="buts_total", selection="Over", cote=1.9,
                                 moteur_responsable="moteur", proba_pct=55.0, proba_calibree_pct=70.0)
    assert score_central(c_calibree)[0] > score_central(c_brute)[0]


def test_score_central_integre_lhistorique_seulement_sil_est_disponible():
    hist_ok = calculer_metriques(_lignes_gagnantes(30, proba_pct=65.0, cote=1.8), n_min=8)
    hist_insuffisant = calculer_metriques(_lignes_gagnantes(3), n_min=8)
    base = dict(match="A vs B", marche="buts_total", selection="Over", cote=1.9,
               moteur_responsable="bet_agent", proba_pct=60.0)
    c_avec = CandidatCentral(**base, historique_marche=hist_ok)
    c_sans = CandidatCentral(**base, historique_marche=hist_insuffisant)
    assert score_central(c_avec)[0] != score_central(c_sans)[0]
    assert dict(score_central(c_sans)[1])["historique_marche"] == "indisponible (échantillon insuffisant)"


# ---------------------------------------------------------------------------
# Sélection adaptative 2-5, diversité (= corrélation intra-match interdite)
# ---------------------------------------------------------------------------

def _candidat(match, cote, proba_pct=65.0, marche="buts_total", selection="Over"):
    return CandidatCentral(match=match, marche=marche, selection=selection, cote=cote,
                           moteur_responsable="bet_agent", proba_pct=proba_pct)


def test_selection_aucun_candidat_fiable():
    r = selectionner([], cote_min=1.3, cote_max=2.5)
    assert r["genere"] is False
    assert "0" in r["raison"] or "minimum" in r["raison"]


def test_selection_jamais_force_a_5_jambes_si_2_sont_meilleures():
    # 2 candidats premium (score élevé) donnent déjà une cote dans la cible ; les autres
    # candidats disponibles sont médiocres (score faible) et dégraderaient le combo.
    pool = [
        _candidat("A vs B", cote=1.3, proba_pct=85.0),
        _candidat("C vs D", cote=1.3, proba_pct=85.0),
        _candidat("E vs F", cote=1.05, proba_pct=20.0),
        _candidat("G vs H", cote=1.05, proba_pct=20.0),
        _candidat("I vs J", cote=1.05, proba_pct=20.0),
    ]
    r = selectionner(pool, cote_min=1.5, cote_max=1.9, nb_min=2, nb_max=5)
    assert r["genere"] is True
    assert r["nb_jambes"] == 2  # pas 5 : le combo à 2 jambes est dans la cible ET meilleur en score


def test_selection_une_seule_jambe_par_match_diversite_et_correlation():
    pool = [
        _candidat("A vs B", cote=1.5, proba_pct=80.0, marche="buts_total", selection="Over"),
        _candidat("A vs B", cote=1.6, proba_pct=78.0, marche="btts", selection="Oui"),  # même match !
        _candidat("C vs D", cote=1.5, proba_pct=75.0),
    ]
    r = selectionner(pool, cote_min=2.0, cote_max=2.6, nb_min=2, nb_max=2)
    assert r["genere"] is True
    matchs = {j.match for j in r["jambes"]}
    assert len(matchs) == len(r["jambes"])  # jamais deux jambes du même match


def test_selection_respecte_la_cote_cible_quand_possible():
    pool = [_candidat(f"M{i} vs X{i}", cote=1.5, proba_pct=70.0) for i in range(4)]
    r = selectionner(pool, cote_min=2.0, cote_max=2.4, nb_min=2, nb_max=4)
    assert r["genere"] is True
    assert 2.0 <= r["cote_totale"] <= 2.4


# ---------------------------------------------------------------------------
# Agent 3.5 central : jamais de remplacement arbitraire
# ---------------------------------------------------------------------------

def test_agent35_central_verifie_la_coherence_structurelle():
    pool = [_candidat("A vs B", 1.5), _candidat("C vs D", 1.5)]
    combo = pool  # cohérent
    assert verifier_coherence(combo, pool) == []
    combo_incoherent = [_candidat("Z vs Y", 1.5)]  # absent du pool
    assert verifier_coherence(combo_incoherent, pool) != []


def test_agent35_central_refuse_un_candidat_hors_pool():
    pool = [_candidat("A vs B", 1.5, proba_pct=70.0)]
    combo = [pool[0]]
    proposition = {"ancien": ("A vs B", "buts_total", "Over"), "nouveau": ("Z vs Y", "buts_total", "Over")}
    combo_final, appliquee, raison = proposer_alternative_ia(combo, pool, proposition)
    assert appliquee is False
    assert combo_final == combo


def test_agent35_central_refuse_une_degradation_du_score():
    bon = _candidat("A vs B", 1.5, proba_pct=80.0, marche="buts_total", selection="Over")
    moins_bon = _candidat("A vs B", 1.5, proba_pct=20.0, marche="btts", selection="Oui")
    pool = [bon, moins_bon]
    combo = [bon]
    proposition = {"ancien": ("A vs B", "buts_total", "Over"), "nouveau": ("A vs B", "btts", "Oui")}
    combo_final, appliquee, raison = proposer_alternative_ia(combo, pool, proposition)
    assert appliquee is False
    assert combo_final == combo  # jamais appliqué : le remplacement dégraderait le score moyen


def test_agent35_central_accepte_une_amelioration_du_score():
    ancien = _candidat("A vs B", 1.5, proba_pct=60.0, marche="buts_total", selection="Over")
    nouveau = _candidat("A vs B", 1.5, proba_pct=90.0, marche="btts", selection="Oui")
    pool = [ancien, nouveau]
    combo = [ancien]
    proposition = {"ancien": ("A vs B", "buts_total", "Over"), "nouveau": ("A vs B", "btts", "Oui")}
    combo_final, appliquee, raison = proposer_alternative_ia(combo, pool, proposition)
    assert appliquee is True
    assert combo_final == [nouveau]


# ---------------------------------------------------------------------------
# Mode shadow : jamais utilisé pour modifier quoi que ce soit en dehors de lui-même
# ---------------------------------------------------------------------------

def test_shadow_pool_central_garde_les_deux_moteurs_si_egalite_ou_indisponible():
    cand_mo = _candidat("A vs B", 1.5, marche="buts_total")
    cand_mo.moteur_responsable = "moteur"
    cand_ba = _candidat("C vs D", 1.5, marche="btts")
    cand_ba.moteur_responsable = "bet_agent"
    choix = {"buts_total": {"decision": "egalite"}, "btts": {"decision": "indisponible"}}
    pool = construire_pool_central([cand_mo], [cand_ba], choix)
    assert cand_mo in pool and cand_ba in pool


def test_shadow_pool_central_exclut_le_moteur_perdant_quand_la_decision_est_tranchee():
    cand_mo = _candidat("A vs B", 1.5, marche="buts_total")
    cand_mo.moteur_responsable = "moteur"
    cand_ba = _candidat("A vs B", 1.5, marche="buts_total")
    cand_ba.moteur_responsable = "bet_agent"
    choix = {"buts_total": {"decision": "bet_agent"}}
    pool = construire_pool_central([cand_mo], [cand_ba], choix)
    assert cand_ba in pool and cand_mo not in pool


def test_shadow_calculer_shadow_renvoie_les_3_coupons_independants():
    pool_mo = [_candidat(f"M{i} vs X{i}", 1.6, marche="buts_total") for i in range(3)]
    for c in pool_mo:
        c.moteur_responsable = "moteur"
    pool_ba = [_candidat(f"M{i} vs X{i}", 1.6, marche="buts_total") for i in range(3)]
    for c in pool_ba:
        c.moteur_responsable = "bet_agent"
    resultat = calculer_shadow(pool_mo, pool_ba, {}, cote_min=2.0, cote_max=3.0)
    assert set(resultat) == {"bet_agent", "moteur", "central", "pool_central_taille"}
    # Mode shadow : ce résultat est purement informatif, aucune clé "telegram"/"envoye" ici.
    assert "telegram" not in resultat and "envoye" not in resultat
