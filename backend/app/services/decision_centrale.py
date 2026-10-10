"""Orchestration SHADOW du moteur_central/ (demande explicite du 10/10/2026) : construit les
candidats bet_agent/moteur du run réel (pool + comparaison_moteurs), les enrichit avec les
métriques RÉELLES déjà accumulées dans hist_cotes (JAMAIS un backtest artificiel — seulement ce
qui a été réellement capturé puis réellement jugé, voir capture_historique.py), calcule les 3
coupons indépendants (bet_agent seul / moteur seul / moteur central) et les journalise dans
hist_decisions_centrales.

RÈGLE ABSOLUE : jamais utilisé pour modifier la sélection réelle ni le coupon Telegram tant que
MOTEUR_CENTRAL_ACTIVE reste false (voir moteur_central/config.py) — appelé depuis runs.py
derrière MOTEUR_CENTRAL_SHADOW, APRÈS que le coupon réel est déjà figé et envoyé. Un échec ici
ne doit jamais faire échouer le run réel."""

import sys
from pathlib import Path

from sqlalchemy import select

from app.models_historique import HistCote, HistDecisionCentrale

# moteur_central/ vit à la racine du dépôt, comme moteur/ (voir comparaison_moteurs.py, même
# raison : ni `python -m app.taches` ni `pytest` lancés depuis backend/ ne l'ont sur sys.path).
_RACINE_DEPOT = str(Path(__file__).resolve().parents[3])
if _RACINE_DEPOT not in sys.path:
    sys.path.insert(0, _RACINE_DEPOT)

from moteur_central.choix_moteur import choisir_par_marche  # noqa: E402
from moteur_central.config import ConfigCentrale  # noqa: E402
from moteur_central.contrat_adapter import convertir as convertir_contrat  # noqa: E402
from moteur_central.metriques import calculer_metriques  # noqa: E402
from moteur_central.score_central import CandidatCentral  # noqa: E402
from moteur_central.shadow import calculer_shadow  # noqa: E402


def _lignes_jugees_par_moteur_et_marche(db):
    """{"bet_agent": {marche: [ligne,...]}, "moteur": {marche: [ligne,...]}} à partir de TOUT
    l'historique hist_cotes déjà jugé (resultat non NULL) — jamais une cote fabriquée."""
    lignes = list(db.scalars(select(HistCote).where(HistCote.resultat.isnot(None))))
    par_moteur = {"bet_agent": {}, "moteur": {}}
    for row in lignes:
        base = {"cote": row.cote, "resultat": row.resultat, "marche": row.marche,
                "competition": row.competition, "jour": row.jour.isoformat() if row.jour else None}
        if row.proba_bet_agent_pct is not None:
            par_moteur["bet_agent"].setdefault(row.marche, []).append({**base, "proba_pct": row.proba_bet_agent_pct})
        if row.proba_moteur_pct is not None:
            par_moteur["moteur"].setdefault(row.marche, []).append({**base, "proba_pct": row.proba_moteur_pct})
    return par_moteur


def _metriques_marche(lignes_par_marche, marche, n_min):
    lignes = lignes_par_marche.get(marche, [])
    if not lignes:
        return {"disponible": False, "n": 0, "n_min": n_min, "raison": "aucune capture jugée pour ce marché"}
    return calculer_metriques(lignes, n_min)


