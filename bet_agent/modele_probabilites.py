"""Modèle probabiliste (extrait de analyser_et_envoyer.py, qui le ré-exporte à l'identique) :
buts attendus (xG) depuis les stats, corrections H2H/Elo/arbitre, lois de Poisson et binomiale
négative, probabilités par marché et edge. Calcul pur : aucun réseau, aucune IA, aucun Telegram."""
import math
import os
import sys

_RACINE_DEPOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RACINE_DEPOT not in sys.path:
    sys.path.append(_RACINE_DEPOT)
from moteur.modeles import lois as _lois, marches as _marches  # noqa: E402

NB_MATCHS_MIN_STATS = 5  # TheSportsDB fournit les 5 derniers matchs


def calculer_xg_depuis_stats(stats_home, stats_away):
    """Calcule mu_home/mu_away à partir des vraies stats historiques (buts marqués/encaissés,
    domicile/extérieur), quand les deux équipes en disposent. Méthode standard :
    mu_home = moyenne(buts marqués à domicile par l'équipe domicile, buts encaissés à
    l'extérieur par l'équipe extérieure) — et symétriquement pour mu_away."""
    if not stats_home or not stats_away:
        return None
    # Échantillon trop petit (ex. 3 matchs amicaux) : moyenne non fiable (constaté : Honduras
    # à 0.15 but attendu) — repli sur l'estimation depuis les cotes du marché.
    if min(stats_home.get("matchs_joues") or 0, stats_away.get("matchs_joues") or 0) < NB_MATCHS_MIN_STATS:
        return None
    bm_dom = stats_home.get("buts_marques_domicile")
    be_dom = stats_home.get("buts_encaisses_domicile")
    bm_ext = stats_away.get("buts_marques_exterieur")
    be_ext = stats_away.get("buts_encaisses_exterieur")
    if None in (bm_dom, be_dom, bm_ext, be_ext):
        return None
    try:
        mu_home = (float(bm_dom) + float(be_ext)) / 2
        mu_away = (float(bm_ext) + float(be_dom)) / 2
    except (TypeError, ValueError):
        return None
    return round(max(0.15, mu_home), 2), round(max(0.15, mu_away), 2)


# Lissage bayésien (shrinkage) d'une moyenne mesurée sur peu de matchs vers un prior neutre —
# demande explicite du 01/10/2026 ("améliore les calculs de Python et le modèle"). Jusqu'ici,
# une moyenne calculée sur SEULEMENT 3 matchs (NB_MATCHS_MIN_STATS_DETAILLEES, collecte_
# donnees.py — le minimum accepté) était utilisée avec EXACTEMENT la même confiance qu'une
# moyenne sur 10 : une équipe à 2 clean sheets sur ses 3 seuls matchs connus donnait un xG
# adverse artificiellement proche de 0, alors que l'échantillon est trop petit pour l'affirmer.
# Le commentaire de collecte_donnees.py le disait déjà ("sous ce seuil, la moyenne est trop
# bruitée pour être fiable") sans jamais agir dessus au-delà du rejet pur sous 3 matchs.
NB_MATCHS_PLEINE_CONFIANCE = 10  # = NB_DERNIERS_MATCHS_DETAILLES (collecte_donnees.py)

# Lissage additif ("matchs fictifs" vers le prior, 17/10/2026, demande explicite après
# investigation Handicap/BTTS) — remplace l'ancien lissage à ratio plafonné
# (poids_donnee = min(nb_matchs, 10)/10) qui atteignait PILE 100% de confiance dès 10 matchs —
# soit la quasi-totalité des cas réels, puisque 10 est précisément le nombre de matchs
# collectés par défaut (NB_MATCHS_PLEINE_CONFIANCE ci-dessus) : ÇA NE LISSAIT JAMAIS RIEN EN
# PRATIQUE. Même principe que moteur/config.py:shrinkage_buts (k matchs fictifs toujours
# présents, jamais 100% de confiance brute même avec l'échantillon complet) — valeur par
# défaut à valider par un vrai backtest (voir diagnostics.yml:backtest-k-lissage-buts),
# réversible par variable d'environnement comme le reste de la configuration du moteur.
K_LISSAGE_BUTS = float(os.getenv("BET_AGENT_K_LISSAGE_BUTS") or 5.0)

# Priors neutres (moyennes raisonnables, toutes ligues confondues) — un point de départ quand
# l'échantillon réel est trop petit pour parler fort, jamais une vérité universelle.
# Recalés le 21/10/2026 sur les moyennes MESURÉES par équipe (backtest sur 6 996 matchs, 5 championnats) :
# l'ancien prior (tirs 12, cadrés 4, fautes 11) tirait le mu vers le bas et sous-estimait les totaux de
# 2 à 3 % (biais mesuré : tirs -0.54, cadrés -0.29, fautes -0.56 par match). Hors-jeux : non collectés,
# prior inchangé faute de mesure.
BUTS_PRIOR = 1.335
CORNERS_PRIOR = 4.8
CARTONS_PRIOR = 2.1
FAUTES_PRIOR = 11.9
TIRS_PRIOR = 12.7
TIRS_CADRES_PRIOR = 4.4
HORS_JEUX_PRIOR = 1.7  # 22/10/2026 : moyenne observée par équipe 1.70 (backtest, 717 matchs PL + Liga) ; l'ancien 2.0 donnait mu +0.24


