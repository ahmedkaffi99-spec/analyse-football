"""Exécution RÉELLE du moteur_central/ (11/10/2026, demande explicite de remplacer
"deterministe" par le moteur le plus récemment construit — moteur_central, confirmé par
audit de code avant toute modification, pas deviné du nom).

RÈGLE ABSOLUE (demande explicite) : jamais de repli silencieux vers un autre moteur. Toute
impossibilité de composer le PREMIER coupon (pas assez de candidats fiables, contrainte de
diversité non satisfaite, candidat central introuvable dans le pool d'origine...) lève une
exception — runs.py:executer_run() la laisse remonter telle quelle (statut "erreur", détail
explicite), jamais rattrapée ici pour retomber sur bet_agent/analyser_et_envoyer.py.

GÉNÉRATION DYNAMIQUE MULTI-COUPONS (13/10/2026, demande explicite : "je veux plusieurs
jambes ou plusieurs coupons combiné") : moteur_central/selection.py ne compose nativement
qu'UN SEUL coupon par appel — ce module boucle sur plusieurs appels, en retirant à chaque
tour les matchs déjà utilisés du pool central (même principe d'exclusion croisée que la
génération dynamique de bet_agent/analyser_et_envoyer.py du 11/10/2026, réutilise directement
ae.nb_coupons_dynamique pour dimensionner le nombre de coupons au volume réel de matchs
éligibles — jamais un chiffre fixé à l'avance). Un échec à partir du 2e coupon (pool restant
épuisé) n'est PAS une erreur : il arrête simplement la boucle, les coupons déjà composés
restent valides et sont retournés.

EXCLUSION DES MARCHÉS SURDISPERSÉS CALCULÉS PAR bet_agent (15/10/2026, demande explicite :
"calcul à part chaque marché, tu me dis 10 modèles tu as injecté" — chaque marché doit être
calculé par le modèle qui lui correspond, pas un seul calcul générique pour tout). Constat
réel (run 144/145, 14-15/10/2026) : les coupons convergeaient presque tous vers "Total Tirs
Under", avec un taux de réussite faible (1/6 coupons déjà tranchés) malgré un edge apparent
élevé. Cause trouvée dans bet_agent/analyser_et_envoyer.py : proba_over() applique une loi de
POISSON à TOUS les marchés "Total X", y compris tirs/corners/cartons/fautes/hors-jeux — alors
que moteur/modeles/registre.py (modèles 8-10) utilise délibérément une loi BINOMIALE NÉGATIVE
pour ces mêmes marchés, documentée explicitement comme nécessaire à cause de leur
surdispersion réelle (variance mesurée > moyenne, contrairement aux buts). Poisson sous-estime
cette variance et gonfle artificiellement l'edge apparent du côté "Under" — c'est la cause
structurelle du biais observé, pas la malchance.
_exclure_bet_agent_marches_surdisperses() retire donc du pool central tout candidat
D'ORIGINE bet_agent sur ces marchés précis (jamais les candidats d'origine "moteur", qui
restent les seuls éligibles pour tirs/tirs cadrés/corners/cartons) — si aucune prédiction
moteur n'existe pour ce match (historique insuffisant), ce marché est simplement absent de ce
match pour ce run, jamais remplacé par le calcul Poisson déjà démontré peu fiable ici.

CORRECTIF DU CORRECTIF (vérification pas-à-pas du run 146, 15/10/2026, demande explicite :
"code par code, fonction par fonction, donnée par donnée, calcul par calcul") : le filtre
ci-dessus comparait `candidat_central.marche` aux préfixes français ("Total Tirs"...), mais
`.marche` est en réalité `marche_affichage` (voir decision_centrale.construire_candidats) —
le nom BRUT du bookmaker avec la ligne (ex: "Shots - Over Under Full Time (26.5)"), jamais le
libellé français. Le log du run 146 le prouve : aucune ligne "candidat(s) bet_agent (Poisson)
retiré(s)" n'a été imprimée malgré la présence de "Total Tirs"/"Total Corners"/"Total
Cartons" dans plusieurs matchs — `avant_exclusion == len(pool_central)`, l'exclusion n'a
retiré STRICTEMENT RIEN. Corrigé en comparant `candidat_central.categorie` (le libellé
français réel, ex: "Total Tirs" — ajouté au contrat CandidatCentral et renseigné par
construire_candidats depuis pick["categorie"], jamais deviné) au lieu de `.marche`.

RUN PONCTUEL AVEC NOMBRE DE COUPONS / MARCHÉS FORCÉS (16/10/2026, demande explicite : "2
coupon et 5 par jambe et marché but total et but equipe 1 seule") : MOTEUR_CENTRAL_NB_COUPONS
et MOTEUR_CENTRAL_MARCHES_AUTORISES permettent de contourner respectivement
ae.nb_coupons_dynamique et le pool central complet pour UN run précis — vides par défaut,
comportement dynamique/complet inchangé tant qu'ils ne sont pas explicitement positionnés.

MATCHS PERDUS EN ROUTE JOURNALISÉS (18/10/2026, demande explicite : "ne laisse pas un match
disponible [de côté]") : un match collecté sur 1xBet peut finir sans aucun candidat éligible si
tous ses marchés tombent sous un filtre (aucun candidat construit, surdispersion sans
remplaçant moteur, restriction de marchés, edge suspect) — chaque étape où un match disparaît
est désormais journalisée avec sa raison précise (voir `matchs_perdus` ci-dessous), jamais
seulement le compte final de candidats.

NOMBRE DE COUPONS RECALIBRÉ POUR UNE TAILLE DE JAMBES FIXE (17/10/2026, demande explicite :
"si 26 [matchs] diffuse sur 3 à 5 coupons et min 5 jambes") : depuis que nb_jambes_min=
nb_jambes_max=5 par défaut (ConfigCentrale), ae.nb_coupons_dynamique (calibré pour des coupons
à taille VARIABLE 2-5 jambes) ne reflète plus le nombre de matchs réellement nécessaires par
coupon — son palier "10 matchs -> 3 coupons" suppose des coupons à 2 jambes (6 matchs
suffiraient), jamais 3 coupons à 5 jambes qui en demandent 15. Quand la taille est FIXE, ce
module calcule directement nb_matchs_eligibles // nb_jambes_min (jamais plus que les 5
médailles disponibles) : avec 26 matchs, ça donne 5 coupons complets (25 matchs utilisés, 1
non utilisé) — jamais un coupon visé puis avorté en cours de boucle par manque de pool.

PLAFOND D'EDGE RÉELLEMENT APPLIQUÉ AU POOL CENTRAL (16/10/2026, demande explicite après
qu'un candidat à 29.9% d'edge se soit retrouvé dans un coupon réel malgré
EDGE_MAX_PLAUSIBLE=25 dans bet_agent/analyser_et_envoyer.py) : ce seuil bet_agent n'est en
réalité appliqué QUE par evaluer_marches()/candidat_valide(), jamais appelés par le pipeline
réel (agent3_calcul_pool_candidats utilise evaluer_marches_toutes(), sans filtre, par design).
EDGE_MAX_CENTRAL/_exclure_edge_suspect() ci-dessous est donc le premier vrai rejet d'edge
suspect sur le chemin réellement exécuté — score_central() plafonnait déjà la CONTRIBUTION
de l'edge au score à 20% mais ne rejetait jamais le candidat lui-même."""

