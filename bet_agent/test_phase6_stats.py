import phase2_modeles as pm
import phase6_stats_vs_marche as p6


def test_colonnes_et_jugement():
    assert p6.colonnes_fd("Total Tirs Cadrés Équipe 1") == ("HST", "AST") and p6.colonnes_fd("Total Tirs") == ("HS", "AS")
    assert p6.colonnes_fd("Handicap Corners") == ("HC", "AC") and p6.colonnes_fd("Total Hors-jeux") is None
    pick = {"categorie": "Total Corners", "handicap": 9.5, "selection": "Over"}
    assert p6.juger(pick, {"HC": 6, "AC": 5}) == "gagne" and p6.juger(pick, {"HC": 4, "AC": 5}) == "perdu"
    assert p6.juger(pick, {}) is None and p6.juger(pick, None) is None


def test_probabilite_nb_over_under_complementaires():
    f = pm.ForceEquipes({"A": 5.0, "B": 4.0}, {"A": 1.0, "B": 1.0}, 1.1, 4.5, 0.0, 30.0)
    over = p6.p_selection_nb(f, 30, "A", "B", {"handicap": 9.5, "selection": "Over"})
    under = p6.p_selection_nb(f, 30, "A", "B", {"handicap": 9.5, "selection": "Under"})
    assert 0 < over < 1 and abs(over + under - 1) < 1e-9
    assert p6.p_selection_nb(f, 30, "A", "B", {"handicap": None, "selection": "Over"}) is None
    assert p6.p_selection_nb(f, 30, "A", "B", {"handicap": 9.0, "selection": "Over"}) + p6.p_selection_nb(f, 30, "A", "B", {"handicap": 9.0, "selection": "Under"}) < 1   # push possible
