"""Jeu de cas SYNTHÉTIQUES pour démontrer backtest_production.py de bout en bout — AUCUNE
donnée réelle (voir RAPPORT_DONNEES_REELLES dans backtest_production.py : aucune donnée réelle
hist_cotes/hist_matchs suffisante n'est disponible à ce jour pour backtester analyser_et_envoyer.py).
Les scores et cotes sont construits à la main pour couvrir un éventail plausible de résultats
(favoris nets, matchs serrés, surprises) sur les 5 marchés que grader_pick peut juger à partir du
score final (Total, BTTS, Double Chance, Draw No Bet, Handicap/Asian Handicap) — jamais présenté
comme une mesure réelle de performance."""

CHAMPIONNAT_PAR_INDICE = ["Championnat Synthétique A", "Championnat Synthétique B"]


def _marches(ligne_totale, cote_over, cote_under, cote_btts_oui, cote_btts_non,
             cote_1x, cote_x2, cote_12, cote_dnb_home, cote_dnb_away,
             ligne_hcap, cote_hcap_home, cote_hcap_away):
    return [
        {"marche_id": "1", "marche": "Over Under Full Time", "handicap": ligne_totale, "periode": "fulltime",
         "selections": [{"selection": "Over", "cote": cote_over}, {"selection": "Under", "cote": cote_under}]},
        {"marche_id": "2", "marche": "Both Teams To Score", "handicap": 0.0, "periode": "fulltime",
         "selections": [{"selection": "Yes", "cote": cote_btts_oui}, {"selection": "No", "cote": cote_btts_non}]},
        {"marche_id": "3", "marche": "Double Chance Full Time", "handicap": 0.0, "periode": "fulltime",
         "selections": [{"selection": "1X", "cote": cote_1x}, {"selection": "X2", "cote": cote_x2},
                        {"selection": "12", "cote": cote_12}]},
        {"marche_id": "4", "marche": "Draw No Bet", "handicap": 0.0, "periode": "fulltime",
         "selections": [{"selection": "Home", "cote": cote_dnb_home}, {"selection": "Away", "cote": cote_dnb_away}]},
        {"marche_id": "5", "marche": "Asian Handicap", "handicap": ligne_hcap, "periode": "fulltime",
         "selections": [{"selection": "Home", "cote": cote_hcap_home}, {"selection": "Away", "cote": cote_hcap_away}]},
    ]


