import json

import pytest

import agent_strategie as st
import agents_familles as af
import analyser_et_envoyer as ae


def _cand(match, categorie, selection, cote, proba, edge, marche="M"):
    return {"match": match, "pick": {"categorie": categorie, "marche": marche, "marche_affichage": marche,
                                      "selection": selection, "cote": cote, "proba_modele_pct": proba,
                                      "edge_pct": edge, "handicap": None}}


def _pool():
    return {
        "A vs B": [_cand("A vs B", "Double Chance", "1X", 1.8, 76.0, 8.0),
                   _cand("A vs B", "Double Chance", "12", 1.3, 77.0, 3.0),
                   _cand("A vs B", "Total", "Over", 1.7, 74.0, 6.0)],
        "C vs D": [_cand("C vs D", "Total Corners", "Under", 1.9, 72.0, 25.0),
                   _cand("C vs D", "Score Exact Bizarre", "1-0", 6.0, 71.0, 5.0)],
    }


@pytest.fixture(autouse=True)
def agents_actifs(monkeypatch):
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "1")


def test_onze_agents_dix_familles_plus_derives():
    assert len(af.FAMILLES) == 10
    ids = {f[0] for f in af.FAMILLES} | {af.FAMILLE_DERIVES[0]}
    assert len(ids) == 11
    assert {"fautes", "hors_jeux"} <= ids


def test_fautes_et_hors_jeux_sont_deux_familles_distinctes():
    for cat in ("Total Fautes", "Handicap Fautes", "Total Fautes Équipe 1", "Total Fautes Équipe 2"):
        assert af.famille_de(cat)[0] == "fautes"
    for cat in ("Total Hors-jeux", "Handicap Hors-jeux", "Total Hors-jeux Équipe 1", "Total Hors-jeux Équipe 2"):
        assert af.famille_de(cat)[0] == "hors_jeux"
    assert af.famille_de("Total Hors-jeux")[1] == "Hors-jeux" and af.famille_de("Total Fautes")[1] == "Fautes"


def test_chaque_categorie_modelisee_appartient_a_une_seule_famille():
    vues = {}
    for fid, _, cats, _ in af.FAMILLES:
        for c in cats:
            assert c not in vues, f"{c} dans {vues[c]} et {fid}"
            vues[c] = fid


def test_famille_de_categorie_connue_et_inconnue():
    assert af.famille_de("Double Chance")[0] == "resultat"
    assert af.famille_de("Total Corners")[0] == "corners"
    assert af.famille_de("Total Tirs")[0] == "tirs"
    assert af.famille_de("Score Exact Bizarre")[0] == "derives"


def test_veto_python_edge_suspect():
    assert af.veto_python({"categorie": "Total", "edge_pct": 25.0}) is not None
    assert af.veto_python({"categorie": "Total", "edge_pct": 20.0}) is None
    assert af.veto_python({"categorie": "Total", "edge_pct": None}) is None


def test_veto_python_categorie_exclue():
    assert "Handicap Corners" in ae.CATEGORIES_EXCLUES
    assert af.veto_python({"categorie": "Handicap Corners", "edge_pct": 1.0}) is not None
    # Total Tirs réintégré le 22/10/2026 (bug de troncature corrigé) : plus de veto de catégorie
    assert af.veto_python({"categorie": "Total Tirs", "edge_pct": 1.0}) is None


def test_categories_modelisees_ont_leur_famille():
    """Audit du 22/10 : ces catégories modélisées tombaient à tort dans « dérivés »."""
    assert af.famille_de("Draw No Bet")[0] == "resultat"
    assert af.famille_de("Clean Sheet Équipe 1")[0] == "buts_equipe"
    assert af.famille_de("Handicap Tirs Cadrés")[0] == "tirs"


def test_une_famille_d_un_seul_candidat_n_est_jamais_videe(monkeypatch):
    catalogue, _ = st.construire_catalogue({"A vs B": [_cand("A vs B", "Double Chance", "1X", 1.8, 76.0, 8.0)]})
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    id_dc = next(i for i, c in catalogue.items() if c["pick"]["categorie"] == "Double Chance")
    appel = lambda prompt, max_tokens=0, json_attendu=False: json.dumps(
        {"ecartes": [{"id": id_dc, "raison": "x"}], "avis": []})
    ecartes, _ = af.revoir_catalogue(catalogue, appel=appel)
    assert id_dc not in ecartes


