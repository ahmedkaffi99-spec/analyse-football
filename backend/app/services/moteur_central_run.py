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
match pour ce run, jamais remplacé par le calcul Poisson déjà démontré peu fiable ici."""

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
COTE_MIN_CENTRAL = float(os.getenv("MOTEUR_CENTRAL_COTE_MIN") or 1.3)
COTE_MAX_CENTRAL = float(os.getenv("MOTEUR_CENTRAL_COTE_MAX") or 3.0)

MEDAILLES_CENTRAL = ("🥇", "🥈", "🥉", "4️⃣", "5️⃣")

# Marchés où bet_agent utilise Poisson (voir docstring du module) alors que leur variance
# réelle est surdispersée — préfixes de candidat_central.marche (ex: "Total Tirs (28.5)"),
# couvrant aussi les variantes par équipe (ex: "Total Cartons Équipe 1 (1.5)").
PREFIXES_MARCHES_SURDISPERSES_BET_AGENT = ("Total Tirs", "Total Corners", "Total Cartons",
                                          "Total Fautes", "Total Hors-jeux")


def _exclure_bet_agent_marches_surdisperses(pool_central):
    """Retire du pool central tout candidat d'origine bet_agent sur un marché surdispersé
    (voir docstring du module) — les candidats d'origine "moteur" (binomiale négative,
    correcte pour ces marchés) sur ces mêmes marchés restent, eux, dans le pool."""
    return [c for c in pool_central
           if not (c.moteur_responsable == "bet_agent"
                   and c.marche.startswith(PREFIXES_MARCHES_SURDISPERSES_BET_AGENT))]


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
    avant_exclusion = len(pool_central)
    pool_central = _exclure_bet_agent_marches_surdisperses(pool_central)
    if avant_exclusion != len(pool_central):
        print(f"   🧮 [Moteur central] {avant_exclusion - len(pool_central)} candidat(s) bet_agent "
              f"(Poisson) retiré(s) sur des marchés surdispersés (tirs/corners/cartons/fautes/"
              f"hors-jeux) — seules les prédictions moteur (binomiale négative) y restent éligibles.")

    nb_matchs_eligibles = len({c.match for c in pool_central})
    nb_coupons_cible = ae.nb_coupons_dynamique(nb_matchs_eligibles)
    print(f"   🧮 [Moteur central] {nb_matchs_eligibles} match(s) éligible(s) → "
          f"{nb_coupons_cible} coupon(s) dynamique(s) visé(s) (pool central : "
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
