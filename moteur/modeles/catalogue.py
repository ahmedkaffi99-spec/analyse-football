"""Catalogue des modèles et des lignes par défaut (données pures, sans logique).

Séparé du registre pour que chaque spécialiste puisse l'importer sans import circulaire."""

VERSION_MODELES = "1.0.0"
BUTS_DOM_DEFAUT, BUTS_EXT_DEFAUT = 1.45, 1.15  # compétition sans historique suffisant (< 30 matchs)
MIN_MATCHS_LIGUE = 30

LIGNES_DEFAUT = {
    "handicap": [-2.5, -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5],
    "buts_total": [0.5, 1.5, 2.5, 3.5, 4.5],
    "buts_equipe1": [0.5, 1.5, 2.5],
    "buts_equipe2": [0.5, 1.5, 2.5],
    "corners_total": [7.5, 8.5, 9.5, 10.5, 11.5, 12.5],
    "corners_equipe1": [3.5, 4.5, 5.5, 6.5],
    "corners_equipe2": [2.5, 3.5, 4.5, 5.5],
    "cartons_total": [2.5, 3.5, 4.5, 5.5],
    "cartons_equipe1": [0.5, 1.5, 2.5],
    "cartons_equipe2": [0.5, 1.5, 2.5],
    "tirs_total": [20.5, 22.5, 24.5, 26.5],
    "tirs_equipe1": [9.5, 11.5, 13.5],
    "tirs_equipe2": [7.5, 9.5, 11.5],
    "tirs_cadres_total": [6.5, 7.5, 8.5, 9.5],
    "tirs_cadres_equipe1": [2.5, 3.5, 4.5],
    "tirs_cadres_equipe2": [2.5, 3.5, 4.5],
    # Moyenne réelle mesurée (hist_matchs, matchs récents) : 23.1 fautes/match — lignes centrées
    # dessus, même logique que tirs_total ci-dessus (ordre de grandeur comparable).
    "fautes_total": [18.5, 20.5, 22.5, 24.5, 26.5],
    "fautes_equipe1": [8.5, 10.5, 12.5],
    "fautes_equipe2": [8.5, 10.5, 12.5],
}

MODELES = {
    1: ("resultat", ["resultat"]),
    2: ("double_chance", ["double_chance"]),
    3: ("handicap", ["dnb", "handicap"]),
    4: ("buts_total", ["buts_total"]),
    5: ("buts_equipe1", ["buts_equipe1"]),
    6: ("buts_equipe2", ["buts_equipe2"]),
    7: ("btts", ["btts"]),
    8: ("corners", ["corners_total", "corners_equipe1", "corners_equipe2"]),
    9: ("cartons", ["cartons_total", "cartons_equipe1", "cartons_equipe2"]),
    10: ("tirs", ["tirs_total", "tirs_equipe1", "tirs_equipe2",
                  "tirs_cadres_total", "tirs_cadres_equipe1", "tirs_cadres_equipe2"]),
    11: ("fautes", ["fautes_total", "fautes_equipe1", "fautes_equipe2"]),
}
MODELE_DU_MARCHE = {m: num for num, (_, liste) in MODELES.items() for m in liste}
SELECTIONS = {"resultat": ["1", "X", "2"], "double_chance": ["1X", "X2", "12"], "dnb": ["1", "2"],
              "handicap": ["1", "2"], "btts": ["oui", "non"]}