def test_revoir_catalogue_veto_python_sans_ia(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool())
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: True)
    ecartes, avis = af.revoir_catalogue(catalogue, appel=lambda *a, **k: pytest.fail("IA appelée"))
    ids_corners = [i for i, c in catalogue.items() if c["pick"]["categorie"] == "Total Corners"]
    assert set(ids_corners) == ecartes
    assert "edge suspect" in avis[ids_corners[0]]


def test_revoir_catalogue_ia_ecarte_un_pari_valide(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool())
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    id_dc = next(i for i, c in catalogue.items() if c["pick"]["categorie"] == "Double Chance")
    id_total = next(i for i, c in catalogue.items() if c["pick"]["categorie"] == "Total")

    def appel(prompt, max_tokens=0, json_attendu=False):
        if "Résultat 1X2" in prompt:
            return json.dumps({"ecartes": [{"id": id_dc, "raison": "1X surestimé"}], "avis": []})
        return json.dumps({"ecartes": [], "avis": [{"id": id_total, "note": "RAS"}]})

    ecartes, avis = af.revoir_catalogue(catalogue, appel=appel)
    assert id_dc in ecartes and "1X surestimé" in avis[id_dc]
    assert id_total not in ecartes and "RAS" in avis[id_total]


def test_ia_ne_peut_ecarter_que_des_ids_du_catalogue_et_moitie_max(monkeypatch):
    pool = {f"M{i} vs X{i}": [_cand(f"M{i} vs X{i}", "Total", "Over", 1.7, 74.0, 6.0)] for i in range(4)}
    catalogue, _ = st.construire_catalogue(pool)
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    tous = list(catalogue)

    def appel(prompt, max_tokens=0, json_attendu=False):
        return json.dumps({"ecartes": [{"id": i, "raison": "x"} for i in tous] + [{"id": "P999", "raison": "x"}]})

    ecartes, _ = af.revoir_catalogue(catalogue, appel=appel)
    assert len(ecartes) == 2 and ecartes <= set(tous)


def test_reponse_ia_invalide_laisse_la_famille_inchangee(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool())
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    ecartes, _ = af.revoir_catalogue(catalogue, appel=lambda *a, **k: "pas du json")
    ids_corners = {i for i, c in catalogue.items() if c["pick"]["categorie"] == "Total Corners"}
    assert ecartes == ids_corners


def test_catalogue_ids_stables_et_pari_ecarte_masque():
    pool = _pool()
    complet, _ = st.construire_catalogue(pool)
    cid = next(iter(complet))
    reduit, texte = st.construire_catalogue(pool, ecartes={cid}, avis={"P2": "note test"})
    assert cid not in reduit and set(reduit) == set(complet) - {cid}
    assert reduit[next(iter(reduit))] is complet[next(iter(reduit))]
    assert "note test" in texte


def test_composer_coupons_appelle_les_agents_puis_le_stratege(monkeypatch):
    pool = {f"M{i} vs X{i}": [_cand(f"M{i} vs X{i}", "Total", "Over", 1.7, 74.0, 6.0)] for i in range(3)}
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    prompts = []

    def appel(prompt, max_tokens=0, json_attendu=False):
        prompts.append(prompt)
        if "agent spécialiste" in prompt:
            return json.dumps({"ecartes": [], "avis": []})
        return json.dumps({"analyse_matchs": [], "coupons": [
            {"profil": "p", "strategie": "s", "jambes": [{"id": "P1", "raison": "r"}, {"id": "P2", "raison": "r"}]}]})

    profils = [{"cle": "p", "nom": "P", "cote_min": 1.0, "cote_max": 99.0, "nb_jambes_min": 2, "nb_jambes": 2}]
    st.composer_coupons(pool, profils, appel=appel)
    assert any("agent spécialiste" in p for p in prompts)
    assert any("MISSION : composer" in p for p in prompts)


def test_desactivable_par_variable(monkeypatch):
    monkeypatch.setenv("AGENTS_FAMILLES_ACTIFS", "0")
    assert af.actif() is False