# AVANTAGE DU TERRAIN des comptages (22/10/2026). Le mu de chaque équipe est une moyenne de forme tous lieux
# confondus : il ne contenait AUCUN avantage du terrain, alors que l'historique (7 205 matchs, 5 championnats)
# montre domicile contre extérieur : corners 5.34/4.31, tirs 14.00/11.43, tirs cadrés 4.86/3.96, fautes
# 11.78/12.13, cartons jaunes 1.97/2.25. Le backtest des marchés absents l'a révélé : handicaps et totaux PAR
# ÉQUIPE de corners/tirs/cartons faux de 6 à 17 points (ex. handicap tirs +0.5 : annoncé 61 %, réel 67 % ;
# -4.5 : annoncé 78 %, réel 61 %). Facteur du domicile = moyenne domicile / moyenne des deux côtés ; celui de
# l'extérieur est son complément à 2, ce qui conserve le total.
# VALIDÉ par grille (22/10/2026, 7 000 matchs, Brier handicaps + totaux par équipe à 0 / 50 / 75 / 100 % de
# l'écart mesuré) : corners 0.2253 -> 0.2207, tirs 0.2261 -> 0.2181, tirs cadrés 0.2139 -> 0.2089, cartons
# 0.1974 -> 0.1965 ; l'échelle 100 % est la meilleure (75 % équivalent à 0.0001 près) ; fautes : écart
# négligeable (0.2260 -> 0.2256), facteur 0.985 conservé. Hors-jeux : aucun facteur (totaux par équipe déjà
# calibrés sans, domicile 1.78 / extérieur 1.63 sur 717 matchs).
FACTEUR_DOMICILE = {
    "corners": 1.107, "tirs": 1.101, "tirs_cadres": 1.103, "fautes": 0.985, "cartons": 0.934,
}


def appliquer_avantage_domicile(famille, mu_equipes):
    """(mu_dom, mu_ext) -> ajusté de l'avantage du terrain de la famille ; None inchangé. Hors-jeux : pas de
    facteur mesuré (statistique absente de l'historique), donc aucun ajustement."""
    f = FACTEUR_DOMICILE.get(famille)
    if not mu_equipes or f is None:
        return mu_equipes
    return round(max(0.15, mu_equipes[0] * f), 2), round(max(0.15, mu_equipes[1] * (2 - f)), 2)


def _lisser_vers_prior(valeur, nb_matchs, prior, k=K_LISSAGE_BUTS):
    """(valeur*nb_matchs + k*prior) / (nb_matchs+k) : lissage additif — k "matchs fictifs" au
    prior, toujours présents, jamais 100% de confiance brute même avec l'échantillon complet
    (voir K_LISSAGE_BUTS ci-dessus pour pourquoi l'ancien lissage à ratio plafonné ne lissait
    jamais rien en pratique). nb_matchs=None (vieux format sans métadonnée) : comportement
    inchangé, aucun lissage tenté plutôt que deviné."""
    if valeur is None or nb_matchs is None:
        return valeur
    return (valeur * nb_matchs + k * prior) / (nb_matchs + k)


# Les deux FORMES de calcul partagées par toutes les statistiques "VRAIES stats des 10
# derniers matchs" ci-dessous (buts/corners/cartons/fautes/tirs/hors-jeux) — demande explicite
# du 03/10/2026 ("simplifie et organise bien les calculs, car une seule erreur de calcul peut
# causer un résultat faux") : 6 fonctions quasi-identiques (même lissage, même garde-fou
# None/TypeError/ValueError, même arrondi final) ne laissaient qu'une différence réelle entre
# elles — attaque/défense (buts, corners, fautes) vs valeur directe (cartons, tirs, hors-jeux).
# Un bug dans cette arithmétique ne peut maintenant exister qu'à DEUX endroits (un par forme)
# au lieu de six, et se corrige donc une seule fois pour toutes les statistiques concernées.
def _mu_attaque_defense(sd_home, sd_away, champ_pour, champ_contre, prior):
    """(mu_home, mu_away) pour une statistique où chaque équipe a une valeur PRODUITE
    (champ_pour) et une valeur CONCÉDÉE (champ_contre) — le mu de chaque équipe est la
    moyenne de sa propre production et de ce que l'adversaire concède, chaque moyenne
    LISSÉE vers `prior` selon matchs_avec_donnees (voir _lisser_vers_prior)."""
    if not sd_home or not sd_away:
        return None
    champs = (sd_home.get(champ_pour), sd_home.get(champ_contre),
              sd_away.get(champ_pour), sd_away.get(champ_contre))
    if None in champs:
        return None
    try:
        n_home, n_away = sd_home.get("matchs_avec_donnees"), sd_away.get("matchs_avec_donnees")
        pour_home = _lisser_vers_prior(float(sd_home[champ_pour]), n_home, prior)
        contre_home = _lisser_vers_prior(float(sd_home[champ_contre]), n_home, prior)
        pour_away = _lisser_vers_prior(float(sd_away[champ_pour]), n_away, prior)
        contre_away = _lisser_vers_prior(float(sd_away[champ_contre]), n_away, prior)
        mu_home = (pour_home + contre_away) / 2
        mu_away = (pour_away + contre_home) / 2
    except (TypeError, ValueError):
        return None
    return round(max(0.15, mu_home), 2), round(max(0.15, mu_away), 2)