from pathlib import Path
import os
import sys

# moteur_central/ vit à la racine du dépôt (même raison que comparaison_moteurs.py/
# decision_centrale.py : ni `python -m app.taches` ni `pytest` lancés depuis backend/ ne
# l'ont sur sys.path).
_RACINE_DEPOT = str(Path(__file__).resolve().parents[3])
if _RACINE_DEPOT not in sys.path:
    sys.path.insert(0, _RACINE_DEPOT)

from moteur_central.choix_moteur import choisir_par_marche  # noqa: E402
from moteur_central.config import ConfigCentrale  # noqa: E402
from moteur_central.selection import selectionner  # noqa: E402
from moteur_central.shadow import construire_pool_central  # noqa: E402

from app.services.comparaison_moteurs import comparer_candidats  # noqa: E402
from app.services.decision_centrale import (  # noqa: E402
    _lignes_jugees_par_moteur_et_marche,
    construire_candidats,
)

# Mêmes valeurs que celles déjà utilisées (et donc déjà exercées, en mode shadow seulement)
# par decision_centrale.calculer_et_journaliser_shadow — reprises ici pour le chemin RÉEL,
# jamais recalculées différemment, et réversibles par variable d'environnement comme le
# reste de la configuration du moteur central (voir moteur_central/config.py).
COTE_MIN_CENTRAL = float(os.getenv("MOTEUR_CENTRAL_COTE_MIN") or 3.5)
COTE_MAX_CENTRAL = float(os.getenv("MOTEUR_CENTRAL_COTE_MAX") or 15.0)
# Remontés (17/10/2026, demande explicite) depuis 1.3/1.9 — ces bornes ciblaient un coupon à
# 2 jambes ; depuis que nb_jambes_min=nb_jambes_max=5 (ConfigCentrale, 17/10/2026), un coupon à
# 5 jambes dépasse presque toujours 1.9 au total même avec des cotes individuelles modestes
# (1.3^5 ≈ 3.71, 1.8^5 ≈ 18.9) — 3.5/15.0 couvre la plage réaliste pour 5 jambes à cote
# individuelle ~1.3-1.8, sans jamais bloquer la génération (la cible ne sert qu'au tie-break du
# score dans moteur_central/selection.py, jamais à rejeter une combinaison). Réversible par run
# via MOTEUR_CENTRAL_COTE_MIN/MAX (voir workflow central_cote_min/central_cote_max).