def test_les_agents_travaillent_en_parallele(monkeypatch):
    import threading
    import time
    pool = {
        "A vs B": [_cand("A vs B", "Double Chance", "1X", 1.8, 76.0, 8.0)],
        "C vs D": [_cand("C vs D", "Total", "Over", 1.7, 74.0, 6.0)],
        "E vs F": [_cand("E vs F", "Total Corners", "Under", 1.9, 72.0, 5.0)],
        "G vs H": [_cand("G vs H", "BTTS", "Yes", 1.9, 71.0, 5.0)],
    }
    catalogue, _ = st.construire_catalogue(pool)
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    barriere = threading.Barrier(4, timeout=5)  # les 4 agents doivent être EN VOL en même temps
    fils, passes = set(), []

    def appel(prompt, max_tokens=0, json_attendu=False):
        fils.add(threading.current_thread().name)
        barriere.wait()
        passes.append(1)
        time.sleep(0.05)
        return json.dumps({"ecartes": [], "avis": []})

    af.revoir_catalogue(catalogue, appel=appel)
    assert len(fils) == 4 and len(passes) == 4  # sans parallélisme, la barrière casserait


def _sel(match, categorie, selection="Under", cote=1.5):
    return {"match": match, "pick": {"categorie": categorie, "marche": "M", "marche_affichage": "M",
                                      "selection": selection, "cote": cote, "proba_modele_pct": 80.0,
                                      "edge_pct": 1.0, "handicap": 2.5}}


def test_famille_dominante_signalee_quand_une_alternative_existe():
    # 10 jambes dont 5 en "buts par équipe" (Total Équipe 1 x4 + Total Équipe 2 x1) : chaque
    # catégorie reste <= 40 % séparément, mais la FAMILLE vaut 50 % (> 40 %).
    selections = [_sel(f"M{i} vs X{i}", "Total Équipe 1") for i in range(4)]
    selections.append(_sel("M4 vs X4", "Total Équipe 2"))
    selections += [_sel(f"M{i} vs X{i}", "Total") for i in range(5, 10)]
    catalogue = {f"P{i}": s for i, s in enumerate(selections)}
    catalogue["PALT"] = _sel("M0 vs X0", "Double Chance", "1X")  # alternative d'une autre famille
    assert st._categories_dominantes(selections, catalogue) == []
    erreurs = st._familles_dominantes(selections, catalogue)
    assert len(erreurs) == 1 and "buts par équipe" in erreurs[0].lower()


def test_famille_dominante_sans_alternative_ne_bloque_pas():
    selections = [_sel(f"M{i} vs X{i}", "Total Équipe 1") for i in range(4)]
    selections += [_sel(f"N{i} vs Y{i}", "Total") for i in range(2)]
    catalogue = {f"P{i}": s for i, s in enumerate(selections)}  # aucune autre famille disponible
    assert st._familles_dominantes(selections, catalogue) == []


def test_coupon_equilibre_entre_familles_accepte():
    selections = [_sel("A vs B", "Total"), _sel("C vs D", "Total Équipe 1"), _sel("E vs F", "Total Corners"),
                  _sel("G vs H", "Double Chance", "1X"), _sel("I vs J", "BTTS", "Yes")]
    catalogue = {f"P{i}": s for i, s in enumerate(selections)}
    assert st._familles_dominantes(selections, catalogue) == []


# ------------------------------------------------------------------ profil « toutes les familles » + plafond de cote
def _pool_familles():
    return {
        "A vs B": [_cand("A vs B", "Double Chance", "12", 1.3, 80.0, 3.0), _cand("A vs B", "Total", "Over", 1.5, 76.0, 4.0)],
        "C vs D": [_cand("C vs D", "Total Corners", "Over", 1.6, 74.0, 5.0)],
        "E vs F": [_cand("E vs F", "BTTS", "Yes", 1.7, 72.0, 4.0), _cand("E vs F", "Total Cartons", "Under", 1.4, 78.0, 2.0)],
    }


def _valider(ids, profil):
    catalogue, _ = st.construire_catalogue(_pool_familles())
    par_cat = {c["pick"]["categorie"]: cid for cid, c in catalogue.items()}
    proposition = {"coupons": [{"profil": "p", "strategie": "s",
                                "jambes": [{"id": par_cat[c], "raison": "ok"} for c in ids]}]}
    return st.valider(proposition, catalogue, [dict({"cle": "p", "nom": "P", "nb_jambes": 8, "nb_jambes_min": 2,
                                                       "cote_totale_min": 1.0}, **profil)])


def test_familles_couvrables_limitees_par_le_nombre_de_matchs():
    catalogue, _ = st.construire_catalogue(_pool_familles())
    assert len(st.familles_du_catalogue(catalogue)) == 5  # résultat, buts total, corners, BTTS, cartons
    assert st._nb_familles_couvrables(catalogue) == 3      # mais 3 matchs, un pari par match