# (marches, (buts_home, buts_away)) — 40 cas construits à la main, cotes plausibles
# (marge bookmaker ~5-7%), couvrant favoris nets / matchs serrés / surprises.
CAS_SYNTHETIQUES_DEMO = [
    # --- Favoris nets à domicile qui confirment (10 cas) ---
    (_marches(2.5, 1.55, 2.35, 1.45, 2.55, 1.25, 2.80, 1.60, 1.30, 3.20, -1.5, 1.70, 2.05), (3, 0)),
    (_marches(2.5, 1.65, 2.15, 1.60, 2.25, 1.30, 2.60, 1.65, 1.35, 3.00, -1.0, 1.75, 1.95), (2, 0)),
    (_marches(2.5, 1.45, 2.60, 1.35, 2.90, 1.20, 3.10, 1.55, 1.25, 3.50, -1.5, 1.65, 2.15), (4, 1)),
    (_marches(2.5, 1.60, 2.25, 1.50, 2.40, 1.35, 2.50, 1.70, 1.40, 2.85, -1.0, 1.80, 1.90), (2, 1)),
    (_marches(2.5, 1.50, 2.45, 1.40, 2.65, 1.25, 2.75, 1.60, 1.30, 3.10, -1.0, 1.65, 2.10), (3, 1)),
    (_marches(2.5, 1.90, 1.85, 1.75, 1.95, 1.30, 2.55, 1.65, 1.40, 2.80, -0.5, 1.85, 1.90), (1, 0)),
    (_marches(2.5, 1.70, 2.05, 1.65, 2.10, 1.28, 2.65, 1.62, 1.35, 3.00, -1.0, 1.72, 2.00), (2, 0)),
    (_marches(2.5, 1.35, 2.90, 1.30, 3.10, 1.18, 3.30, 1.50, 1.20, 3.80, -2.0, 1.60, 2.25), (5, 1)),
    (_marches(1.5, 2.00, 1.72, 2.00, 1.72, 1.32, 2.50, 1.68, 1.42, 2.70, -0.5, 1.90, 1.85), (1, 0)),
    (_marches(2.5, 1.58, 2.30, 1.48, 2.48, 1.33, 2.52, 1.69, 1.38, 2.90, -0.5, 1.82, 1.92), (2, 1)),
    # --- Favoris nets à domicile qui déçoivent (10 cas, surprises réelles) ---
    (_marches(2.5, 1.55, 2.35, 1.45, 2.55, 1.25, 2.80, 1.60, 1.30, 3.20, -1.5, 1.70, 2.05), (0, 1)),
    (_marches(2.5, 1.65, 2.15, 1.60, 2.25, 1.30, 2.60, 1.65, 1.35, 3.00, -1.0, 1.75, 1.95), (1, 1)),
    (_marches(2.5, 1.45, 2.60, 1.35, 2.90, 1.20, 3.10, 1.55, 1.25, 3.50, -1.5, 1.65, 2.15), (0, 0)),
    (_marches(2.5, 1.60, 2.25, 1.50, 2.40, 1.35, 2.50, 1.70, 1.40, 2.85, -1.0, 1.80, 1.90), (1, 2)),
    (_marches(2.5, 1.50, 2.45, 1.40, 2.65, 1.25, 2.75, 1.60, 1.30, 3.10, -1.0, 1.65, 2.10), (0, 2)),
    (_marches(2.5, 1.90, 1.85, 1.75, 1.95, 1.30, 2.55, 1.65, 1.40, 2.80, -0.5, 1.85, 1.90), (0, 0)),
    (_marches(2.5, 1.70, 2.05, 1.65, 2.10, 1.28, 2.65, 1.62, 1.35, 3.00, -1.0, 1.72, 2.00), (1, 1)),
    (_marches(2.5, 1.35, 2.90, 1.30, 3.10, 1.18, 3.30, 1.50, 1.20, 3.80, -2.0, 1.60, 2.25), (1, 2)),
    (_marches(1.5, 2.00, 1.72, 2.00, 1.72, 1.32, 2.50, 1.68, 1.42, 2.70, -0.5, 1.90, 1.85), (0, 1)),
    (_marches(2.5, 1.58, 2.30, 1.48, 2.48, 1.33, 2.52, 1.69, 1.38, 2.90, -0.5, 1.82, 1.92), (0, 0)),
    # --- Matchs serrés (sans gros favori), lignes de totaux centrées (10 cas) ---
    (_marches(2.5, 1.95, 1.82, 1.80, 1.98, 1.95, 1.95, 2.85, 1.90, 1.90, 0.0, 1.90, 1.90), (1, 1)),
    (_marches(2.5, 1.70, 2.05, 1.60, 2.20, 2.00, 1.90, 2.90, 1.95, 1.85, 0.0, 1.92, 1.88), (2, 2)),
    (_marches(2.5, 2.10, 1.68, 2.05, 1.72, 1.98, 1.92, 2.80, 1.88, 1.92, 0.0, 1.88, 1.92), (0, 0)),
    (_marches(2.5, 1.88, 1.90, 1.85, 1.92, 1.92, 1.98, 2.70, 1.85, 1.95, 0.0, 1.95, 1.85), (1, 0)),
    (_marches(2.5, 1.92, 1.86, 1.78, 2.00, 2.02, 1.88, 2.95, 1.98, 1.82, 0.0, 1.82, 1.98), (0, 1)),
    (_marches(2.5, 1.65, 2.10, 1.55, 2.30, 1.97, 1.93, 2.88, 1.93, 1.87, 0.0, 1.87, 1.93), (2, 1)),
    (_marches(2.5, 1.68, 2.08, 1.58, 2.25, 2.05, 1.85, 3.00, 2.00, 1.80, 0.0, 1.80, 2.00), (1, 2)),
    (_marches(3.5, 1.60, 2.20, 1.45, 2.55, 1.96, 1.94, 2.86, 1.91, 1.89, 0.0, 1.89, 1.91), (3, 2)),
    (_marches(2.5, 1.90, 1.88, 1.78, 1.96, 1.94, 1.96, 2.82, 1.89, 1.91, 0.0, 1.91, 1.89), (1, 1)),
    (_marches(2.5, 2.05, 1.70, 2.00, 1.76, 1.99, 1.91, 2.92, 1.94, 1.86, 0.0, 1.86, 1.94), (0, 0)),
    # --- Favoris extérieurs (Away favori, 10 cas) ---
    (_marches(2.5, 1.65, 2.15, 1.55, 2.30, 2.90, 1.25, 1.65, 3.10, 1.30, 1.5, 2.05, 1.70), (0, 2)),
    (_marches(2.5, 1.70, 2.05, 1.60, 2.20, 2.70, 1.30, 1.70, 2.95, 1.35, 1.0, 1.95, 1.75), (1, 2)),
    (_marches(2.5, 1.50, 2.45, 1.40, 2.65, 3.20, 1.20, 1.55, 3.50, 1.25, 1.5, 2.15, 1.65), (0, 3)),
    (_marches(2.5, 1.75, 2.00, 1.65, 2.15, 2.60, 1.33, 1.72, 2.85, 1.38, 1.0, 1.90, 1.80), (1, 1)),
    (_marches(2.5, 1.62, 2.18, 1.52, 2.35, 2.80, 1.28, 1.63, 3.05, 1.33, 1.0, 2.00, 1.72), (2, 2)),
    (_marches(2.5, 1.95, 1.85, 1.80, 1.95, 2.50, 1.35, 1.75, 2.75, 1.40, 0.5, 1.92, 1.82), (0, 1)),
    (_marches(2.5, 1.72, 2.02, 1.62, 2.18, 2.65, 1.32, 1.68, 2.90, 1.37, 1.0, 1.88, 1.78), (1, 0)),
    (_marches(3.5, 1.58, 2.25, 1.42, 2.60, 3.00, 1.22, 1.58, 3.30, 1.27, 1.5, 2.10, 1.68), (2, 3)),
    (_marches(2.5, 1.48, 2.60, 1.38, 2.70, 3.10, 1.20, 1.56, 3.40, 1.25, 1.5, 2.12, 1.66), (1, 3)),
    (_marches(2.5, 2.00, 1.75, 1.90, 1.90, 2.45, 1.38, 1.78, 2.65, 1.42, 0.5, 1.88, 1.86), (0, 0)),
]