def _mu_direct(sd_home, sd_away, champ, prior):
    """(mu_home, mu_away) pour une statistique SANS notion d'attaque/défense (une équipe
    produit son propre volume, jamais "concédé" par l'adversaire, ex: cartons reçus, tirs
    tentés, hors-jeux) — le mu de chaque équipe est directement sa propre moyenne, LISSÉE
    vers `prior` selon matchs_avec_donnees."""
    if not sd_home or not sd_away:
        return None
    v_home, v_away = sd_home.get(champ), sd_away.get(champ)
    if v_home is None or v_away is None:
        return None
    try:
        mu_home = _lisser_vers_prior(float(v_home), sd_home.get("matchs_avec_donnees"), prior)
        mu_away = _lisser_vers_prior(float(v_away), sd_away.get("matchs_avec_donnees"), prior)
    except (TypeError, ValueError):
        return None
    return round(max(0.15, mu_home), 2), round(max(0.15, mu_away), 2)


def calculer_xg_depuis_stats_detaillees(sd_home, sd_away):
    """Buts attendus depuis les VRAIES stats des 10 DERNIERS matchs joués (API-Football,
    recuperer_stats_10_derniers_matchs) — demande explicite de l'utilisateur (30/09/2026) :
    remplacer Understat (bloqué la quasi-totalité du temps par un anti-bot, voir
    trouver_stats_understat, 0% de réussite constaté en pratique) par du calcul Python sur
    des données API-Football fiables, plutôt que de dépendre d'un scraping HTML qui échoue.
    Même méthode que calculer_xg_depuis_stats (moyenne de l'attaque de l'une et de la
    défense de l'autre), mais sur la FORME RÉCENTE (10 derniers matchs, toutes compétitions)
    plutôt que la moyenne de saison domicile/extérieur — prioritaire dans la chaîne de calcul
    car mesuré sur des matchs réellement joués récemment, jamais périmé par un plan API
    limité à une vieille saison (contrairement à calculer_xg_depuis_stats)."""
    return _mu_attaque_defense(sd_home, sd_away, "buts_marques_moyenne", "buts_encaisses_moyenne", BUTS_PRIOR)


# Poids MAXIMUM du H2H dans le xG final — jamais dominant, un signal parmi d'autres (demande
# explicite du 03/10/2026, après le constat du 02/10/2026, run #86 : Poland vs Romania, le H2H
# collecté montrait déjà Pologne +2.5 buts de moyenne sur les confrontations passées (3-0.5),
# mais le xG utilisé pour le pari ne venait QUE de la forme générale récente (1.4-1.7 but/match,
# quasi équilibrée) — jamais mélangé au H2H, alors affiché à l'IA en texte seulement. Résultat
# réel : Pologne 6-0, confirmant que le H2H était le signal le plus fiable ici. Plafonné à 40%
# et atteint seulement à partir de NB_H2H_POIDS_PLEIN confrontations analysées, pour qu'un H2H
# sur 2-3 matchs seulement (bruité) ne domine jamais un échantillon de forme plus large.
H2H_POIDS_MAX = 0.4
NB_H2H_POIDS_PLEIN = 5


def _ponderer_avec_h2h(xg_home, xg_away, h2h):
    """Mélange le xG calculé depuis la forme récente avec la moyenne de buts des confrontations
    directes (head_to_head) quand elle existe — jamais plus de H2H_POIDS_MAX, atteint seulement
    à NB_H2H_POIDS_PLEIN confrontations analysées (moins de confrontations = poids proportionnel,
    jamais 0 dès qu'il y en a au moins une)."""
    if not h2h or xg_home is None or xg_away is None:
        return xg_home, xg_away
    nb = h2h.get("matchs_analyses")
    buts_home_h2h = h2h.get("buts_home_moyenne")
    buts_away_h2h = h2h.get("buts_away_moyenne")
    if not nb or buts_home_h2h is None or buts_away_h2h is None:
        return xg_home, xg_away
    poids_h2h = min(nb, NB_H2H_POIDS_PLEIN) / NB_H2H_POIDS_PLEIN * H2H_POIDS_MAX
    xg_home_ajuste = (1 - poids_h2h) * xg_home + poids_h2h * float(buts_home_h2h)
    xg_away_ajuste = (1 - poids_h2h) * xg_away + poids_h2h * float(buts_away_h2h)
    return round(max(0.15, xg_home_ajuste), 2), round(max(0.15, xg_away_ajuste), 2)


# Intégration de l'Elo (18/10/2026, demande explicite après le constat Real Madrid-Sevilla :
# Elo seul=86,5% pour Real Madrid vs forme+H2H=57,3%, marché=78,7% — la forme sur 10 matchs,
# même mélangée au H2H, ne capture pas un écart de qualité d'effectif aussi marqué). Même
# formule logistique et même ELO_AVANTAGE_DOMICILE que moteur/features.py:_calculer_elo
# (cohérence obligatoire : l'Elo vient de là, voir collecte_donnees.recuperer_elo). ELO_POIDS_MAX
# mesuré par un vrai backtest walk-forward (5 grands championnats, 6972 matchs utilisables,
# Brier multi-classe 1/X/2, grille 0.0 à 1.0) — PAS une estimation : 0.4 minimise le Brier
# (0.5957, contre 0.6164 à poids=0, une courbe convexe propre, le poids n'est pas à un extrême).
ELO_AVANTAGE_DOMICILE = 60.0
ELO_POIDS_MAX = 0.4


def proba_elo(elo_home, elo_away):
    """Probabilité implicite (domicile vs non-domicile) depuis l'écart Elo seul, même formule
    logistique que moteur/features.py:_calculer_elo (avantage domicile inclus)."""
    return 1 / (1 + 10 ** (-(elo_home - elo_away + ELO_AVANTAGE_DOMICILE) / 400))


