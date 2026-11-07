"""Base commune des trois moteurs (profils de risque) et évaluation comparable. Tests locaux ; ils ne prouvent AUCUNE rentabilité prédictive."""
import math
import random

import pytest

from moteur import evaluation as ev
from moteur import profils_risque as pr


def jambe(match="M1", p=0.6, cote=1.7, categorie="Total", selection="Over", comp="L1"):
    return {"match": match, "competition": comp, "categorie": categorie, "selection": selection, "p": p, "cote": cote}


# ---------- règles communes ----------
def test_famille_et_sens():
    assert pr.famille("Total Corners") == "corners" and pr.famille("Total Cartons Équipe 1") == "cartons" and pr.famille("Total Tirs Cadrés") == "tirs"
    assert pr.famille("BTTS") == "btts" and pr.famille("Handicap Asiatique") == "handicap" and pr.famille("Double Chance") == "resultat"
    assert pr.famille("Total") == "buts" and pr.famille("???") == "autre"
    assert [pr.sens(x) for x in ("Over", "Under 2.5", "Yes", "Non", "1X")] == ["over", "under", "yes", "no", "autre"]


@pytest.mark.parametrize("p,cote", [(None, 1.5), (0.0, 1.5), (1.2, 1.5), (0.6, None), (0.6, 1.0), (0.6, 0.9), ("0.6", 1.5)])
def test_jambe_invalide_refusee_rien_n_est_invente(p, cote):
    assert pr.valider_jambe(jambe(p=p, cote=cote)) is not None


def test_jambe_valide_acceptee():
    assert pr.valider_jambe(jambe()) is None and pr.valider_jambe(jambe(p=1.0)) is None


def test_diversite_limite_la_meme_famille_et_le_meme_sens():
    assert pr.diversite_ok([jambe(str(i)) for i in range(2)])                          # 2 jambes : toujours accepté
    assert not pr.diversite_ok([jambe(str(i)) for i in range(4)])                      # 4 « Over buts » : 4 > 2
    assert pr.diversite_ok([jambe("1"), jambe("2"), jambe("3", selection="Under"), jambe("4", categorie="BTTS", selection="Yes")])


def test_correlation_paires_meme_competition_famille_sens():
    a, b, c = jambe("1"), jambe("2"), jambe("3", comp="L2")
    assert pr.nb_paires_correlees([a, b]) == 1 and pr.nb_paires_correlees([a, c]) == 0
    assert pr.proba_jointe([a, b]) == pytest.approx(0.36 * (1 - pr.CORRELATION_PAIRE))
    assert pr.proba_jointe([a, b], corriger_correlation=False) == pytest.approx(0.36)
    assert pr.proba_jointe([]) == 0.0 and pr.cote_totale([a, b]) == pytest.approx(2.89)


def test_utilites_par_profil_ordonnent_differemment():
    sure, valeur, folle = jambe("a", p=0.9, cote=1.15), jambe("b", p=0.6, cote=1.9), jambe("c", p=0.2, cote=4.5)
    classement = {n: max((sure, valeur, folle), key=lambda j: pr.utilite_jambe(n, j))["match"] for n in pr.NIVEAUX}
    assert classement == {"prudent": "a", "equilibre": "b", "risque": "c"}
    with pytest.raises(ValueError):
        pr.utilite_jambe("inconnu", sure)


def test_utilite_coupon_fait_varier_la_taille_selon_le_profil():
    j = [jambe(str(i), p=0.75, cote=1.3, categorie=c, selection=s) for i, (c, s) in enumerate(
        [("Total", "Over"), ("BTTS", "Yes"), ("Total Corners", "Under"), ("Double Chance", "1X"), ("Total Cartons", "Over")])]
    assert pr.utilite_coupon("prudent", j[:2]) > pr.utilite_coupon("prudent", j[:5])   # prudent : peu de jambes
    assert pr.utilite_coupon("risque", j[:5]) > pr.utilite_coupon("risque", j[:2])     # risque : davantage de jambes (gain visé)
    assert pr.utilite_coupon("prudent", []) == float("-inf")


