"""07/11/2026 — stratégie à TROIS profils de risque (prudent, équilibré, risque) : l'IA choisit librement, aucune cote totale cible ni cote individuelle
obligatoire ; les validations Python (catalogue, cohérence des coupons) restent. Tests locaux, sans réseau ni clé ; aucune preuve de rentabilité."""
import math

import agent_pilote as pilote
import agent_strategie as st
import ombre
import profils_smart
import vote


def _sel(match, cote, marche="1X2", selection="1", proba=60.0, cat="resultat"):
    return {"match": match, "pick": {"marche": marche, "selection": selection, "cote": cote, "categorie": cat, "proba_modele_pct": proba,
                                     "handicap": None, "edge_pct": 1.0}, "home_nom": match.split(" - ")[0], "fixture_id_oddspapi": match}


def _cat(cotes):
    return {f"P{i + 1}": _sel(f"M{i} - X{i}", c) for i, c in enumerate(cotes)}


def _prop(cle, ids):
    return {"coupons": [{"profil": cle, "strategie": "s", "jambes": [{"id": i, "raison": "ok"} for i in ids]}]}


# ---------- profils ----------
def test_trois_profils_dans_l_ordre_prudent_equilibre_risque():
    p = profils_smart.profils(contraintes=False)
    assert [x["niveau_risque"] for x in p] == ["prudent", "equilibre", "risque"]
    assert [x["cle"] for x in p] == ["coupon1", "coupon2", "coupon3"]          # clés historiques conservées (colonne coupons.profil)
    assert [x["nom"].split(" ", 1)[1] for x in p] == ["PRUDENT", "ÉQUILIBRÉ", "RISQUE"]
    assert len({x["consigne"] for x in p}) == 3


def test_aucune_cote_imposee_dans_les_profils():
    interdits = {"cote_min", "cote_max", "cote_totale_min", "cote_totale_max", "prefere_cote_elevee", "proba_min_pct", "proba_max_pct"}
    for profil in profils_smart.profils(contraintes=False):
        assert not interdits & set(profil)


def test_regles_de_coherence_conservees_dans_les_profils():
    for profil in profils_smart.profils(contraintes=False):
        assert profil["nb_jambes_min"] == 2 and profil["jambes_max_par_match"] == 1
        assert profil["un_seul_pari_par_event"] is True and profil["match_repete_autorise"] is False
    assert all(x["jambes_max_par_match"] == 3 for x in profils_smart.profils(un_pari_par_match=False))


# ---------- validations Python ----------
def test_cote_totale_tres_basse_ou_tres_haute_acceptee_sans_bande():
    profil = profils_smart.profils(contraintes=False)[2]
    basse, _, _ = st.valider(_prop("coupon3", ["P1", "P2"]), _cat([1.20, 1.20]), [profil])
    assert "coupon3" in basse                                                  # 1,44 : aucun plancher de cote TOTALE
    haute, _, _ = st.valider(_prop("coupon3", ["P1", "P2", "P3"]), _cat([20.0, 20.0, 20.0]), [profil])
    assert "coupon3" in haute                                                  # 8 000 : aucun plafond


def test_cotes_individuelles_trop_basses_refusees_meme_si_ia_les_choisit():
    profil = profils_smart.profils(contraintes=False)[0]
    acceptes, problemes, _ = st.valider(_prop("coupon1", ["P1", "P2"]), _cat([1.02, 1.50]), [profil])
    assert "coupon1" not in acceptes
    assert any("plancher technique 1.20" in p for p in problemes)


def test_catalogue_exclut_les_cotes_individuelles_inferieures_a_1_20():
    pool = {
        "M1 - X1": [_sel("M1 - X1", 1.02, proba=99.0),
                    _sel("M1 - X1", 1.35, marche="Total", selection="Under", proba=78.0)]
    }
    catalogue, texte = st.construire_catalogue(pool)
    assert len(catalogue) == 1
    assert next(iter(catalogue.values()))["pick"]["cote"] == 1.35
    assert "@ 1.02" not in texte