def _delta_vers_cible(mu_home, mu_away, p_cible, max_buts=25, iters=18):
    """Cherche par bissection le delta (mu_total constant) tel que
    proba_1x2(mu_home+delta, mu_away-delta)[0] == p_cible. Relie l'Elo à l'espace de
    probabilité déjà utilisé par le modèle plutôt qu'une constante 'buts par point Elo'
    jamais calibrée."""
    lo, hi = -min(mu_home, 5.0) + 0.001, min(mu_away, 5.0) - 0.001
    if lo >= hi:
        return 0.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        p, _, _ = proba_1x2(mu_home + mid, mu_away - mid, max_buts=max_buts)
        if p < p_cible:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _ajuster_avec_elo(xg_home, xg_away, elo, poids=ELO_POIDS_MAX):
    """Mélange le xG (déjà ajusté forme + H2H) avec la probabilité implicite Elo, par un
    déplacement mu_home/mu_away à mu_total CONSTANT (les marchés Total buts ne bougent pas,
    seul l'équilibre domicile/extérieur change) — poids plafonné, mesuré par backtest
    (ELO_POIDS_MAX), jamais appliqué en entier."""
    if not elo or xg_home is None or xg_away is None:
        return xg_home, xg_away
    elo_home, elo_away = elo.get("elo_home"), elo.get("elo_away")
    if elo_home is None or elo_away is None:
        return xg_home, xg_away
    p_cible = proba_elo(float(elo_home), float(elo_away))
    delta_full = _delta_vers_cible(xg_home, xg_away, p_cible)
    delta = poids * delta_full
    return round(max(0.15, xg_home + delta), 2), round(max(0.15, xg_away - delta), 2)


def calculer_mu_corners_depuis_stats_detaillees(sd_home, sd_away):
    """Corners attendus, domicile et extérieur SÉPARÉMENT, depuis les VRAIES stats des 10
    derniers matchs (API-Football, recuperer_stats_10_derniers_matchs) — réactive Total
    Corners, désactivé le 29/09/2026 (mu_corners=None) faute de source indépendante : la seule
    donnée disponible alors était la ligne 1xBet elle-même, comparée à d'AUTRES lignes de
    corners du même bookmaker — un edge purement circulaire, jamais une vraie valeur
    prédictive. Le split par équipe sert aussi à modéliser Corners - Handicap (voir
    _evaluer_marches_brut), pas seulement Total Corners (mu_home + mu_away)."""
    return _mu_attaque_defense(sd_home, sd_away, "corners_pour_moyenne", "corners_contre_moyenne", CORNERS_PRIOR)


def calculer_mu_cartons_depuis_stats_detaillees(sd_home, sd_away):
    """Cartons (jaunes) attendus, domicile et extérieur SÉPARÉMENT, depuis les VRAIES stats des
    10 derniers matchs (API-Football) — remplace, quand disponible, l'ancienne méthode
    circulaire (estimer_ligne_equilibree : ligne 1xBet comparée à elle-même, même défaut que les
    corners avant leur désactivation). Cartons rouges exclus (trop rares sur 10 matchs pour un
    signal fiable) ; pas de notion d'attaque/défense comme pour les buts ou les corners — un
    carton est reçu par une équipe pour son propre comportement, pas "concédé" par l'adversaire."""
    return _mu_direct(sd_home, sd_away, "cartons_jaunes_moyenne", CARTONS_PRIOR)


# Effet arbitre sur les cartons (18/10/2026, "lance les deux" après l'audit Agent 7) :
# moteur/modeles/registre.py applique déjà ce facteur (sqrt(arbitre_cartons_moy / (2*moy_ligue)),
# amorti, appliqué si arbitre_n>=5) mais bet_agent (le pipeline RÉEL) ne l'utilisait pas du tout —
# même angle mort que l'Elo avant son intégration. ARBITRE_POIDS_CARTONS mesuré par un vrai
# backtest walk-forward (5 championnats, 6780 matchs, 5528 avec effet calculable, log-
# vraisemblance négative d'une Poisson sur le total de cartons réellement observé) — 0.6
# minimise la NLL (2.0921 contre 2.0965 à poids=0, courbe convexe propre, amélioration réelle
# mais modeste, pas une estimation).
ARBITRE_POIDS_CARTONS = 0.6


def _ajuster_cartons_avec_arbitre(mu_home, mu_away, arbitre_info, poids=ARBITRE_POIDS_CARTONS):
    """Multiplie mu_home/mu_away (cartons) par un facteur dérivé de la sévérité moyenne de
    l'arbitre assigné, mesurée sur ses 30 derniers matchs (walk-forward, jamais de fuite) —
    même formule que moteur/modeles/registre.py, poids mesuré par backtest. None si l'arbitre
    est absent/pas encore assigné, ou son historique insuffisant (arbitre_n<5) : mu_home/
    mu_away inchangés, jamais un chiffre inventé."""
    if not arbitre_info or mu_home is None or mu_away is None:
        return mu_home, mu_away
    n = arbitre_info.get("arbitre_n")
    cartons_arbitre = arbitre_info.get("arbitre_cartons_moy")
    moy_ligue = arbitre_info.get("moy_ligue_cartons_par_equipe")
    if not n or n < 5 or not cartons_arbitre or not moy_ligue:
        return mu_home, mu_away
    facteur_brut = (cartons_arbitre / (2 * moy_ligue)) ** 0.5
    facteur = 1 + poids * (facteur_brut - 1)
    return round(max(0.15, mu_home * facteur), 2), round(max(0.15, mu_away * facteur), 2)


