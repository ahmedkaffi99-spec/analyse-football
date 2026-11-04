from datetime import datetime

import phase2_production as pp


def fd(dom="Man United", ext="Arsenal", ah=-0.5):
    return {"ligue": "E0", "date": datetime(2026, 11, 8), "dom": dom, "ext": ext,
            "ou_clo": {"O": 1.9, "U": 2.0}, "1x2_clo": {"1": 2.5, "X": 3.4, "2": 2.9},
            "ah": {"ouv": ah, "clo": ah}, "ah_clo": {"H": 1.95, "A": 1.95}}


def test_rapprochement_par_noms_et_date():
    r, s = pp.rapprocher("Manchester United", "Arsenal FC", "2026-11-08T15:00:00Z", [fd()])
    assert r is not None and s >= 80
    assert pp.rapprocher("Chelsea", "Liverpool", "2026-11-08T15:00:00Z", [fd()])[0] is None
    assert pp.rapprocher("Manchester United", "Arsenal", "2026-12-08T15:00:00Z", [fd()])[0] is None


def test_probas_pinnacle_par_marche():
    l = fd()
    over = pp.p_pinnacle({"categorie": "Total", "handicap": 2.5, "selection": "Over"}, l)
    under = pp.p_pinnacle({"categorie": "Total", "handicap": 2.5, "selection": "Under"}, l)
    assert abs(over + under - 1) < 1e-9
    assert pp.p_pinnacle({"categorie": "Total", "handicap": 3.5, "selection": "Over"}, l) is None
    h = pp.p_pinnacle({"categorie": "Handicap", "handicap": -0.5, "selection": "Home"}, l)
    assert abs(h - 0.5) < 1e-9
    assert pp.p_pinnacle({"categorie": "Handicap", "handicap": -1.5, "selection": "Home"}, l) is None   # ligne différente : jamais assimilée
    dc = pp.p_pinnacle({"categorie": "Double Chance", "handicap": None, "selection": "1X"}, l)
    assert 0.5 < dc < 0.9


def test_un_par_evenement_et_comparaison_sur_memes_evenements():
    bets = []
    for i in range(40):
        for sel in ("Over", "Under"):
            gagne = (i % 2 == 0) == (sel == "Over")
            bets.append({"match": i, "groupe": "T2.5", "selection": sel, "cote": 1.9, "issue": "gagne" if gagne else "perdu",
                         "categorie": "Total", "p_modele": 0.5, "p_marche": 0.5, "p_final": 0.5, "p_pin": 0.5, "date": i})
    ev = pp.un_par_evenement(bets)
    assert len(ev) == 40
    txt = "\n".join(pp.tableau_comparaison(ev, "test"))
    assert "40 événements communs" in txt and "Référence clôture (Pinnacle 1X2 ; Bet365 O/U-AH)" in txt and "aléatoire" in txt
