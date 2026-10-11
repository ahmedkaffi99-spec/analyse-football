"""Backtest hors-ligne de la logique RÉELLEMENT utilisée en production pour générer les coupons
Telegram (analyser_et_envoyer.py : estimer_expected_goals_depuis_marches + evaluer_marches_toutes),
PAS du moteur Poisson distinct déjà backtesté par moteur/backtest.py (moteur/modeles/registre.py).

Contexte (audit du 10/10/2026) : analyser_et_envoyer.py n'a jamais été backtesté. Ce script est un
harnais de préparation, pas un backtest définitif sur données réelles — voir la section "LIMITES"
ci-dessous et le rapport livré avec ce fichier.

================================================================================================
CE QUE CE SCRIPT FAIT
================================================================================================
1. Prend une liste de "cas" {marches: [...marchés OddsPapi bruts...], resultat: (buts_home, buts_away)}.
2. Reproduit EXACTEMENT le chemin de données de production pour les marchés basés sur les buts :
       marches -> estimer_expected_goals_depuis_marches(marches) -> mu_home, mu_away
       -> _evaluer_marches_brut(...) -> probabilités Poisson par marché
       -> probabilites_sans_marge(marches) -> probabilité implicite de marché (marge retirée)
       -> mélange (1-w)*p_modele + w*p_marche  [w = POIDS_MARCHE en production, paramétrable ici]
   Les quatre premières étapes importent et appellent directement les fonctions de production
   (analyser_et_envoyer.py n'est JAMAIS modifié) ; seule la dernière étape (le mélange) est
   DUPLIQUÉE ici en paramètre, parce que POIDS_MARCHE est une constante module-level dans le code
   de production et qu'on ne peut pas la faire varier sans la modifier sur place — interdit par la
   tâche. Voir `melanger_modele_marche_parametrable`.
3. Juge chaque candidat retenu contre le score réel avec bet_agent.verifier_resultats.grader_pick
   (déjà utilisé en production pour juger les paris après coup) -> issue binaire gagne/perdu/push.
   Un push est exclu du calcul Brier/log-loss (ni gagné ni perdu, comme pour tout pari réel annulé).
4. Calcule Brier, log-loss et un tableau de fiabilité par tranche de probabilité, en impportant
   TEL QUEL moteur.calibration (brier, log_loss, tableau_fiabilite) — jamais réécrit ici.

================================================================================================
LIMITES ASSUMÉES (à lire avant toute conclusion chiffrée)
================================================================================================
- AUCUNE donnée réelle hist_cotes n'a été utilisée : voir RAPPORT_DONNEES_REELLES ci-dessous,
  rempli par une vraie requête en lecture seule sur les bases disponibles. Si ce script tourne
  avec des cas synthétiques, c'est documenté explicitement dans le nom du jeu de cas
  (`cas_synthetiques_demo`) et dans chaque rapport produit — jamais présenté comme une mesure
  réelle de performance du système de production.
- Ce harnais ne couvre QUE les marchés jugeables à partir du score final (Total, BTTS, Double
  Chance, Draw No Bet, Handicap/Asian Handicap, Pair/Impair) — grader_pick ne juge pas les
  marchés statistiques (corners/cartons/tirs/fautes/hors-jeux), qui nécessitent des stats
  détaillées finales (grader_pick_stat, pas appelée ici). Les candidats de ces catégories sont
  simplement absents des cas construits.
- Ce harnais n'appelle PAS evaluer_marches_toutes() directement pour le mélange (puisque cette
  fonction utilise la constante module-level POIDS_MARCHE, non paramétrable) : il appelle
  _evaluer_marches_brut + probabilites_sans_marge séparément et refait le mélange lui-même avec un
  poids choisi. Le risque est que cette duplication dérive du code réel si analyser_et_envoyer.py
  change sans que ce fichier soit mis à jour — test de non-régression inclus
  (test_backtest_production.py::test_poids_0_65_reproduit_evaluer_marches_toutes) qui compare,
  pour POIDS_MARCHE=0.65 exactement, la sortie de ce harnais à la sortie réelle de
  evaluer_marches_toutes() sur les mêmes marchés — pour s'assurer que la "réplique" du mélange
  reste fidèle au code de production tel qu'il existe aujourd'hui.
- Ce harnais NE reproduit PAS candidat_valide() (SEUIL_EDGE/EDGE_MAX_PLAUSIBLE/PROBA_MIN_FORTE)
  ni la sélection finale par l'IA/agent3_calcul_pool_candidats (choix du pool, contraintes de
  combiné, redaction du ticket) : il mesure la QUALITÉ DE LA PROBABILITÉ produite par le mélange
  modèle/marché pour CHAQUE marché évalué, pas la rentabilité du coupon final réellement envoyé
  sur Telegram (qui dépend aussi de la cote jouée et de ces filtres). C'est un choix délibéré :
  la question posée par l'audit portait sur la calibration de la probabilité ancrée à 65% sur le
  marché, pas sur le ROI du filtre de sélection.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(__file__))          # bet_agent/ (analyser_et_envoyer, verifier_resultats)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # racine du repo (moteur/)

import analyser_et_envoyer as ae  # noqa: E402 — jamais modifié, seulement importé/appelé
import verifier_resultats as vr  # noqa: E402 — grader_pick, déjà utilisé en production pour juger après coup
from moteur import calibration  # noqa: E402 — brier/log_loss/tableau_fiabilite réutilisés tels quels


# ================================================================================================
# 1. REPRODUCTION PARAMÉTRABLE DU MÉLANGE MODÈLE/MARCHÉ (seule partie dupliquée, cf. docstring)
# ================================================================================================

def evaluer_marches_toutes_poids(marches, mu_home, mu_away, poids_marche):
    """Copie EXACTE de analyser_et_envoyer.evaluer_marches_toutes, à la seule différence que le
    poids du mélange modèle/marché est un paramètre au lieu de la constante POIDS_MARCHE. Tout le
    reste (lecture de marches, _evaluer_marches_brut, probabilites_sans_marge, calc_edge) appelle
    directement les fonctions réelles de analyser_et_envoyer.py."""
    marche_sans_marge = ae.probabilites_sans_marge(marches)
    retenus = []
    for c in ae._evaluer_marches_brut(marches, mu_home, mu_away):
        if c["categorie"] in ae.CATEGORIES_EXCLUES or c["cote"] < ae.COTE_MIN_JAMBE:
            continue
        p_marche = marche_sans_marge.get((c["marche"], c["selection"]))
        if p_marche is None:
            continue
        p_modele = c["proba_modele_pct"] / 100
        p = (1 - poids_marche) * p_modele + poids_marche * p_marche
        edge = ae.calc_edge(p, c["cote"])
        c.update(proba_modele_pct=round(p * 100, 1), edge_pct=round(edge, 1) if edge is not None else None,
                 proba_poisson_pct=round(p_modele * 100, 1), proba_marche_pct=round(p_marche * 100, 1))
        retenus.append(c)
    return sorted(retenus, key=lambda c: (c["edge_pct"] if c["edge_pct"] is not None else -999), reverse=True)


# ================================================================================================
# 2. JUGEMENT D'UN CAS (marches + résultat réel) -> liste de points (proba, issue_binaire)
# ================================================================================================

@dataclass
class ResultatCas:
    points: list = field(default_factory=list)  # [(categorie, marche, selection, proba, issue_binaire)]
    ignores: int = 0  # candidats dont grader_pick n'a pas pu juger (push, ou catégorie hors buts)


def evaluer_cas(marches, resultat, poids_marche):
    """resultat = (buts_home, buts_away) réellement joués. Renvoie un ResultatCas : pour chaque
    candidat jugeable (grader_pick renvoie gagne/perdu, jamais None/push), le triplet
    (proba_mélangée, issue 1/0)."""
    home_g, away_g = resultat
    mu_home, mu_away, mu_total, total_trouve, hcp_trouve = ae.estimer_expected_goals_depuis_marches(marches)
    candidats = evaluer_marches_toutes_poids(marches, mu_home, mu_away, poids_marche)
    r = ResultatCas()
    for c in candidats:
        issue = vr.grader_pick(c, home_g, away_g)
        if issue not in ("gagne", "perdu"):  # push ou catégorie non jugeable ici (stats) -> exclu
            r.ignores += 1
            continue
        proba = c["proba_modele_pct"] / 100
        r.points.append((c["categorie"], c["marche"], c["selection"], proba, 1 if issue == "gagne" else 0))
    return r


# ================================================================================================
# 3. AGRÉGATION SUR UN JEU DE CAS + RAPPORT (Brier/log-loss/calibration/Wilson)
# ================================================================================================

def wilson_half_width(n, z=1.96):
    """Demi-largeur approximative d'un intervalle de Wilson à 95% pour une proportion sur n essais
    binaires, évaluée au point le plus défavorable (p=0.5) — juste pour donner un ordre de grandeur
    de l'incertitude statistique liée à la taille d'échantillon, pas une estimation précise par
    marché (dont la vraie proportion n'est pas 0.5)."""
    if n <= 0:
        return float("nan")
    p = 0.5
    centre = p + z * z / (2 * n)
    marge = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    denom = 1 + z * z / n
    return marge / denom


def backtester(cas_list, poids_marche):
    """cas_list : liste de (marches, resultat). Renvoie {"global": {...}, "par_marche": {...}}."""
    tous_points = []
    par_categorie = {}
    total_ignores = 0
    for marches, resultat in cas_list:
        r = evaluer_cas(marches, resultat, poids_marche)
        total_ignores += r.ignores
        for categorie, marche, selection, proba, y in r.points:
            tous_points.append((proba, y))
            par_categorie.setdefault(categorie, []).append((proba, y))

    def _rapport(points):
        pts = [(p, y) for p, y in points]
        return {
            "n": len(pts),
            "brier": calibration.brier(pts),
            "log_loss": calibration.log_loss(pts),
            "fiabilite": calibration.tableau_fiabilite(pts),
            "wilson_demi_largeur_95pct": wilson_half_width(len(pts)),
        }

    return {
        "poids_marche": poids_marche,
        "n_cas": len(cas_list),
        "n_candidats_ignores_non_jugeables": total_ignores,
        "global": _rapport(tous_points),
        "par_marche": {cat: _rapport(pts) for cat, pts in sorted(par_categorie.items())},
    }


def comparer_poids(cas_list, poids_liste=(0.0, 0.65, 1.0)):
    return {w: backtester(cas_list, w) for w in poids_liste}


# ================================================================================================
# 4. DONNÉES RÉELLES DISPONIBLES (étape 1 de la tâche) — constaté, pas inventé
# ================================================================================================

RAPPORT_DONNEES_REELLES = """
Vérifié le 2026-10-10, en lecture seule :
- backend/app/config.py : DATABASE_URL vide => SQLite local backend/data/bet_agent.db ; sinon
  Postgres Supabase distant. Aucune des deux bases n'est accessible hors ligne ici :
  backend/data/ ne contient PAS de fichier bet_agent.db (seulement des JSON de run), et aucune
  connexion Supabase n'est disponible dans cet environnement (pas d'appel réseau autorisé de
  toute façon).
- Les seuls fichiers *.db trouvés sur la machine sont des bases de test pytest éphémères dans
  /tmp (tmpXXXXXX/test.db), créées et détruites par la suite de tests du backend à chaque run —
  confirmé vides de données réelles (tables créées par Base.metadata.create_all, schéma seul).
- hist_cotes (backend/app/models_historique.py) est alimentée depuis le 10/10/2026 SEULEMENT
  (capture_historique.py) par les runs réels en production (Supabase) : même avec un accès à
  cette base, au 10/10/2026 (date du jour), le nombre de lignes avec un `resultat` déjà jugé
  (rempli par juger_cotes_en_attente une fois les matchs terminés) est structurellement proche de
  zéro — aucun historique jugé n'a eu le temps de s'accumuler.
=> CONCLUSION : aucune donnée réelle suffisante n'est disponible pour un backtest de la logique
de production à la date de cette tâche. C'est une limite réelle de calendrier/infrastructure, pas
une raison d'inventer des résultats. Ce script est donc démontré ci-dessous sur un jeu de cas
SYNTHÉTIQUES (cas_synthetiques_demo.py), explicitement balisé comme non généralisable.
"""


def rapport_texte(resultats_par_poids):
    lignes = [RAPPORT_DONNEES_REELLES.strip(), ""]
    for poids, r in resultats_par_poids.items():
        g = r["global"]
        lignes.append(f"=== POIDS_MARCHE={poids} === n_cas={r['n_cas']} "
                      f"n_candidats_juges={g['n']} (ignorés/non jugeables : {r['n_candidats_ignores_non_jugeables']})")
        lignes.append(f"  Brier={g['brier']:.4f}  log_loss={g['log_loss']:.4f}  "
                      f"incertitude Wilson (n={g['n']}, ±pts) ≈ {g['wilson_demi_largeur_95pct']*100:.1f} pts")
        for cat, rc in r["par_marche"].items():
            lignes.append(f"    [{cat}] n={rc['n']} brier={rc['brier']:.4f} log_loss={rc['log_loss']:.4f}")
        lignes.append("")
    return "\n".join(lignes)


if __name__ == "__main__":
    from cas_synthetiques_demo import CAS_SYNTHETIQUES_DEMO

    resultats = comparer_poids(CAS_SYNTHETIQUES_DEMO, poids_liste=(0.0, 0.65, 1.0))
    print(rapport_texte(resultats))
