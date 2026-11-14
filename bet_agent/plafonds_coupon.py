"""Plafond « un même pari dans UN seul coupon par jour, tous runs confondus » (14/11/2026).

Constat du 13/11/2026 : le même pari (par exemple « Mali moins de 2 buts ») figurait dans plusieurs coupons de plusieurs runs, et un seul résultat (Mali–Rwanda 3-2) faisait
perdre cinq coupons. Avant chaque run de l'agent, la base fournit les paris déjà présents dans un coupon non vide du jour d'un AUTRE run ; ils sont retirés du catalogue et refusés
par la validation. Module pur Python (aucune dépendance).

Identité d'un pari entre runs : match + catégorie + sélection + ligne, SANS le libellé du marché (« Team 1 (3.0) » et « Team 1 (3) » désignent le même pari d'un run à l'autre).
PLAFOND_PARI_JOUR=0 désactive le plafond (comparaison de modèles sur les mêmes paris)."""
import os


def plafond_actif():
    return os.getenv("PLAFOND_PARI_JOUR", "1").strip().lower() not in ("0", "non", "false", "no")


def cle_pari_jour(match, categorie, selection, handicap):
    ligne = None
    if handicap is not None:
        try:
            ligne = round(float(handicap), 2)
        except (TypeError, ValueError):
            ligne = str(handicap)
    return (str(match or "").strip(), str(categorie or "").strip(), str(selection if selection is not None else "").strip().lower(), ligne)


def cle_pari_jour_selection(selection):
    """selection : {"match": ..., "pick": {"categorie", "selection", "handicap", ...}} (forme du catalogue de l'agent)."""
    pick = selection.get("pick") or {}
    return cle_pari_jour(selection.get("match"), pick.get("categorie"), pick.get("selection"), pick.get("handicap"))
