import vote


def _sel(match, marche, selection, cote, proba):
    return {"match": match, "pick": {"marche": marche, "selection": selection, "handicap": None, "cote": cote, "proba_modele_pct": proba}}


PROFILS = [{"cle": "coupon1", "nom": "C1"}, {"cle": "coupon2", "nom": "C2"}]


def test_garde_le_coupon_a_plus_forte_probabilite_combinee():
    pilote = [{"profil": PROFILS[0], "selections": [_sel("A", "T", "Over", 1.8, 60), _sel("B", "T", "Over", 1.8, 60)]},
              {"profil": PROFILS[1], "selections": [_sel("C", "T", "Over", 2.0, 50)]}]
    modele = {"modele": "m/x", "coupons": [
        {"profil": "coupon1", "dans_la_bande": True, "selections": [_sel("D", "T", "Under", 1.8, 70), _sel("E", "T", "Under", 1.8, 70)]},
        {"profil": "coupon2", "dans_la_bande": True, "selections": [_sel("F", "T", "Under", 2.0, 40)]}]}
    sortie, journal = vote.choisir(PROFILS, pilote, [modele])
    assert sortie[0]["selections"][0]["match"] == "D"     # 49 % > 36 %
    assert sortie[1]["selections"][0]["match"] == "C"     # 50 % > 40 %
    assert "coupon1 : m/x retenu" in journal[0] and "coupon2 : pilote retenu" in journal[1]


def test_hors_bande_ou_vide_ignore_et_egalite_pour_le_pilote():
    pilote = [{"profil": PROFILS[0], "selections": [_sel("A", "T", "Over", 1.8, 60)]}, {"profil": PROFILS[1], "selections": []}]
    modele = {"modele": "m/x", "coupons": [{"profil": "coupon1", "dans_la_bande": False, "selections": [_sel("D", "T", "Under", 1.8, 99)]},
                                           {"profil": "coupon2", "dans_la_bande": True, "selections": [_sel("F", "T", "Under", 2.0, 40)]}]}
    sortie, _ = vote.choisir(PROFILS, pilote, [modele])
    assert sortie[0]["selections"][0]["match"] == "A"
    assert sortie[1]["selections"][0]["match"] == "F"     # le pilote n'avait rien pour ce profil
    egal = {"modele": "m/y", "coupons": [{"profil": "coupon1", "dans_la_bande": True, "selections": [_sel("Z", "T", "Under", 1.8, 60)]}]}
    assert vote.choisir(PROFILS, pilote, [egal])[0][0]["selections"][0]["match"] == "A"


def test_un_meme_pari_n_est_jamais_dans_deux_coupons():
    commun = _sel("A", "T", "Over", 1.8, 80)
    pilote = [{"profil": PROFILS[0], "selections": [_sel("B", "T", "Over", 1.8, 50)]}, {"profil": PROFILS[1], "selections": [_sel("C", "T", "Over", 1.8, 50)]}]
    modele = {"modele": "m/x", "coupons": [{"profil": "coupon1", "dans_la_bande": True, "selections": [commun]},
                                           {"profil": "coupon2", "dans_la_bande": True, "selections": [commun]}]}
    sortie, _ = vote.choisir(PROFILS, pilote, [modele])
    assert sortie[0]["selections"] == [commun] and sortie[1]["selections"][0]["match"] == "C"


def test_modeles_vote_lit_l_environnement(monkeypatch):
    monkeypatch.setenv("MODELES_VOTE", "a/b, c/d")
    assert vote.modeles_vote() == ["a/b", "c/d"]
    monkeypatch.setenv("MODELES_VOTE", "aucun")
    assert vote.modeles_vote() == []
