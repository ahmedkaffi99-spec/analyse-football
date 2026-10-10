"""Adaptateur vers une forme commune inspirée de moteur/contrat.py (jamais modifié, jamais
réécrit) — demande explicite du 10/10/2026, option B : uniformiser la sortie de
moteur_central/ sans confondre le modèle statistique réellement utilisé, la source du
candidat (bet_agent vs moteur) et les informations de marché/sélection.

CONSTAT VÉRIFIÉ AVANT ÉCRITURE (voir plan présenté et validé) : dans le câblage réel actuel
(backend/app/services/decision_centrale.py + comparaison_moteurs.py), AUCUN CandidatCentral —
ni "bet_agent" ni "moteur" — ne porte de véritable moteur.modeles.registre.Prediction :
comparaison_moteurs.comparer_candidat() en retrouve bien un en interne, mais l'aplatit en
scalaires (proba_moteur_pct, modele_moteur) avant de le jeter, et CandidatCentral n'a aucun
champ pour le porter. La branche "avec Prediction" ci-dessous reste prévue pour un futur où ce
câblage changerait, mais n'est aujourd'hui jamais exercée par le pipeline réel — ce fichier ne
le prétend pas.

SCHÉMA COMMUN (mêmes clés toujours, jamais deux formats) :
- "source" : "bet_agent" | "moteur" — JAMAIS confondu avec "model"/"model_name" (le modèle
  statistique numéroté de moteur/, qui n'existe que si un vrai Prediction est fourni).
- "match_id" : toujours None ici — CandidatCentral ne porte aucun identifiant hist_matchs.
  JAMAIS assimilé à "fixture_id_oddspapi" (espace d'identifiants différent, préservé à part).
- "raw_probability"/"probability" (fractions 0-1) : distincts et jamais substitués l'un à
  l'autre. "proba_pct"/"proba_calibree_pct" (pourcentages 0-100, valeurs BRUTES de
  CandidatCentral, non transformées) sont préservés EN PLUS, pour une vérification d'unité
  sans ambiguïté.
- "edge" (fraction) = candidat.edge_pct / 100 — CONVERTI pour la cohérence du schéma commun
  (moteur.cotes.edge renvoie une fraction), mais JAMAIS RECALCULÉ : c'est la même valeur que
  bet_agent/moteur ont déjà produite, simplement changée d'unité. "edge_pct" (valeur BRUTE,
  pourcentage, non transformée) est préservé EN PLUS.
- "implied_probability" = moteur.cotes.proba_implicite(cote) = 1/cote AVEC la marge du
  bookmaker (PAS la version sans-marge du marché complet, qui nécessiterait les cotes de
  TOUTES les sélections du marché — non disponibles sur un CandidatCentral isolé). None si
  cote absente ou <= 1 (même garde que moteur.cotes.proba_implicite et que
  moteur/contrat.py:avec_cote).
- "calibration_n" : None pour tout candidat sans Prediction — "historique_marche.get('n')"
  compte des PARIS JUGÉS historiquement sur ce marché (voir moteur_central/metriques.py),
  PAS le nombre d'échantillons sur lequel une courbe de calibration isotone a été ajustée
  (concept différent de moteur/contrat.py:calibration_n). Aucune preuve dans le schéma que
  ces deux nombres coïncident -> jamais confondus ici, sur demande explicite."""

from datetime import datetime, timezone

from moteur import contrat as mcontrat
from moteur import cotes as mcotes
from moteur.features import VERSION_FEATURES
from moteur.modeles.registre import VERSION_MODELES

CLES_SCHEMA_COMMUN = (
    "source", "match_id", "model", "model_name", "market", "line", "selection",
    "raw_probability", "probability", "proba_pct", "proba_calibree_pct",
    "calibrated", "calibration_n", "binary", "timestamp", "model_version", "features_version",
    "parameters", "odds", "bookmaker", "odds_timestamp", "implied_probability",
    "edge", "edge_pct", "decision", "reasons",
    "competition", "fixture_id_oddspapi", "historique_marche",
)


def convertir(candidat, prediction=None, retenu=None, raisons=None, horodatage=None):
    """candidat : moteur_central.score_central.CandidatCentral.
    prediction : moteur.modeles.registre.Prediction réelle, SEULEMENT si l'appelant en a
        effectivement une sous la main (jamais déduite de `candidat`, qui n'en porte aucune
        dans le câblage actuel — voir docstring du module). Si fournie, moteur/contrat.py
        reste la seule source de vérité pour model/model_name/line/raw_probability/
        probability/calibrated/calibration_n/binary/model_version/features_version/
        parameters : jamais recalculés ici, jamais écrasés par les champs de `candidat`.
    retenu : True -> "decision"="retenu" ; False -> "rejeté" ; None (défaut) -> None, jamais
        deviné (la décision de sélection n'appartient pas à ce candidat pris isolément).
    raisons : si fourni, remplace explicitement `candidat.raisons` dans la sortie ; si omis
        (None), `candidat.raisons` est préservé tel quel (jamais écrasé par une liste vide)."""
    horodatage = horodatage or datetime.now(timezone.utc)
    horodatage_iso = horodatage.isoformat() if hasattr(horodatage, "isoformat") else horodatage

    if prediction is not None:
        # moteur/contrat.py reste seul responsable de market/line/selection/raw_probability/
        # probability/calibrated/calibration_n/binary/model_version/features_version/
        # parameters pour cette branche : jamais écrasés ci-dessous par les champs de `candidat`.
        base = mcontrat.prediction(match_id=None, p=prediction, horodatage=horodatage)
        source = "moteur"
    else:
        # Aucun Prediction : jamais un modèle/une version inventés (None explicite partout où
        # moteur/contrat.py exigerait un vrai Prediction pour répondre).
        base = {
            "match_id": None, "model": None, "model_name": None,
            "market": candidat.marche, "line": None, "selection": candidat.selection,
            "raw_probability": (candidat.proba_pct or 0.0) / 100,
            "probability": ((candidat.proba_calibree_pct if candidat.proba_calibree_pct is not None
                             else candidat.proba_pct) or 0.0) / 100,
            "calibrated": candidat.proba_calibree_pct is not None,
            "calibration_n": None,
            "binary": None,
            "timestamp": horodatage_iso,
            "model_version": None, "features_version": None, "parameters": None,
        }
        source = candidat.moteur_responsable

    cote_valide = candidat.cote is not None and candidat.cote > 1
    edge_fraction = candidat.edge_pct / 100 if candidat.edge_pct is not None else None

    base.update({
        "source": source,
        "proba_pct": candidat.proba_pct,
        "proba_calibree_pct": candidat.proba_calibree_pct,
        "odds": candidat.cote,
        "bookmaker": None,         # jamais deviné ("1xbet" implicite ailleurs, non porté ici)
        "odds_timestamp": None,    # non suivi sur CandidatCentral
        "implied_probability": mcotes.proba_implicite(candidat.cote) if cote_valide else None,
        "edge": edge_fraction,     # fraction, pour la cohérence du schéma commun
        "edge_pct": candidat.edge_pct,  # valeur brute préservée telle que fournie, jamais recalculée
        "decision": {True: "retenu", False: "rejeté"}.get(retenu),
        "reasons": list(raisons) if raisons is not None else list(candidat.raisons),
        "competition": candidat.competition,
        "fixture_id_oddspapi": candidat.fixture_id_oddspapi,
        "historique_marche": candidat.historique_marche,
    })
    return base