def calculer_mu_fautes_depuis_stats_detaillees(sd_home, sd_away):
    """Fautes commises attendues, domicile et extérieur SÉPARÉMENT, depuis les VRAIES stats des
    10 derniers matchs (API-Football) — demande explicite du 01/10/2026 ("utilise toutes les
    données collectées") : fautes_commises_moyenne/fautes_subies_moyenne (15 métriques déjà
    collectées par recuperer_stats_10_derniers_matchs) étaient calculées mais jamais utilisées
    pour modéliser un marché. Même méthode que les corners (attaque de l'une, "fautes subies"
    de l'autre = tendance de l'adversaire à provoquer/concéder des fautes)."""
    return _mu_attaque_defense(sd_home, sd_away, "fautes_commises_moyenne", "fautes_subies_moyenne", FAUTES_PRIOR)


def calculer_mu_tirs_depuis_stats_detaillees(sd_home, sd_away, cadres=False):
    """Tirs attendus (cadrés si cadres=True, sinon totaux), domicile et extérieur, depuis les
    VRAIES stats des 10 derniers matchs — demande explicite du 01/10/2026. Pas de notion
    d'attaque/défense comme pour les corners : aucune statistique "tirs subis/concédés" n'est
    collectée (seulement le volume de tirs PRODUITS par chaque équipe), donc le mu de chaque
    équipe est directement sa propre moyenne — même principe que les cartons."""
    champ = "tirs_cadres_moyenne" if cadres else "tirs_totaux_moyenne"
    prior = TIRS_CADRES_PRIOR if cadres else TIRS_PRIOR
    return _mu_direct(sd_home, sd_away, champ, prior)


def calculer_mu_hors_jeux_depuis_stats_detaillees(sd_home, sd_away):
    """Hors-jeux attendus, domicile et extérieur, depuis les VRAIES stats des 10 derniers
    matchs — demande explicite du 01/10/2026. Comme les tirs : aucune statistique "hors-jeux
    subis" n'est collectée, le mu de chaque équipe est directement sa propre moyenne."""
    return _mu_direct(sd_home, sd_away, "hors_jeux_moyenne", HORS_JEUX_PRIOR)


def _est_ligne_quart(x):
    r = x * 4
    return abs(r - round(r)) < 1e-6 and (round(r) % 2 != 0)


def _note_ligne_quart(handicap):
    """Explique le mécanisme d'une ligne de quart (.25/.75) : une demi-mise sur chacune des deux
    lignes ENTIÈRES/DEMI adjacentes (ex: 3.25 = moitié sur 3.0, moitié sur 3.5) — un résultat
    PARTIEL (demi-remboursement + demi-perte, ou demi-remboursement + demi-gain, selon le sens du
    pari) est possible pile sur l'une des deux lignes, jamais un simple seuil net comme sur une
    ligne entière/demi classique. Signalé par l'utilisateur le 01/10/2026 : un pari "Over 3.25"
    rédigé par l'IA ("je joue plus de trois buts") ignorait ce mécanisme, laissant croire à un
    seuil simple sans cette nuance. Volontairement SANS préciser laquelle des deux lignes
    déclenche le résultat partiel (ça dépend du sens Over/Under ou du camp Domicile/Extérieur,
    que cette fonction ne connaît pas) — juste l'avertissement que ce n'est jamais net à 100%.
    Renvoie None si handicap n'est pas une ligne de quart (aucune note nécessaire) — ne dépend
    d'aucune probabilité/catégorie, seulement du chiffre, donc s'applique aussi bien aux lignes
    de quart Total/Corners/Cartons (toujours en marché brut, jamais modélisées) qu'au handicap
    principal."""
    if handicap is None or not _est_ligne_quart(handicap):
        return None
    bas, haut = handicap - 0.25, handicap + 0.25

    def _fmt(v):
        return f"{v:g}"
    return (f"ligne de quart : moitié de la mise sur la ligne {_fmt(bas)}, moitié sur {_fmt(haut)} — "
            "un résultat PARTIEL (remboursement + gain/perte partiel) est possible pile sur l'une "
            "des deux, jamais un résultat net à 100% comme sur une ligne entière/demi classique")


def estimer_ligne_equilibree(marches, mots_cles_categorie, exclure_team=True, equipe=None):
    """Cherche, parmi les marchés Total correspondant à une catégorie donnée (buts/corners/
    cartons — identifiée par mots-clés dans le nom du marché), la ligne dont les cotes
    Plus de/Moins de sont les plus proches l'une de l'autre (donc la plus 'juste' selon le
    marché). Retourne cette ligne (l'estimation de la valeur moyenne attendue), ou None si
    rien trouvé. Réutilisée pour buts, corners et cartons — même logique, catégorie différente.

    equipe=1 ou 2 (01/10/2026, repli quand les stats détaillées manquent pour modéliser
    Corners/Bookings - Handicap) : ne cherche QUE parmi les marchés "Team 1"/"Team 2" de cette
    équipe (ex: "Corners - Over Under Team 1"), pour dériver un mu par équipe depuis le marché
    plutôt que d'inventer un split 50/50. Ignore alors exclure_team (incompatible avec ce mode)."""
    meilleure_ligne, meilleur_ecart = None, float("inf")
    for m in marches:
        nom = (m.get("marche") or "").lower()
        if not any(mc in nom for mc in mots_cles_categorie):
            continue
        est_team1 = "team 1" in nom or "team1" in nom
        est_team2 = "team 2" in nom or "team2" in nom
        if equipe == 1:
            if not est_team1:
                continue
        elif equipe == 2:
            if not est_team2:
                continue
        elif exclure_team and (est_team1 or est_team2):
            continue
        selections_m = m.get("selections", [])
        a_over = any("over" in s["selection"].lower() for s in selections_m)
        a_under = any("under" in s["selection"].lower() for s in selections_m)
        if not (a_over and a_under):
            continue
        handicap = m.get("handicap")
        if handicap is None:
            continue
        cote_over = next((s["cote"] for s in m["selections"] if "over" in s["selection"].lower()), None)
        cote_under = next((s["cote"] for s in m["selections"] if "under" in s["selection"].lower()), None)
        if cote_over and cote_under:
            ecart = abs(cote_over - cote_under)
            if ecart < meilleur_ecart:
                meilleur_ecart, meilleure_ligne = ecart, handicap
    return meilleure_ligne