def test_familles_obligatoires_refuse_un_coupon_qui_couvre_moins_que_le_maximum_faisable():
    acceptes, problemes, _ = _valider(["Double Chance", "Total Corners"], {"familles_obligatoires": True})
    assert not acceptes and "il en faut au moins 3" in problemes[0]


def test_familles_obligatoires_accepte_le_maximum_faisable():
    acceptes, problemes, _ = _valider(["Double Chance", "Total Corners", "BTTS"], {"familles_obligatoires": True})
    assert "p" in acceptes, problemes


def test_sans_le_drapeau_une_famille_absente_reste_permise():
    acceptes, _, _ = _valider(["Double Chance", "Total Corners"], {})
    assert "p" in acceptes


def test_plafond_de_cote_totale():
    # 1.3 * 1.6 * 1.7 = 3.54
    acceptes, problemes, _ = _valider(["Double Chance", "Total Corners", "BTTS"], {"cote_totale_max": 3.0})
    assert not acceptes and "trop haute" in problemes[0]
    acceptes, _, _ = _valider(["Double Chance", "Total Corners", "BTTS"], {"cote_totale_max": 4.0})
    assert "p" in acceptes


def test_nouvelles_categories_par_equipe_ont_leur_famille():
    assert af.famille_de("Total Corners Équipe 1")[0] == "corners"
    assert af.famille_de("Total Fautes Équipe 2")[0] == "fautes"
    assert af.famille_de("Total Hors-jeux Équipe 1")[0] == "hors_jeux"
    assert af.famille_de("Total Tirs Cadrés Équipe 2")[0] == "tirs"


def test_revoir_catalogue_lance_un_agent_par_famille_fautes_et_hors_jeux(monkeypatch):
    pool = {
        "A vs B": [_cand("A vs B", "Total Fautes", "Under", 1.5, 74.0, 3.0),
                   _cand("A vs B", "Total Fautes Équipe 1", "Under", 1.4, 75.0, 2.0)],
        "C vs D": [_cand("C vs D", "Total Hors-jeux", "Under", 1.4, 76.0, 2.0),
                   _cand("C vs D", "Total Hors-jeux Équipe 2", "Over", 1.6, 72.0, 2.0)],
    }
    catalogue, _ = st.construire_catalogue(pool)
    monkeypatch.setattr(ae, "budget_ia_epuise", lambda: False)
    prompts = []

    def appel(prompt, max_tokens=0, json_attendu=False):
        prompts.append(prompt)
        return json.dumps({"ecartes": [], "avis": []})

    af.revoir_catalogue(catalogue, appel=appel)
    assert len(prompts) == 2
    assert sum("agent spécialiste « Fautes »" in p for p in prompts) == 1
    assert sum("agent spécialiste « Hors-jeux »" in p for p in prompts) == 1
    # les candidats d'un agent ne fuient pas dans le prompt de l'autre
    p_fautes = next(p for p in prompts if "« Fautes »" in p)
    assert "Hors-jeux" not in p_fautes.split("CANDIDATS :")[1]


# ------------------------------------------------------------------ 22/10/2026 : match répété + tous les matchs dans chaque coupon
def _valider_deux(ids1, ids2, extra1=None, extra2=None, pool_supplementaire=None):
    pool = _pool_familles()
    for match, candidats in (pool_supplementaire or {}).items():
        pool[match] = pool[match] + candidats
    catalogue, _ = st.construire_catalogue(pool)
    par_cat = {c["pick"]["categorie"]: cid for cid, c in catalogue.items()}
    base = {"nom": "P", "nb_jambes": 8, "nb_jambes_min": 2, "cote_totale_min": 1.0}
    proposition = {"coupons": [
        {"profil": "p1", "strategie": "s", "jambes": [{"id": par_cat[c], "raison": "ok"} for c in ids1]},
        {"profil": "p2", "strategie": "s", "jambes": [{"id": par_cat[c], "raison": "ok"} for c in ids2]}]}
    return st.valider(proposition, catalogue, [dict(base, cle="p1", **(extra1 or {})), dict(base, cle="p2", **(extra2 or {}))])


def test_match_deja_pris_refuse_par_defaut():
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total Corners"], ["Total Corners", "BTTS"])
    assert "p1" in acceptes and "p2" not in acceptes and "déjà utilisé" in problemes[0]