def construire_candidats(pool, comparaison, historique_par_moteur_et_marche, cfg):
    """pool : {match: [candidat bet_agent, ...]} (bet_agent.agent3_calcul_pool_candidats).
    comparaison : comparaison_moteurs.comparer_candidats(db, pool). Renvoie
    (candidats_bet_agent, candidats_moteur) — un candidat moteur seulement si comparaison_moteurs
    a pu réellement prédire (historique hist_matchs suffisant), jamais inventé."""
    comparaison_par_cle = {(c["match"], c["marche_bet_agent"], c["selection"]): c for c in comparaison}
    candidats_ba, candidats_mo = [], []
    deja_vus = set()
    for nom_match, candidats in pool.items():
        for c in candidats:
            pick = c.get("pick") or {}
            cote, marche, selection = pick.get("cote"), (pick.get("marche_affichage") or pick.get("marche")), pick.get("selection")
            cle = (nom_match, marche, selection)
            if cote is None or marche is None or cle in deja_vus:
                continue
            deja_vus.add(cle)
            comp = comparaison_par_cle.get(cle)

            candidats_ba.append(CandidatCentral(
                match=nom_match, marche=marche, selection=selection, cote=cote, moteur_responsable="bet_agent",
                proba_pct=pick.get("proba_modele_pct") or 0.0, competition=c.get("competition"),
                edge_pct=pick.get("edge_pct"),
                historique_marche=_metriques_marche(historique_par_moteur_et_marche["bet_agent"], marche, cfg.n_min_fiable),
                fixture_id_oddspapi=c.get("fixture_id_oddspapi")))

            if comp and comp.get("proba_moteur_pct") is not None:
                candidats_mo.append(CandidatCentral(
                    match=nom_match, marche=marche, selection=selection, cote=cote, moteur_responsable="moteur",
                    proba_pct=comp["proba_moteur_pct"], competition=c.get("competition"),
                    edge_pct=comp.get("edge_moteur_pct"),
                    historique_marche=_metriques_marche(historique_par_moteur_et_marche["moteur"], marche, cfg.n_min_fiable),
                    fixture_id_oddspapi=c.get("fixture_id_oddspapi")))
    return candidats_ba, candidats_mo


def _combo_vers_json(combo):
    """Métadonnées du coupon (genere/nb_jambes/cote_totale/score_moyen) inchangées — seul le
    format de chaque jambe change : schéma commun de moteur_central/contrat_adapter.py (Lot 3,
    Phase 1 du plan de bascule du 10/10/2026) au lieu d'un sous-ensemble de champs choisi à la
    main. Aucune Prediction réelle n'est fournie ici (voir contrat_adapter.py : le câblage
    actuel n'en porte jamais) — convertir() décrit alors le candidat depuis CandidatCentral
    seul, jamais un modèle inventé. "retenu"/"raisons" restent None/non fournis : ce lot ne
    porte pas de décision de sélection individuelle, seulement la composition déjà faite par
    selectionner()."""
    if not combo.get("genere"):
        return {"genere": False, "raison": combo.get("raison")}
    return {"genere": True, "nb_jambes": combo["nb_jambes"], "cote_totale": combo["cote_totale"],
            "score_moyen": combo["score_moyen"],
            "jambes": [convertir_contrat(j) for j in combo["jambes"]]}


def calculer_et_journaliser_shadow(db, run, pool, comparaison, cote_min=1.3, cote_max=3.0, cfg=None):
    """Calcule le shadow pour CE run (bet_agent seul / moteur seul / moteur central) et le
    journalise dans hist_decisions_centrales — purement informatif, voir docstring du module."""
    cfg = cfg or ConfigCentrale.depuis_env()
    historique = _lignes_jugees_par_moteur_et_marche(db)
    candidats_ba, candidats_mo = construire_candidats(pool, comparaison, historique, cfg)
    choix = choisir_par_marche(historique["bet_agent"], historique["moteur"], cfg.n_min_decision_moteur)
    resultat = calculer_shadow(candidats_mo, candidats_ba, choix, cote_min, cote_max)

    ligne = HistDecisionCentrale(
        run_id=run.id, coupon_bet_agent=_combo_vers_json(resultat["bet_agent"]),
        coupon_moteur=_combo_vers_json(resultat["moteur"]), coupon_central=_combo_vers_json(resultat["central"]),
        raisons=choix, metriques={"pool_central_taille": resultat["pool_central_taille"],
                                  "n_candidats_bet_agent": len(candidats_ba), "n_candidats_moteur": len(candidats_mo)})
    db.add(ligne)
    db.commit()
    return ligne