# Plafond d'edge RÉELLEMENT appliqué au pool central (16/10/2026, demande explicite : un
# candidat à edge 29.9% s'est retrouvé dans un coupon réel malgré EDGE_MAX_PLAUSIBLE=25 dans
# bet_agent/analyser_et_envoyer.py — audit montre que ce seuil n'est appliqué QUE par
# evaluer_marches()/candidat_valide(), jamais appelés par le pipeline réel
# (agent3_calcul_pool_candidats utilise evaluer_marches_toutes(), SANS filtre, par design
# depuis le passage à moteur_central — voir sa docstring "aucun filtré, aucune présélection
# Python"). score_central() PLAFONNE déjà la contribution de l'edge au score à 20% mais ne
# REJETTE jamais un candidat au-delà — ce module ajoute donc le vrai rejet, ici, au même
# niveau que les autres filtres de pool (surdispersion, marchés autorisés).
EDGE_MAX_CENTRAL = float(os.getenv("MOTEUR_CENTRAL_EDGE_MAX") or 20.0)

# Demande explicite (16/10/2026) : forcer EXACTEMENT un nombre de coupons pour UN run ponctuel
# (plutôt que ae.nb_coupons_dynamique, qui dimensionne selon le volume réel de matchs) et
# restreindre le pool central à des categorie précises (ex: "Total,Total Équipe 1" pour
# n'avoir QUE le marché buts du match et buts équipe 1) — vide par défaut : comportement
# dynamique/complet inchangé tant que ces variables ne sont pas explicitement positionnées.
NB_COUPONS_CENTRAL = os.getenv("MOTEUR_CENTRAL_NB_COUPONS")
MARCHES_AUTORISES_CENTRAL = tuple(
    v.strip() for v in (os.getenv("MOTEUR_CENTRAL_MARCHES_AUTORISES") or "").split(",") if v.strip())


def _restreindre_marches_autorises(pool_central):
    """Si MARCHES_AUTORISES_CENTRAL est renseigné, ne garde que les candidats dont la
    categorie est EXACTEMENT l'une des valeurs listées (comparaison exacte, pas un préfixe —
    "Total" ne doit jamais inclure "Total Équipe 1", ce sont deux marchés distincts). Vide
    (défaut) : aucune restriction, comportement inchangé."""
    if not MARCHES_AUTORISES_CENTRAL:
        return pool_central
    return [c for c in pool_central if c.categorie in MARCHES_AUTORISES_CENTRAL]