def estimer_expected_goals_depuis_marches(marches):
    """
    Reconstruit mu_home/mu_away sans aucune API externe :
    - la ligne 'Total' la plus équilibrée (cotes Over/Under les plus proches) donne
      l'estimation du nombre de buts total attendu (mu_total) — c'est la ligne que
      le marché considère comme la plus proche de 50/50, donc la plus proche de la
      vraie espérance.
    - la ligne 'Handicap Asiatique' la plus équilibrée donne l'écart de force attendu
      entre les deux équipes (mu_diff).
    mu_home et mu_away sont ensuite dérivés de mu_total et mu_diff.
    """
    meilleur_total_line, meilleur_ecart_total = None, float("inf")
    for m in marches:
        nom = (m.get("marche") or "").lower()
        # IMPORTANT : exclure les totaux par équipe (Team 1/Team 2), sinon on confond
        # le total d'UNE équipe avec le total du MATCH complet — bug qui a produit
        # des xG absurdes (0.15) et des edges à 400%+ lors du premier essai.
        if "team 1" in nom or "team 2" in nom or "team1" in nom or "team2" in nom:
            continue
        # IMPORTANT : exclure les marchés Corners/Cartons — ce sont des statistiques
        # différentes des buts, les mélanger fausserait complètement l'estimation.
        if "corner" in nom or "card" in nom or "booking" in nom:
            continue
        cote_over = next((s["cote"] for s in m["selections"] if "over" in s["selection"].lower()), None)
        cote_under = next((s["cote"] for s in m["selections"] if "under" in s["selection"].lower()), None)
        if cote_over and cote_under:
            handicap = m.get("handicap")
            if handicap is None:
                continue
            ecart = abs(cote_over - cote_under)
            if ecart < meilleur_ecart_total:
                meilleur_ecart_total, meilleur_total_line = ecart, handicap

    mu_total = meilleur_total_line if meilleur_total_line is not None else 2.5
    # Garde-fou : une ligne de match plausible se situe presque toujours entre 0.5 et 6.5 buts.
    # En dehors, c'est le signe qu'une mauvaise ligne a été captée — on retombe sur 2.5 (neutre).
    if not (0.5 <= mu_total <= 6.5):
        mu_total = 2.5

    meilleur_hcp, meilleur_ecart_hcp = None, float("inf")
    for m in marches:
        nom = (m.get("marche") or "").lower()
        if "corner" in nom or "card" in nom or "booking" in nom:
            continue
        if "handicap" in nom:
            handicap = m.get("handicap")
            if handicap is None:
                continue
            cote_home = next((s["cote"] for s in m["selections"]
                               if "home" in s["selection"].lower() or s["selection"] in ("1",)), None)
            cote_away = next((s["cote"] for s in m["selections"]
                               if "away" in s["selection"].lower() or s["selection"] in ("2",)), None)
            if cote_home and cote_away:
                ecart = abs(cote_home - cote_away)
                if ecart < meilleur_ecart_hcp:
                    meilleur_ecart_hcp, meilleur_hcp = ecart, handicap

    mu_diff = -meilleur_hcp if meilleur_hcp is not None else 0.0  # handicap négatif = domicile favori
    # Garde-fou physique : l'écart entre les deux équipes ne peut pas dépasser le total
    # (sinon on obtiendrait un xG négatif pour l'équipe la plus faible) — on plafonne à 90% du total.
    mu_diff = max(-mu_total * 0.9, min(mu_total * 0.9, mu_diff))

    mu_home = max(0.15, round((mu_total + mu_diff) / 2, 2))
    mu_away = max(0.15, round((mu_total - mu_diff) / 2, 2))
    return mu_home, mu_away, mu_total, (meilleur_total_line is not None), (meilleur_hcp is not None)


# ============================================================
# POISSON — probabilités de base
# ============================================================

def poisson_p(lmbda, k):
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lmbda) - lmbda - math.lgamma(k + 1))