def test_match_repete_autorise_mais_jamais_le_meme_pari_exact():
    permis = {"match_repete_autorise": True}
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total Corners"], ["Total", "BTTS"], permis, permis)
    assert set(acceptes) == {"p1", "p2"}, problemes   # A–B repris avec un autre marché : accepté
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total Corners"], ["Total", "Total Corners"], permis, permis)
    assert "p2" not in acceptes and "même pari exact" in problemes[0]


def test_tous_les_matchs_obligatoires_et_max_deux_paris_par_match():
    regles = {"match_repete_autorise": True, "tous_les_matchs_obligatoires": True, "jambes_max_par_match": 2}
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total", "Total Corners", "BTTS"], ["Total Cartons"],
                                            regles, {"nb_jambes_min": 1})
    assert "p1" in acceptes, problemes                           # 3 matchs présents, 2 paris sur A–B permis
    # Coupon 2 : les 3 mêmes matchs, avec d'AUTRES paris (C–D reçoit un 2e pari, un Handicap)
    en_plus = {"C vs D": [_cand("C vs D", "Handicap", "1", 1.5, 70.0, 2.0)]}
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total Corners", "BTTS"],
                                            ["Total", "Handicap", "Total Cartons"], regles, regles, en_plus)
    assert set(acceptes) == {"p1", "p2"}, problemes
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total Corners"], ["Double Chance"], regles, regles)
    assert "p1" not in acceptes and "matchs absents" in problemes[0] and "E vs F" in problemes[0]


def test_un_seul_pari_par_match_reste_la_regle_par_defaut():
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total"], ["Total Corners"])
    assert "p1" not in acceptes and "maximum 1" in problemes[0]


def test_un_seul_pari_par_event_regle_1xbet():
    # Captures du coupon réel du 23/10/2026 : Total + Handicap du même match refusés (même event) ;
    # double chance + corners acceptés (events distincts).
    regles = {"match_repete_autorise": True, "jambes_max_par_match": 6, "un_seul_pari_par_event": True}
    # A–B : Double Chance + Total = deux paris du jeu principal -> refusé
    acceptes, problemes, _ = _valider_deux(["Double Chance", "Total", "Total Corners"], ["Total Corners"], regles, None)
    assert "p1" not in acceptes and "même event « jeu principal » sur A vs B" in problemes[0]
    # E–F : BTTS (jeu principal) + Cartons (event distinct) -> accepté
    acceptes, problemes, _ = _valider_deux(["Double Chance", "BTTS", "Total Cartons"], ["Total Corners"], regles, None)
    assert "p1" in acceptes, problemes
    # Deux paris de corners sur le même match = même event -> refusé
    pool = {"C vs D": [_cand("C vs D", "Total Corners Équipe 1", "Over", 1.5, 72.0, 2.0)]}
    acceptes, problemes, _ = _valider_deux(["Total Corners", "Total Corners Équipe 1", "BTTS"], ["Double Chance"],
                                            regles, None, pool)
    assert "p1" not in acceptes and "même event « corners » sur C vs D" in problemes[0]


def test_diversification_entre_coupons_meme_risque_toute_ligne():
    # 23/10/2026 : « Malaga corners plus de 2.5 » puis « plus de 3 » = le même risque, trois coupons perdus d'un coup.
    div = {"match_repete_autorise": True, "diversifier_entre_coupons": True}
    pool = {"C vs D": [_cand("C vs D", "Total Corners Équipe 1", "Over", 1.5, 72.0, 2.0)]}
    # p1 prend « Total Corners » (C–D), p2 reprend la même catégorie/sens sur C–D avec une autre ligne : refus
    catalogue, _ = st.construire_catalogue({**_pool_familles(), **{"C vs D": _pool_familles()["C vs D"] + [
        _cand("C vs D", "Total Corners", "Over", 1.4, 75.0, 2.0, marche="M2")]}})
    ids = {}
    for cid, c in catalogue.items():
        ids.setdefault((c["match"], c["pick"]["categorie"], c["pick"]["marche"]), cid)
    base = {"nom": "P", "nb_jambes": 8, "nb_jambes_min": 1, "cote_totale_min": 1.0, **div}
    proposition = {"coupons": [
        {"profil": "p1", "strategie": "s", "jambes": [{"id": ids[("C vs D", "Total Corners", "M")], "raison": "ok"}]},
        {"profil": "p2", "strategie": "s", "jambes": [{"id": ids[("C vs D", "Total Corners", "M2")], "raison": "ok"}]}]}
    acceptes, problemes, _ = st.valider(proposition, catalogue, [dict(base, cle="p1"), dict(base, cle="p2")])
    assert "p1" in acceptes and "p2" not in acceptes and "même risque" in problemes[0]