def _exclure_edge_suspect(pool_central):
    """Retire tout candidat dont l'edge dépasse EDGE_MAX_CENTRAL (suspect, voir docstring
    ci-dessus) — un candidat sans edge connu (c.edge_pct is None) n'est jamais exclu par cette
    règle plutôt que supposé suspect."""
    return [c for c in pool_central if c.edge_pct is None or c.edge_pct <= EDGE_MAX_CENTRAL]

MEDAILLES_CENTRAL = ("🥇", "🥈", "🥉", "4️⃣", "5️⃣")

# Marchés où bet_agent utilise Poisson (voir docstring du module) alors que leur variance
# réelle est surdispersée — préfixes de candidat_central.categorie (ex: "Total Tirs", voir
# pick["categorie"] dans bet_agent/analyser_et_envoyer.py), couvrant aussi les variantes par
# équipe (ex: "Total Cartons Équipe 1") et cadrés (ex: "Total Tirs Cadrés" via le préfixe
# "Total Tirs"). JAMAIS candidat_central.marche (voir correctif du 15/10/2026 ci-dessus) :
# ce champ porte le nom BRUT du bookmaker (ex: "Shots - Over Under Full Time (26.5)"), pas
# le libellé français, donc ne correspondrait jamais à ces préfixes.
PREFIXES_MARCHES_SURDISPERSES_BET_AGENT = ("Total Tirs", "Total Corners", "Total Cartons",
                                          "Total Fautes", "Total Hors-jeux")


def _exclure_bet_agent_marches_surdisperses(pool_central):
    """Retire du pool central tout candidat d'origine bet_agent sur un marché surdispersé
    (voir docstring du module) — les candidats d'origine "moteur" (binomiale négative,
    correcte pour ces marchés) sur ces mêmes marchés restent, eux, dans le pool. Un candidat
    sans categorie connue (jamais censé arriver, voir construire_candidats) n'est jamais
    exclu par cette règle plutôt que supposé surdispersé."""
    return [c for c in pool_central
           if not (c.moteur_responsable == "bet_agent" and c.categorie
                   and c.categorie.startswith(PREFIXES_MARCHES_SURDISPERSES_BET_AGENT))]


def _profil_central(indice):
    medaille = MEDAILLES_CENTRAL[indice] if indice < len(MEDAILLES_CENTRAL) else "🧭"
    return {"cle": f"central_{indice + 1}", "nom": f"{medaille} COUPON — MOTEUR CENTRAL #{indice + 1}",
           "cote_min": COTE_MIN_CENTRAL, "cote_max": COTE_MAX_CENTRAL}


def _rejoindre_candidat_bet_agent(pool, candidat_central):
    """Retrouve dans le pool bet_agent ORIGINAL (agent3_calcul_pool_candidats) le candidat
    complet (categorie/handicap/guide/onglet/home_nom/away_nom/contexte) correspondant à ce
    CandidatCentral — jamais une donnée inventée. Possible dans TOUS les cas (y compris quand
    candidat_central.moteur_responsable == "moteur") parce que decision_centrale.
    construire_candidats ne crée un candidat "moteur" que pour une clé (match, marché,
    sélection) qui existe déjà dans ce même pool bet_agent (même pari réel, probabilité
    concurrente) — voir ce module. La copie renvoyée porte la probabilité/l'edge RETENUS par
    le moteur central (ceux qui ont réellement motivé ce choix), jamais ceux de bet_agent si
    c'est le moteur qui a été préféré sur ce marché."""
    for c in pool.get(candidat_central.match) or []:
        pick = c.get("pick") or {}
        marche = pick.get("marche_affichage") or pick.get("marche")
        if marche == candidat_central.marche and pick.get("selection") == candidat_central.selection:
            copie = dict(c, pick=dict(pick))
            copie["pick"]["proba_modele_pct"] = candidat_central.proba_pct
            copie["pick"]["edge_pct"] = candidat_central.edge_pct
            copie["moteur_central_responsable"] = candidat_central.moteur_responsable
            return copie
    raise RuntimeError(
        f"Moteur central : jambe retenue introuvable dans le pool bet_agent d'origine "
        f"({candidat_central.match} / {candidat_central.marche} / {candidat_central.selection}) — "
        "incompatibilité réelle entre moteur_central et le pool de ce run, publication bloquée "
        "plutôt qu'une jambe incomplète envoyée.")