def test_les_validations_de_securite_restent_actives():
    profil = profils_smart.profils(contraintes=False)[0]
    cat = _cat([1.5, 1.5, 1.5])
    _, p, _ = st.valider(_prop("coupon1", ["P1", "P99"]), cat, [profil])
    assert any("identifiant inconnu" in x for x in p)                          # un pari hors catalogue est refusé
    _, p, _ = st.valider(_prop("coupon1", ["P1"]), cat, [profil])
    assert any("minimum 2" in x for x in p)                                    # deux jambes minimum
    _, p, _ = st.valider(_prop("coupon1", ["P1", "P1"]), cat, [profil])
    assert any("choisi deux fois" in x for x in p)                             # pas de doublon dans un coupon
    deja = [cat["P1"]]
    _, p, _ = st.valider(_prop("coupon1", ["P1", "P2"]), cat, [profil], selections_precedentes=deja)
    assert any("déjà utilisé" in x for x in p)                                 # un match ne figure que dans un coupon
    a, _, _ = st.valider(_prop("coupon1", ["P1", "P2"]), cat, [profil])
    s = a["coupon1"]["selections"][0]["pick"]
    assert s["cote"] == 1.5                                                    # la cote vient du catalogue


def test_deux_coupons_identiques_refuses():
    profils = profils_smart.profils(contraintes=False)[:2]
    cat = _cat([1.5, 1.5, 1.5, 1.5])
    deja = [st.signature([dict(cat["P1"]), dict(cat["P2"])])]
    _, p, _ = st.valider(_prop("coupon2", ["P1", "P2"]), cat, [profils[1]], signatures_existantes=deja)
    assert p                                                                   # même combinaison (ou match repris) : refusée


def test_profil_personnalise_garde_sa_bande_explicite():
    profil = {"cle": "p", "nom": "x", "nb_jambes_min": 1, "nb_jambes": 5, "cote_totale_min": 5.0, "cote_totale_max": 10.0}
    cat = _cat([2.0, 2.0, 2.0])
    ok, _, _ = st.valider(_prop("p", ["P1", "P2", "P3"]), cat, [profil])       # 8,0 : dans la bande
    assert "p" in ok
    _, trop_bas, _ = st.valider(_prop("p", ["P1", "P2"]), cat, [profil])       # 4,0
    assert any("trop basse" in x for x in trop_bas)
    _, trop_haut, _ = st.valider(_prop("p", ["P1", "P2", "P3"]), _cat([3.0, 3.0, 3.0]), [profil])   # 27
    assert any("trop haute" in x for x in trop_haut)


# ---------- vote par niveau de risque ----------
def _coupon(modele_cote_proba):
    return [{"match": f"M{i}", "pick": {"marche": "m", "selection": f"s{i}", "handicap": None, "cote": c, "proba_modele_pct": p}}
            for i, (c, p) in enumerate(modele_cote_proba)]


def test_le_vote_choisit_selon_le_niveau_de_risque():
    surs = _coupon([(1.2, 90), (1.2, 90)])           # proba 0,81 ; cote 1,44 ; valeur 1,17
    moyens = _coupon([(1.6, 70), (1.6, 70)])         # proba 0,49 ; cote 2,56 ; valeur 1,25
    fous = _coupon([(3.0, 30), (3.0, 30)])           # proba 0,09 ; cote 9,00 ; valeur 0,81
    resultats = [{"modele": "m", "coupons": []}]
    attendu = {"prudent": "surs", "equilibre": "moyens", "risque": "fous"}
    noms = {id(surs): "surs", id(moyens): "moyens", id(fous): "fous"}
    for niveau, voulu in attendu.items():
        profil = {"cle": "c", "niveau_risque": niveau}
        candidats = [("pilote", surs), ("a", moyens), ("b", fous)]
        choix = max(candidats, key=lambda ns: vote.score_vote(niveau, ns[1]))
        assert noms[id(choix[1])] == voulu, niveau
    assert resultats


