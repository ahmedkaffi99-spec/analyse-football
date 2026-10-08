"""Choix du moteur le plus fiable PAR MARCHÉ, à partir de métriques RÉELLES — jamais sur un
seul indicateur ("ne jamais comparer uniquement le win rate", demande explicite) : la décision
se fait sur le ROI réel (seul indicateur qui traduit directement un gain/une perte d'argent),
mais n'est rapportée QUE si l'échantillon est suffisant pour les deux moteurs.

Validation temporelle : la décision globale est recoupée séparément sur chaque moitié
chronologique du même échantillon — "stable" n'est True que si les deux moitiés désignent le
même gagnant que la décision globale. Ne JAMAIS choisir un gagnant sur le même échantillon qui
sert aussi à mesurer sa performance sans cette vérification (demande explicite)."""

from moteur_central.metriques import calculer_metriques

SEUIL_N_MIN_DECISION = 30
ECART_ROI_MINIMAL = 0.01  # moins d'1 point de ROI entre les deux moteurs : pas assez net, "égalité"


def _moitie_chronologique(lignes):
    tries = sorted(lignes, key=lambda l: str(l.get("jour") or l.get("horodatage") or ""))
    milieu = len(tries) // 2
    return tries[:milieu], tries[milieu:]


def _gagnant(roi_ba, roi_mo):
    if roi_ba is None or roi_mo is None:
        return None
    if abs(roi_ba - roi_mo) < ECART_ROI_MINIMAL:
        return "egalite"
    return "bet_agent" if roi_ba > roi_mo else "moteur"


def comparer(lignes_bet_agent, lignes_moteur, n_min=SEUIL_N_MIN_DECISION):
    """{"decision": "bet_agent"|"moteur"|"egalite"|"indisponible", "raison":str,
    "metriques_bet_agent":dict, "metriques_moteur":dict, "stable": bool|None}."""
    m_ba = calculer_metriques(lignes_bet_agent, n_min)
    m_mo = calculer_metriques(lignes_moteur, n_min)
    if not (m_ba["disponible"] and m_mo["disponible"]):
        return {"decision": "indisponible",
                "raison": "historique insuffisant pour au moins un des deux moteurs sur ce marché",
                "metriques_bet_agent": m_ba, "metriques_moteur": m_mo, "stable": None}

    roi_ba, roi_mo = m_ba.get("roi"), m_mo.get("roi")
    if roi_ba is None or roi_mo is None:
        return {"decision": "indisponible", "raison": "ROI non calculable (aucune cote capturée pour ce marché)",
                "metriques_bet_agent": m_ba, "metriques_moteur": m_mo, "stable": None}

    gagnant_global = _gagnant(roi_ba, roi_mo)

    ba1, ba2 = _moitie_chronologique(lignes_bet_agent)
    mo1, mo2 = _moitie_chronologique(lignes_moteur)
    n_min_moitie = max(n_min // 2, 1)
    m_ba1, m_mo1 = calculer_metriques(ba1, n_min_moitie), calculer_metriques(mo1, n_min_moitie)
    m_ba2, m_mo2 = calculer_metriques(ba2, n_min_moitie), calculer_metriques(mo2, n_min_moitie)
    stable = None
    if all(m["disponible"] and m.get("roi") is not None for m in (m_ba1, m_mo1, m_ba2, m_mo2)):
        g1 = _gagnant(m_ba1["roi"], m_mo1["roi"])
        g2 = _gagnant(m_ba2["roi"], m_mo2["roi"])
        stable = g1 == gagnant_global and g2 == gagnant_global

    raison = (f"ROI bet_agent={roi_ba:+.1%} (n={m_ba['n_paris']}) vs moteur={roi_mo:+.1%} (n={m_mo['n_paris']})"
              + ("" if stable is None else f" — {'stable' if stable else 'instable'} sur validation temporelle"))
    return {"decision": gagnant_global, "raison": raison, "metriques_bet_agent": m_ba, "metriques_moteur": m_mo,
            "stable": stable}


def choisir_par_marche(lignes_bet_agent_par_marche, lignes_moteur_par_marche, n_min=SEUIL_N_MIN_DECISION):
    """lignes_*_par_marche : {marche: [ligne, ...]}. Un marché absent d'un des deux dicts est
    traité comme un historique vide pour ce moteur (jamais une erreur silencieuse)."""
    tous_marches = set(lignes_bet_agent_par_marche) | set(lignes_moteur_par_marche)
    return {m: comparer(lignes_bet_agent_par_marche.get(m, []), lignes_moteur_par_marche.get(m, []), n_min)
            for m in sorted(tous_marches)}