def test_regles_coupon():
    assert pr.regles_coupon([jambe("1", categorie="BTTS", selection="Yes"), jambe("2", categorie="Total", selection="Under")]) == []
    assert any("minimum 2" in x for x in pr.regles_coupon([jambe()]))
    assert any("même match" in x for x in pr.regles_coupon([jambe("1"), jambe("1", categorie="BTTS", selection="Yes")]))
    assert any("probabilité" in x for x in pr.regles_coupon([jambe("1"), jambe("2", p=None)]))
    faible = [jambe("1", p=0.1, cote=5, categorie="BTTS", selection="Yes"), jambe("2", p=0.1, cote=5, categorie="Total", selection="Under")]
    assert pr.regles_coupon(faible, "prudent") == []                                   # aucun plancher pour prudent
    assert any("plancher de sécurité" in x for x in pr.regles_coupon(faible, "risque"))   # 0,01 < 0,02 pour risque


def test_regles_entre_coupons():
    a = [jambe("1"), jambe("2", categorie="BTTS", selection="Yes")]
    assert pr.regles_entre_coupons([a, [jambe("3"), jambe("4", categorie="BTTS", selection="Yes")]]) == []
    assert any("deux coupons" in x for x in pr.regles_entre_coupons([a, [jambe("1"), jambe("5")]]))
    assert any("identiques" in x for x in pr.regles_entre_coupons([a, list(a)]))


# ---------- évaluation ----------
def obs(i, p=0.7, issue=1, cote=1.5, p_marche=0.65, jour="2026-11-01", marche="buts"):
    return {"cle": ("m", i), "p": p, "issue": issue, "cote": cote, "p_marche": p_marche, "jour": jour, "marche": marche}


def test_les_observations_non_reglees_sont_exclues_pas_comptees_perdues():
    liste = [obs(1), obs(2, issue=None), obs(3, p=None), obs(4, cote=1.0)]
    m = ev.metriques(liste)
    assert (m["n_total"], m["n_regle"], m["n_exclu"]) == (4, 1, 3) and m["taux_reussite"] == 1.0


def test_metriques_vides():
    m = ev.metriques([])
    assert m["brier"] is None and m["roi"] is None and m["n_regle"] == 0


def test_brier_log_loss_roi_valeurs_connues():
    liste = [obs(1, p=0.8, issue=1, cote=2.0), obs(2, p=0.8, issue=0, cote=2.0)]
    m = ev.metriques(liste)
    assert m["brier"] == pytest.approx(((0.2) ** 2 + 0.8 ** 2) / 2, abs=1e-5)
    assert m["log_loss"] == pytest.approx(-(math.log(0.8) + math.log(0.2)) / 2, abs=1e-4)
    assert m["roi"] == 0.0 and m["ecart_calibration"] == pytest.approx(-0.3)


def test_face_au_marche():
    meilleur = [obs(i, p=0.9 if i % 2 else 0.1, issue=i % 2, p_marche=0.6 if i % 2 else 0.4) for i in range(40)]
    r = ev.face_au_marche(meilleur)
    assert r["bat_le_marche"] is True and r["gain_brier"] > 0 and r["significatif"] is False
    assert ev.face_au_marche([obs(1, p_marche=None)])["bat_le_marche"] is None


def test_comparaison_sur_les_memes_paris_seulement():
    a = [obs(i) for i in range(10)]
    b = [obs(i) for i in range(5)] + [obs(i + 100) for i in range(5)]
    r = ev.comparer_moteurs({"central": a, "determ": b})
    assert r["n_communs"] == 5
    assert r["moteurs"]["central"]["global"]["n_regle"] == 5 and r["moteurs"]["determ"]["global"]["n_regle"] == 5   # même échantillon des deux côtés
    assert r["moteurs"]["central"]["toutes_observations"]["n_regle"] == 10                                         # le total propre est conservé à part