# Rapport variance/moyenne des TOTAUX de match, mesuré le 21/10/2026 sur 6 883 matchs FT de 20
# ligues-saisons (hist_matchs, pondéré par le nombre de matchs) : corners 1.16, cartons 0.98, tirs
# 1.34, tirs cadrés 1.10, fautes 1.23, buts 0.98. Buts et cartons sont Poisson (≈1) ; les autres sont
# légèrement surdispersés, donc modélisés en binomiale négative (même moyenne, variance = mu*rapport)
# — une Poisson pure y rend les lignes extrêmes trop sûres. Hors-jeux : pas de mesure, Poisson.
DISPERSION_PAR_CATEGORIE = {
    "Total Corners": 1.16, "Handicap Corners": 1.16,
    "Total Tirs": 1.34, "Handicap Tirs": 1.34,
    "Total Tirs Cadrés": 1.10, "Handicap Tirs Cadrés": 1.10,
    "Total Fautes": 1.23, "Handicap Fautes": 1.23,
    # Totaux par équipe : même rapport que le total (approximation, non mesurée par équipe)
    "Total Corners Équipe 1": 1.16, "Total Corners Équipe 2": 1.16,
    "Total Tirs Équipe 1": 1.34, "Total Tirs Équipe 2": 1.34,
    "Total Tirs Cadrés Équipe 1": 1.10, "Total Tirs Cadrés Équipe 2": 1.10,
    "Total Fautes Équipe 1": 1.23, "Total Fautes Équipe 2": 1.23,
}


def _pmf(mu, k, dispersion=1.0):
    """P(X=k) : Poisson si dispersion <= 1, sinon binomiale négative de moyenne mu et variance
    mu*dispersion (méthode des moments)."""
    if dispersion is None or dispersion <= 1.0001 or mu <= 0:
        return poisson_p(mu, k)
    r = mu / (dispersion - 1.0)
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))


def _borne_poisson(mu, max_buts=25, dispersion=1.0):
    """Borne de sommation d'une loi de Poisson de moyenne mu. Bug corrigé le 21/10/2026 : toutes les
    sommes étaient figées à 25 événements, or pour des fautes (mu~22) ou des tirs (mu~26) cette
    troncature perdait 30 à 60 % de la masse (mesuré : P(Over 25.5 | mu=26) = 0.0 au lieu de ~0.5), donc
    tout « Under » était surestimé — c'est la vraie cause du « Total Tirs : 50 % réel pour 69 % annoncé »
    attribué à tort à la seule surdispersion. Plancher conservé pour ne rien changer aux buts."""
    return max(max_buts, int(mu + 10 * math.sqrt(max(mu * (dispersion or 1.0), 1.0))) + 10)


def proba_1x2(mu_home, mu_away, max_buts=25):
    p_home = p_draw = p_away = 0.0
    for i in range(max_buts):
        for j in range(max_buts):
            p = poisson_p(mu_home, i) * poisson_p(mu_away, j)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def proba_over(ligne, mu_total, max_buts=25, dispersion=1.0):
    max_buts = _borne_poisson(mu_total, max_buts, dispersion)
    """Probabilité de gagner un pari 'Plus de' à la ligne donnée. Gère les lignes quart
    (.25/.75) de la même façon que proba_handicap_couvert : ce sont deux demi-mises sur
    des lignes adjacentes, avec push (remboursement) possible sur la moitié entière —
    pas un simple 'plus/moins' binaire (même bug que celui corrigé sur le handicap)."""
    def gain_et_push(l):
        p_gain, p_push = 0.0, 0.0
        for k in range(max_buts):
            p = _pmf(mu_total, k, dispersion)
            if k > l:
                p_gain += p
            elif abs(k - l) < 1e-9:
                p_push += p
        return p_gain, p_push

    r = ligne * 4
    est_ligne_quart = abs(r - round(r)) < 1e-6 and (round(r) % 2 != 0)
    if not est_ligne_quart:
        p_gain, p_push = gain_et_push(ligne)
        return p_gain + p_push * 0.5

    p_gain_bas, p_push_bas = gain_et_push(ligne - 0.25)
    p_gain_haut, p_push_haut = gain_et_push(ligne + 0.25)
    proba_bas = p_gain_bas + p_push_bas * 0.5
    proba_haut = p_gain_haut + p_push_haut * 0.5
    return (proba_bas + proba_haut) / 2


def proba_btts(mu_home, mu_away):
    p_home_0 = poisson_p(mu_home, 0)
    p_away_0 = poisson_p(mu_away, 0)
    return 1 - p_home_0 - p_away_0 + (p_home_0 * p_away_0)


def proba_total_impair(mu, max_buts=25):
    max_buts = _borne_poisson(mu, max_buts)
    return sum(poisson_p(mu, k) for k in range(1, max_buts, 2))


def proba_clean_sheet(mu_adverse):
    """Probabilité qu'une équipe garde sa cage inviolée = probabilité que l'ADVERSAIRE marque 0."""
    return poisson_p(mu_adverse, 0)


def proba_win_to_nil(mu_equipe, mu_adverse):
    """Probabilité qu'une équipe gagne SANS encaisser : l'adversaire marque 0 ET l'équipe marque >=1."""
    return poisson_p(mu_adverse, 0) * (1 - poisson_p(mu_equipe, 0))


def _gain_et_push_sur_ligne_demie(mu_home, mu_away, h, max_buts=25, dispersion=1.0):
    """Pour une ligne handicap qui est un multiple de 0.5 (pas de quart), calcule
    (probabilité de gain plein, probabilité de push/remboursement)."""
    p_gain, p_push = 0.0, 0.0
    max_i, max_j = _borne_poisson(mu_home, max_buts, dispersion), _borne_poisson(mu_away, max_buts, dispersion)
    pj = [_pmf(mu_away, j, dispersion) for j in range(max_j)]
    for i in range(max_i):
        pi = _pmf(mu_home, i, dispersion)
        for j in range(max_j):
            marge = (i - j) + h
            p = pi * pj[j]
            if marge > 0:
                p_gain += p
            elif abs(marge) < 1e-9:
                p_push += p
    return p_gain, p_push