def test_un_seul_pari_resultat_par_match_sur_l_ensemble_des_coupons():
    div = {"match_repete_autorise": True, "diversifier_entre_coupons": True, "nb_jambes_min": 1}
    acceptes, problemes, _ = _valider_deux(["Double Chance"], ["Total"], div, div)
    assert set(acceptes) == {"p1", "p2"}, problemes      # résultat puis un autre marché sur A–B : permis
    pool = {"A vs B": [_cand("A vs B", "Draw No Bet", "1", 1.4, 74.0, 2.0)]}
    acceptes, problemes, _ = _valider_deux(["Double Chance"], ["Draw No Bet"], div, div, pool)
    assert "p2" not in acceptes and "même risque" in problemes[0]   # deuxième pari « résultat » sur A–B : refusé


def test_probabilite_minimale_par_profil_et_seuil_du_catalogue():
    # 24/10/2026 : le coupon « très risqué » accepte des jambes moins probables, les autres gardent leur minimum.
    profils = [{"cle": "p1", "proba_min_pct": 70.0}, {"cle": "p3", "proba_min_pct": 55.0}]
    assert st.seuil_catalogue(profils) == 55.0
    assert st.seuil_catalogue([]) == st.SEUIL_PROBA_CATALOGUE
    pool = {"A vs B": [_cand("A vs B", "Total", "Over", 1.8, 60.0, 2.0), _cand("A vs B", "BTTS", "Yes", 1.4, 75.0, 2.0)]}
    catalogue, _ = st.construire_catalogue(pool, seuil_proba=55.0)
    par_cat = {c["pick"]["categorie"]: cid for cid, c in catalogue.items()}
    assert "Total" in par_cat                                   # visible grâce au seuil abaissé
    base = {"nom": "P", "nb_jambes": 8, "nb_jambes_min": 1, "cote_totale_min": 1.0}
    prop = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": par_cat["Total"], "raison": "ok"}]},
                        {"profil": "p3", "strategie": "s", "jambes": [{"id": par_cat["Total"], "raison": "ok"}]}]}
    acceptes, problemes, _ = st.valider(prop, catalogue, [dict(base, cle="p1", proba_min_pct=70.0),
                                                         dict(base, cle="p3", proba_min_pct=55.0)])
    assert "p3" in acceptes and "p1" not in acceptes and "trop basse pour CE profil" in problemes[0]


def test_dernier_coupon_doit_couvrir_tous_les_matchs_restants():
    # 24/10/2026 : obligation de couvrir tous les matchs sur l'ensemble des coupons (le dernier complète).
    catalogue, _ = st.construire_catalogue(_pool_familles())
    par = {}
    for cid, c in catalogue.items():
        par.setdefault(c["match"], []).append(cid)
    base = {"nom": "P", "nb_jambes": 8, "nb_jambes_min": 1, "cote_totale_min": 1.0, "couvrir_tous_les_matchs": True,
            "dernier_profil": True}
    # Coupon précédent (verrouillé) : A–B ; ce dernier coupon ne prend que C–D -> E–F reste non couvert -> refusé
    precedent = [dict(catalogue[par["A vs B"][0]], pick=dict(catalogue[par["A vs B"][0]]["pick"]))]
    prop = {"coupons": [{"profil": "p", "strategie": "s", "jambes": [{"id": par["C vs D"][0], "raison": "ok"}]}]}
    acceptes, problemes, _ = st.valider(prop, catalogue, [dict(base, cle="p")], selections_precedentes=precedent)
    assert not acceptes and "E vs F" in problemes[0] and "couvrir TOUS les matchs" in problemes[0]
    # Avec C–D et E–F dans ce dernier coupon : accepté
    prop = {"coupons": [{"profil": "p", "strategie": "s", "jambes": [
        {"id": par["C vs D"][0], "raison": "ok"}, {"id": par["E vs F"][0], "raison": "ok"}]}]}
    acceptes, problemes, _ = st.valider(prop, catalogue, [dict(base, cle="p")], selections_precedentes=precedent)
    assert "p" in acceptes, problemes
