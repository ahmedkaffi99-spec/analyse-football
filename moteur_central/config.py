"""Seuils du moteur central — jamais codés en dur dans la logique (même convention que
moteur/config.py). MOTEUR_CENTRAL_ACTIVE reste false par défaut (demande explicite du
10/10/2026, phase 1) : le moteur central calcule mais ne pilote jamais encore le coupon
Telegram. MOTEUR_CENTRAL_SHADOW (séparé de MOTEUR_COMPARAISON_ACTIVE, backend/app/services/
runs.py) contrôle uniquement si le calcul shadow est journalisé à chaque run."""

import os
from dataclasses import dataclass


def _env_bool(nom, defaut):
    valeur = os.getenv(nom)
    return defaut if valeur in (None, "") else valeur.lower() in ("1", "true", "oui", "yes")


def _env_float(nom, defaut):
    valeur = os.getenv(nom)
    return defaut if valeur in (None, "") else float(valeur)


def _env_int(nom, defaut):
    valeur = os.getenv(nom)
    return defaut if valeur in (None, "") else int(valeur)


@dataclass(frozen=True)
class ConfigCentrale:
    actif: bool = False                     # pilote réellement le coupon : jamais encore (phase shadow)
    shadow: bool = False                    # calcule et journalise à chaque run, sans rien envoyer
    n_min_fiable: int = 8                    # seuil "historique jugé digne de confiance" (qualite_marches)
    n_min_decision_moteur: int = 30          # seuil pour trancher bet_agent vs moteur sur un marché (ROI)
    nb_jambes_min: int = 2
    nb_jambes_max: int = 5
    taille_pool_max: int = 25                # recherche exhaustive au-delà : trop coûteux, voir selection.py

    @classmethod
    def depuis_env(cls, **surcharges):
        valeurs = {
            "actif": _env_bool("MOTEUR_CENTRAL_ACTIVE", cls.actif),
            "shadow": _env_bool("MOTEUR_CENTRAL_SHADOW", cls.shadow),
            "n_min_fiable": _env_int("MOTEUR_CENTRAL_N_MIN_FIABLE", cls.n_min_fiable),
            "n_min_decision_moteur": _env_int("MOTEUR_CENTRAL_N_MIN_DECISION", cls.n_min_decision_moteur),
            "nb_jambes_min": _env_int("MOTEUR_CENTRAL_NB_JAMBES_MIN", cls.nb_jambes_min),
            "nb_jambes_max": _env_int("MOTEUR_CENTRAL_NB_JAMBES_MAX", cls.nb_jambes_max),
            "taille_pool_max": _env_int("MOTEUR_CENTRAL_TAILLE_POOL_MAX", cls.taille_pool_max),
        }
        valeurs.update(surcharges)
        return cls(**valeurs)