# RÈGLE CANONIQUE DU HANDICAP ASIATIQUE sur 1xBet (demande explicite de l'utilisateur,
# 03/10/2026 : 1xBet étiquette souvent TOUT handicap "Handicap", y compris un Asiatique à
# ligne demie — jamais se fier au seul libellé textuel, toujours classifier par la VALEUR
# NUMÉRIQUE) — vérifié ci-dessous par TestProbaHandicapCouvertPushParTypeDeLigne :
#   - Ligne de QUART (.25/.75) : deux demi-mises sur les deux lignes entières/demies
#     adjacentes (ex: 1.25 = moitié sur 1.0, moitié sur 1.5) — jamais un simple gagne/perd.
#   - Ligne ENTIÈRE (0, 1, 2...) : remboursement (push) possible si l'écart réel tombe
#     EXACTEMENT sur la ligne — seul cas où un push existe.
#   - Ligne DEMIE (.5) : AUCUN push possible (l'écart de buts, toujours entier, ne peut
#     jamais tomber exactement sur une valeur .5) — gagne ou perd intégralement.
# Un marché "European Handicap"/"Handicap Européen" (3 voies 1/X/2, le nul reste un résultat
# possible) est un marché OddsPapi TOTALEMENT DISTINCT, jamais traité par ce calcul — voir
# TestAsianHandicapVsEuropeanHandicapMarchesDistincts : il ne doit jamais être confondu avec
# l'Asiatique (2 voies, push/split au lieu d'un nul) quelle que soit la valeur du handicap.
def proba_handicap_couvert(mu_home, mu_away, handicap_home, max_buts=25, dispersion=1.0):
    """Probabilité de gain sur un handicap asiatique donné pour 'home'.
    Gère correctement les lignes quart (.25/.75) : en réalité, ce sont DEUX demi-mises
    sur deux lignes adjacentes (ex: 1.25 = moitié sur 1.0, moitié sur 1.5), avec un
    remboursement partiel (push) possible sur la moitié entière/demie — ce n'est PAS
    un simple 'gagne ou perd' comme le calcul précédent le supposait à tort (ce qui
    gonflait artificiellement l'edge calculé sur ces lignes)."""
    r = handicap_home * 4
    est_ligne_quart = abs(r - round(r)) < 1e-6 and (round(r) % 2 != 0)

    if not est_ligne_quart:
        p_gain, p_push = _gain_et_push_sur_ligne_demie(mu_home, mu_away, handicap_home, max_buts, dispersion)
        # Sur une ligne pleine, un push rembourse la mise (ni gain ni perte) — pour comparer
        # équitablement à une cote décimale classique, on traite un push comme un gain neutre
        # à 0 profit : proba effective de "ne pas perdre" utilisée pour l'edge.
        return p_gain + p_push * 0.5  # approximation standard : la moitié "neutre" d'un push

    h_bas = handicap_home - 0.25
    h_haut = handicap_home + 0.25
    p_gain_bas, p_push_bas = _gain_et_push_sur_ligne_demie(mu_home, mu_away, h_bas, max_buts, dispersion)
    p_gain_haut, p_push_haut = _gain_et_push_sur_ligne_demie(mu_home, mu_away, h_haut, max_buts, dispersion)
    # Moyenne des deux moitiés de mise, chaque push comptant comme un demi-gain neutre
    proba_bas = p_gain_bas + p_push_bas * 0.5
    proba_haut = p_gain_haut + p_push_haut * 0.5
    return (proba_bas + proba_haut) / 2


def _distribution_comptage(mu, dispersion=1.0):
    """Loi (Poisson, ou binomiale négative si dispersion > 1) d'un comptage de moyenne mu — celle de
    moteur/, bornes adaptatives et renormalisation."""
    return _lois.distribution(mu, mu * dispersion if dispersion and dispersion > 1 else None)


def issues_total(ligne, mu, selection, dispersion=1.0):
    """Distribution EXACTE des 5 issues (gagné, demi-gagné, remboursé, demi-perdu, perdu) d'un
    Over/Under sur un total de moyenne mu. Même règle que la vérification des résultats."""
    resultat = dict.fromkeys(_marches.ISSUES, 0.0)
    for k, p in enumerate(_distribution_comptage(mu, dispersion)):
        resultat[_marches.issue_total(k, ligne, selection)] += p
    return resultat


def issues_handicap(mu_pour, mu_contre, handicap, dispersion=1.0):
    """Distribution exacte des 5 issues d'un handicap asiatique pour l'équipe de moyenne mu_pour
    (handicap appliqué à CETTE équipe)."""
    resultat = dict.fromkeys(_marches.ISSUES, 0.0)
    d_pour, d_contre = _distribution_comptage(mu_pour, dispersion), _distribution_comptage(mu_contre, dispersion)
    for i, pi in enumerate(d_pour):
        for j, pj in enumerate(d_contre):
            resultat[_marches.issue_ligne(i - j, handicap)] += pi * pj
    return resultat


def proba_equivalente(issues, cote):
    """Probabilité « équivalente » p telle que p*cote - 1 = espérance exacte du pari. Remplace
    l'ancienne approximation p_gain + 0.5*p_remboursement (EV fausse dès que cote != 2, audit C3) ;
    identique à p_gain sur un marché binaire (ligne demie)."""
    if not cote or cote <= 1:
        return None
    return (_marches.esperance(issues, cote) + 1) / cote


def calc_edge(proba_modele, cote):
    if not cote or cote <= 1:
        return None
    proba_implicite = 1 / cote
    return (proba_modele - proba_implicite) / proba_implicite * 100