def executer_moteur_central(db, donnees, ae, cfg=None):
    """Calcule et sélectionne LE(S) coupon(s) RÉEL(S) via moteur_central/ à partir de la
    collecte déjà faite (donnees). Renvoie resultats_profils au format attendu par
    enregistrer_coupons/agent4_rediger_coupons (compatible bet_agent). Lève une exception si
    AUCUN coupon n'a pu être composé — jamais un résultat vide silencieux ni un repli vers un
    autre moteur."""
    cfg = cfg or ConfigCentrale.depuis_env()
    pool = ae.agent3_calcul_pool_candidats(donnees)
    if not pool:
        raise RuntimeError("Moteur central : pool de candidats vide (aucun match exploitable ce run).")

    comparaison = comparer_candidats(db, pool)
    historique = _lignes_jugees_par_moteur_et_marche(db)
    candidats_ba, candidats_mo = construire_candidats(pool, comparaison, historique, cfg)
    choix = choisir_par_marche(historique["bet_agent"], historique["moteur"], cfg.n_min_decision_moteur)
    pool_central = construire_pool_central(candidats_mo, candidats_ba, choix)

    # Suivi des matchs perdus en route (18/10/2026, demande explicite : "ne laisse pas un
    # match disponible [de côté]") — un match collecté sur 1xBet (clé de `pool`) peut quand
    # même finir sans AUCUN candidat éligible si tous ses marchés tombent sous un filtre
    # différent (aucun candidat moteur/bet_agent construit, surdispersion, restriction de
    # marchés, edge suspect). Jamais silencieux : chaque étape où un match disparaît est
    # journalisée avec sa raison, pas seulement le compte final de candidats.
    matchs_collectes = set(pool)
    matchs_avant_pool_central = {c.match for c in pool_central}

    avant_exclusion = len(pool_central)
    pool_central = _exclure_bet_agent_marches_surdisperses(pool_central)
    matchs_apres_surdispersion = {c.match for c in pool_central}
    if avant_exclusion != len(pool_central):
        print(f"   🧮 [Moteur central] {avant_exclusion - len(pool_central)} candidat(s) bet_agent "
              f"(Poisson) retiré(s) sur des marchés surdispersés (tirs/corners/cartons/fautes/"
              f"hors-jeux) — seules les prédictions moteur (binomiale négative) y restent éligibles.")

    avant_restriction = len(pool_central)
    pool_central = _restreindre_marches_autorises(pool_central)
    matchs_apres_restriction = {c.match for c in pool_central}
    if MARCHES_AUTORISES_CENTRAL:
        print(f"   🧮 [Moteur central] Restriction explicite aux marchés {MARCHES_AUTORISES_CENTRAL} "
              f"({avant_restriction} → {len(pool_central)} candidat(s)).")

    avant_edge = len(pool_central)
    pool_central = _exclure_edge_suspect(pool_central)
    matchs_apres_edge = {c.match for c in pool_central}
    if avant_edge != len(pool_central):
        print(f"   🧮 [Moteur central] {avant_edge - len(pool_central)} candidat(s) retiré(s) "
              f"pour edge suspect (> {EDGE_MAX_CENTRAL:.0f}%).")

    matchs_perdus = []
    matchs_perdus += [(m, "aucun candidat construit (historique insuffisant ou marché non mappé)")
                      for m in sorted(matchs_collectes - matchs_avant_pool_central)]
    matchs_perdus += [(m, "tous ses candidats étaient bet_agent sur un marché surdispersé, sans remplaçant moteur")
                      for m in sorted(matchs_avant_pool_central - matchs_apres_surdispersion)]
    matchs_perdus += [(m, f"aucun candidat sur les marchés autorisés {MARCHES_AUTORISES_CENTRAL}")
                      for m in sorted(matchs_apres_surdispersion - matchs_apres_restriction)]
    matchs_perdus += [(m, f"tous ses candidats restants dépassaient l'edge max ({EDGE_MAX_CENTRAL:.0f}%)")
                      for m in sorted(matchs_apres_restriction - matchs_apres_edge)]
    if matchs_perdus:
        print(f"   ⚠️ [Moteur central] {len(matchs_perdus)} match(s) collecté(s) sur 1xBet mais "
              f"SANS AUCUN candidat éligible, donc exclu(s) du pool :")
        for match, raison in matchs_perdus:
            print(f"      • {match} — {raison}")

    nb_matchs_eligibles = len({c.match for c in pool_central})
    if NB_COUPONS_CENTRAL:
        nb_coupons_cible = int(NB_COUPONS_CENTRAL)
    elif cfg.nb_jambes_min == cfg.nb_jambes_max:
        # Taille de jambes FIXE (ex: 5/5, défaut depuis le 17/10/2026) : ae.nb_coupons_dynamique
        # est calibré pour une taille VARIABLE (2 à 5) et sous-estime donc le nombre de matchs
        # réellement nécessaires par coupon à taille fixe (ex: son palier "10 matchs -> 3
        # coupons" suppose des coupons à 2 jambes, 6 matchs suffiraient, pas 3 coupons à 5
        # jambes qui en demandent 15) — calcul direct : autant de coupons COMPLETS que le pool
        # le permet (division entière), jamais plus que MEDAILLES_CENTRAL (5).
        nb_coupons_cible = min(len(MEDAILLES_CENTRAL), nb_matchs_eligibles // cfg.nb_jambes_min)
    else:
        nb_coupons_cible = ae.nb_coupons_dynamique(nb_matchs_eligibles)
    print(f"   🧮 [Moteur central] {nb_matchs_eligibles} match(s) éligible(s) → "
          f"{nb_coupons_cible} coupon(s) "
          f"{'FORCÉ(S) explicitement' if NB_COUPONS_CENTRAL else 'dynamique(s)'} visé(s) (pool central : "
          f"{len(pool_central)} candidat(s), bet_agent={len(candidats_ba)}, moteur={len(candidats_mo)}).")

    resultats, matchs_utilises = [], set()
    for indice in range(max(nb_coupons_cible, 1)):
        pool_disponible = [c for c in pool_central if c.match not in matchs_utilises]
        combo = selectionner(pool_disponible, COTE_MIN_CENTRAL, COTE_MAX_CENTRAL,
                             nb_min=cfg.nb_jambes_min, nb_max=cfg.nb_jambes_max,
                             taille_pool_max=cfg.taille_pool_max)
        if not combo.get("genere"):
            if indice == 0:
                raise RuntimeError(f"Moteur central : aucun coupon composé ({combo.get('raison')}) — "
                                   "jamais de repli automatique vers un autre moteur.")
            print(f"   🧭 [Moteur central] coupon #{indice + 1} impossible ({combo.get('raison')}) — "
                  f"{len(resultats)} coupon(s) déjà composé(s) conservé(s), arrêt de la génération.")
            break

        selections = [_rejoindre_candidat_bet_agent(pool, c) for c in combo["jambes"]]
        matchs_utilises.update(s["match"] for s in selections)
        print(f"   🧭 [Moteur central] coupon #{indice + 1} : {len(selections)} jambe(s) retenue(s), "
              f"cote totale {combo['cote_totale']}, score moyen {combo['score_moyen']}.")
        resultats.append({"profil": _profil_central(indice), "selections": selections})

    ae.verifier_unicite_matchs_coupons(resultats)
    return resultats