def test_aucun_classement_sous_le_seuil_et_classement_indicatif_au_dessus():
    petit = ev.comparer_moteurs({"a": [obs(i) for i in range(20)], "b": [obs(i) for i in range(20)]})
    assert petit["classement_autorise"] is False and "AUCUN CLASSEMENT" in petit["verdict"] and "classement_brier" not in petit
    rnd = random.Random(1)
    gros = {"a": [obs(i, p=0.7, issue=int(rnd.random() < 0.7)) for i in range(150)], "b": [obs(i, p=0.5, issue=int(rnd.random() < 0.7)) for i in range(150)]}
    gros["b"] = [dict(o, issue=g["issue"]) for o, g in zip(gros["b"], gros["a"])]
    r = ev.comparer_moteurs(gros)
    assert r["classement_autorise"] is True and r["classement_brier"][0][0] == "a" and "indicatif" in r["verdict"]


def test_forces_et_faiblesses_automatiques():
    optimiste = [obs(i, p=0.9, issue=0, p_marche=0.5, cote=1.2) for i in range(40)]
    r = ev.comparer_moteurs({"x": optimiste, "y": optimiste})["moteurs"]["x"]["forces_faiblesses"]
    assert any("trop optimiste" in f for f in r["faiblesses"]) and any("moins bon que le marché" in f for f in r["faiblesses"])
    assert ev.forces_faiblesses({"global": {"n_regle": 3}, "face_au_marche": {"n": 0}, "par_marche": {}})["faiblesses"][0].startswith("échantillon insuffisant")
    juste = [obs(i, p=0.7, issue=1 if i % 10 < 7 else 0, p_marche=0.6) for i in range(100)]
    f = ev.comparer_moteurs({"a": juste, "b": juste})["moteurs"]["a"]["forces_faiblesses"]
    assert any("calibration correcte" in x for x in f["forces"]) and any("meilleur que le marché" in x for x in f["forces"])


def test_par_marche_signale_les_echantillons_insuffisants():
    liste = [obs(i, marche="buts") for i in range(40)] + [obs(100 + i, marche="corners") for i in range(5)]
    pm = ev.par_marche(liste)
    assert pm["buts"]["suffisant"] is True and pm["corners"]["suffisant"] is False


def test_backtest_chronologique_hors_echantillon():
    rnd = random.Random(7)
    donnees = []
    for i in range(600):
        vrai = rnd.choice([0.3, 0.5, 0.7])
        donnees.append(obs(i, p=min(0.95, vrai + 0.2), issue=int(rnd.random() < vrai), jour=f"2026-10-{1 + i // 30:02d}"))   # moteur trop optimiste de 0,2
    r = ev.backtest_chronologique(donnees)
    assert r["disponible"] and r["n_app"] == 300 and r["n_test"] == 300
    assert r["brier_calibre"] < r["brier_brut"] and r["calibration_utile"] is True
    assert r["jours_test"][0] >= "2026-10-10"                                          # le test vient APRÈS l'apprentissage
    assert ev.backtest_chronologique(donnees[:50])["disponible"] is False


def test_pas_de_fuite_entre_apprentissage_et_test():
    donnees = [obs(i, p=0.6, issue=int(i % 2), jour=f"2026-10-{1 + i // 20:02d}") for i in range(400)]
    desordre = list(reversed(donnees))
    assert ev.backtest_chronologique(donnees)["jours_test"] == ev.backtest_chronologique(desordre)["jours_test"]   # tri chronologique, indépendant de l'ordre d'entrée


def test_stabilite_par_jour():
    s = ev.stabilite_par_jour([obs(1, jour="2026-11-01"), obs(2, jour="2026-11-01", issue=0), obs(3, jour="2026-11-02"), obs(4, issue=None, jour="2026-11-03")])
    assert list(s) == ["2026-11-01", "2026-11-02"] and s["2026-11-01"]["n"] == 2 and s["2026-11-01"]["taux"] == 0.5