def test_choisir_detail_applique_le_niveau_du_profil():
    profil = {"cle": "c", "niveau_risque": "risque"}
    pilote_res = [{"profil": profil, "selections": _coupon([(1.2, 90), (1.2, 90)])}]
    autre = [{"modele": "gpt", "coupons": [{"profil": "c", "dans_la_bande": True, "selections": _coupon([(3.0, 30), (3.0, 30)])}]}]
    # selections de matchs identiques (M0, M1) mais paris différents : match déjà pris ? profil sans match_repete_autorise -> un seul candidat libre
    profil["match_repete_autorise"] = True
    _, journal, gagnants = vote.choisir_detail([profil], pilote_res, autre)
    assert gagnants["c"] == "gpt" and "cote 9.0" in journal[0]
    profil_p = {"cle": "c", "niveau_risque": "prudent", "match_repete_autorise": True}
    assert vote.choisir_detail([profil_p], [{"profil": profil_p, "selections": pilote_res[0]["selections"]}], autre)[2]["c"] == "pilote"


def test_profil_sans_niveau_garde_le_choix_par_probabilite():
    assert vote.score_vote(None, _coupon([(1.2, 90)]))[0] == vote.proba_combinee(_coupon([(1.2, 90)]))
    assert vote.cote_combinee([]) == 0.0 and math.isclose(vote.cote_combinee(_coupon([(2.0, 50), (3.0, 50)])), 6.0)


def test_coupon_de_comparaison_valide_sans_bande():
    r = ombre._resume_coupon("coupon1", profils_smart.profils(contraintes=False)[0], [_sel("A - B", 2.0), _sel("C - D", 3.0)])
    assert r["dans_la_bande"] is True and r["cote_totale"] == 6.0               # aucune borne : valide dès qu'il y a une cote
    assert ombre._resume_coupon("coupon1", profils_smart.profils(contraintes=False)[0], [])["dans_la_bande"] is False
    borne = {"cle": "p", "cote_totale_min": 5.0, "cote_totale_max": 10.0}
    assert ombre._resume_coupon("p", borne, [_sel("A - B", 2.0)])["dans_la_bande"] is False       # une bande explicite reste vérifiée


# ---------- consignes données à l'IA ----------
def test_prompt_pilote_decrit_les_trois_profils_sans_cote_imposee():
    prompt = pilote.construire_prompt_systeme(profils_smart.profils(contraintes=False))
    assert "PRUDENT" in prompt and "ÉQUILIBRÉ" in prompt and "RISQUE" in prompt
    assert "TROIS PROFILS DE RISQUE" in prompt and "AUCUNE cote" in prompt
    assert "un match ne figure que dans UN seul coupon" in prompt
    assert "peut figurer dans plusieurs coupons" not in prompt                  # plus de contradiction avec la règle Python
    for ancien in ("SMART COUPON", "BANDE DE COTE TOTALE du profil", "cote_totale_min", "5-10", "20-35", "60 % par défaut"):
        assert ancien not in prompt, ancien


def test_prompt_des_modeles_du_vote_decrit_les_trois_profils():
    cat = {"P1": _sel("A - B", 1.5)}
    texte = st.construire_prompt({"A - B": [_sel("A - B", 1.5)]}, profils_smart.profils(contraintes=False), "\n- P1 : ...")
    assert "Profil PRUDENT" in texte and "Profil ÉQUILIBRÉ" in texte and "Profil RISQUE" in texte
    assert "AUCUNE cote totale cible" in texte
    assert "sans match commun" in texte and "UN seul coupon" in texte
    for ancien in ("BANDE DE COTE TOTALE", "plancher ET plafond", "tu peux reprendre un MATCH", "5-10"):
        assert ancien not in texte, ancien
    assert cat


def test_prompt_conserve_la_bande_d_un_profil_personnalise():
    perso = {"cle": "p", "nom": "P", "nb_jambes_min": 2, "nb_jambes": 4, "cote_totale_min": 5.0, "cote_totale_max": 10.0}
    texte = st.construire_prompt({"A - B": [_sel("A - B", 1.5)]}, [perso], "\n- P1 : ...")
    assert "BANDE DE COTE TOTALE (profil personnalisé) : 5 à 10" in texte


def test_voir_catalogue_n_annonce_aucune_cote_pour_les_profils_de_risque():
    assert "prefere_cote_elevee" not in pilote.construire_prompt_systeme(profils_smart.profils(contraintes=False))
    schemas = str(pilote.construire_outils_schemas(profils_smart.profils(contraintes=False)))
    assert "prefere_cote_elevee" not in schemas and "60%" not in schemas and "cote_totale_min" not in schemas
