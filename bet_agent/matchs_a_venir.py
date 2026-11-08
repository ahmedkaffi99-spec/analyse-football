"""Matchs pas encore commencés et fraîcheur des cotes (07/11/2026). Module pur Python (aucune dépendance).

Constat du 07/11/2026 : un run relancé en fin de matinée ou l'après-midi (collecte réutilisée) pouvait proposer des paris sur des matchs déjà commencés ou terminés,
et les cotes affichées dataient de plusieurs heures sans que rien ne l'indique dans le message Telegram.
- `retirer_matchs_commences` retire de la collecte les matchs dont le coup d'envoi est passé (ou dans moins de MARGE_AVANT_MATCH_MIN minutes). Un coup d'envoi inconnu
  garde le match (on ne retire jamais sur une donnée absente). FILTRER_MATCHS_COMMENCES=0 désactive le filtre.
- `ligne_fraicheur` : ligne ajoutée aux messages Telegram (heure de relevé des cotes, prochain coup d'envoi)."""
import copy
import os
from datetime import datetime, timedelta, timezone


def _lire_marge():
    try:
        return max(0, int(os.getenv("MARGE_AVANT_MATCH_MIN") or 10))
    except ValueError:
        return 10


def _en_datetime(texte):
    if not texte:
        return None
    try:
        d = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def coup_envoi(match):
    """Coup d'envoi (datetime UTC) d'un match de la collecte : date API-Football, sinon OddsPapi ; None si inconnu."""
    af, op = (match or {}).get("api_football") or {}, (match or {}).get("oddspapi") or {}
    return _en_datetime(af.get("fixture_date")) or _en_datetime(op.get("start_time"))


def nom_du_match(match):
    af, demande = (match or {}).get("api_football") or {}, (match or {}).get("match_demande") or {}
    return f"{af.get('home_name') or demande.get('home') or '?'} - {af.get('away_name') or demande.get('away') or '?'}"


def filtre_actif():
    return os.getenv("FILTRER_MATCHS_COMMENCES", "1").strip().lower() not in ("0", "non", "false", "no")


def retirer_matchs_commences(donnees, maintenant=None, marge_min=None):
    """-> (donnees_filtrees, noms_retires). `donnees` n'est jamais modifiée : copie si au moins un match est retiré. Les compteurs nb_matchs_* sont recalculés."""
    if not donnees or not filtre_actif():
        return donnees, []
    maintenant = maintenant or datetime.now(timezone.utc)
    limite = maintenant + timedelta(minutes=_lire_marge() if marge_min is None else marge_min)
    gardes, retires = [], []
    for m in donnees.get("matchs", []):
        debut = coup_envoi(m)
        (retires if debut is not None and debut <= limite else gardes).append(m)
    if not retires:
        return donnees, []
    nouvelles = copy.copy(donnees)
    nouvelles["matchs"] = gardes
    nouvelles["nb_matchs_demandes"] = len(gardes)
    nouvelles["nb_matchs_avec_marches"] = sum(1 for m in gardes if (m.get("oddspapi") or {}).get("tous_marches"))
    nouvelles["nb_marches_total"] = sum(len((m.get("oddspapi") or {}).get("tous_marches") or []) for m in gardes)
    return nouvelles, [nom_du_match(m) for m in retires]


def ligne_fraicheur(donnees, maintenant=None):
    """« 🕒 Cotes relevées à 06:25 UTC · prochain match à 15:00 UTC — vérifie les cotes sur 1xBet avant de parier. » ('' si l'heure de collecte est inconnue)."""
    collecte = _en_datetime((donnees or {}).get("date_collecte"))
    if collecte is None:
        return ""
    maintenant = maintenant or datetime.now(timezone.utc)
    debuts = sorted(d for d in (coup_envoi(m) for m in (donnees or {}).get("matchs", [])) if d is not None and d > maintenant)
    texte = f"🕒 Cotes relevées à {collecte.strftime('%H:%M')} UTC"
    if debuts:
        texte += f" · prochain match à {debuts[0].strftime('%H:%M')} UTC"
    return texte + " — vérifie les cotes sur 1xBet avant de parier."
