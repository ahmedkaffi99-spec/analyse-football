"""Étude du 13/11/2026 (12 coupons perdus) : plafond de paris « moins de buts d'une équipe » par coupon et plafond « un même pari dans un seul coupon par jour, tous runs
confondus ». Tests locaux, sans réseau ni clé ; ils ne prouvent aucune rentabilité."""
import agent_strategie as st
import plafonds_coupon as pc
from moteur import profils_risque as pr


def _sel(match, categorie, selection, cote, handicap=2.5):
    return {"match": match, "home_nom": match.split(" vs ")[0], "away_nom": match.split(" vs ")[1],
            "fixture_id_oddspapi": match,
            "pick": {"categorie": categorie, "marche": f"{categorie} ({handicap})", "handicap": handicap, "selection": selection,
                     "cote": cote, "proba_modele_pct": 75.0, "edge_pct": 6.0, "guide": "g", "onglet": "o",
                     "proba_poisson_pct": 64.0, "proba_marche_pct": 58.0},
            "contexte": {"contexte_web": [], "elo": {}, "buts_attendus": {"domicile": 1.5, "exterieur": 1.0}}}


def _pool_under(n=6):
    return {f"A{i} vs B{i}": [_sel(f"A{i} vs B{i}", "Total Équipe 1", "Under", 1.3)] for i in range(n)}


PROFIL = {"cle": "p1", "nom": "x", "nb_jambes_min": 1, "nb_jambes": 8, "match_repete_autorise": False}


def test_est_under_equipe():
    assert pr.est_under_equipe("Total Équipe 1", "Under")
    assert pr.est_under_equipe("Total Équipe 2", "moins de 2.5")
    assert not pr.est_under_equipe("Total Équipe 1", "Over")
    assert not pr.est_under_equipe("Total", "Under")                       # total du match, pas d'une équipe
    assert not pr.est_under_equipe("Total Corners Équipe 1", "Under")      # corners : hors plafond
    assert not pr.est_under_equipe("Handicap Asiatique", "1")


def test_regles_communes_refusent_cinq_under_equipe_et_acceptent_quatre():
    def leg(i, cat, sel):
        return {"match": f"M{i}", "competition": f"L{i}", "categorie": cat, "selection": sel, "p": 0.8, "cote": 1.3}
    cinq = [leg(i, "Total Équipe 1", "Under") for i in range(5)]
    assert any("moins de buts d'une équipe" in x for x in pr.regles_coupon(cinq))
    quatre_et_autres = [leg(i, "Total Équipe 1", "Under") for i in range(4)] + [leg(4, "Handicap Asiatique", "1"), leg(5, "Double Chance", "1X"),
                                                                                leg(6, "BTTS", "Yes"), leg(7, "Total", "Over")]
    assert not any("moins de buts d'une équipe" in x for x in pr.regles_coupon(quatre_et_autres))
    assert not any("moins de buts d'une équipe" in x for x in pr.regles_coupon(cinq, profil={"max_under_equipe": 5}))   # un profil peut fixer son plafond


def test_valider_agent_refuse_plus_de_quatre_under_equipe(monkeypatch):
    catalogue, _ = st.construire_catalogue(_pool_under())
    cinq = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": f"P{i}"} for i in range(1, 6)]}]}
    acceptes, problemes, _ = st.valider(cinq, catalogue, [PROFIL])
    assert "p1" not in acceptes and any("moins de buts d'une équipe" in p for p in problemes), problemes
    quatre = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": f"P{i}"} for i in range(1, 5)]}]}
    _, problemes, _ = st.valider(quatre, catalogue, [PROFIL])
    assert not any("moins de buts d'une équipe" in p for p in problemes), problemes


def test_plafond_desactivable_par_variable(monkeypatch):
    monkeypatch.setattr(pr, "MAX_JAMBES_UNDER_EQUIPE", 0)
    catalogue, _ = st.construire_catalogue(_pool_under())
    six = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": f"P{i}"} for i in range(1, 7)]}]}
    _, problemes, _ = st.valider(six, catalogue, [PROFIL])
    assert not any("moins de buts d'une équipe" in p for p in problemes), problemes


def test_cle_pari_jour_ignore_le_libelle_du_marche_la_casse_et_le_format_de_la_ligne():
    a = pc.cle_pari_jour("Mali vs Rwanda", "Total Équipe 1", "Under", 2.0)
    assert a == pc.cle_pari_jour("Mali vs Rwanda", "Total Équipe 1", "under", 2)
    assert a != pc.cle_pari_jour("Mali vs Rwanda", "Total Équipe 1", "Under", 2.5)   # une autre ligne est un autre pari
    assert a != pc.cle_pari_jour("Mali vs Rwanda", "Total Équipe 1", "Over", 2.0)
    assert pc.cle_pari_jour("A vs B", "Handicap Asiatique", "1", None)[3] is None


def test_catalogue_retire_les_paris_deja_pris_par_un_autre_run_et_garde_les_identifiants():
    pool = {"A vs B": [_sel("A vs B", "Total", "Over", 1.6), _sel("A vs B", "BTTS", "Yes", 1.8)],
            "C vs D": [_sel("C vs D", "Total", "Under", 1.5)]}
    exclus = {pc.cle_pari_jour("A vs B", "BTTS", "Yes", 2.5)}
    catalogue, texte = st.construire_catalogue(pool, paris_exclus=exclus)
    assert list(catalogue) == ["P1", "P3"]          # P2 retiré, P3 garde son numéro
    assert "P2 :" not in texte


def test_valider_refuse_un_pari_deja_pris_par_un_autre_run():
    pool = {f"A{i} vs B{i}": [_sel(f"A{i} vs B{i}", "Total", "Over", 1.5)] for i in range(3)}
    catalogue, _ = st.construire_catalogue(pool)
    profil = dict(PROFIL, nb_jambes=3)
    proposition = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]}]}
    exclus = {pc.cle_pari_jour("A0 vs B0", "Total", "Over", 2.5)}
    acceptes, problemes, _ = st.valider(proposition, catalogue, [profil], paris_exclus=exclus)
    assert "p1" not in acceptes and any("autre run" in p for p in problemes), problemes
    acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])        # sans exclusion : accepté
    assert "p1" in acceptes, problemes


def test_plafond_actif_par_defaut_et_desactivable(monkeypatch):
    monkeypatch.delenv("PLAFOND_PARI_JOUR", raising=False)
    assert pc.plafond_actif()
    monkeypatch.setenv("PLAFOND_PARI_JOUR", "")        # variable de dépôt vide : actif
    assert pc.plafond_actif()
    monkeypatch.setenv("PLAFOND_PARI_JOUR", "0")
    assert not pc.plafond_actif()
