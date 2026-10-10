"""Adaptateur API-Football → vocabulaire interne OddsPapi-compatible (demande explicite du
10/10/2026, PHASE B de la migration progressive OddsPapi → API-Football).

RÈGLES ABSOLUES :
- CORRECTIF DOCUMENTAIRE (10/10/2026, audit de simplification) : contrairement à l'affirmation
  d'origine ci-dessous, ce fichier EST importé par un module de production —
  collecte_donnees.py:recuperer_marches_pour_fixture_api_football() (sous le flag
  FOURNISSEUR_COTES, voir collecte_donnees.py) — mais ce chemin reste inactif en pratique :
  FOURNISSEUR_COTES n'est positionné dans AUCUN workflow actuel (défaut "oddspapi"), donc
  aucun appel réel ne part d'ici tant que cette variable n'est pas explicitement activée.
  analyser_et_envoyer.py, runs.py, persistance.py et models.py, eux, ne l'importent jamais.
  Importer ce fichier ne déclenche AUCUN appel réseau : seule capturer_api_football_adapte()
  en fait, et seulement si on l'appelle explicitement (ou si FOURNISSEUR_COTES=api_football).
- Réutilise les mappings canoniques déjà validés de shadow_capture.py (MAPPING_API_FOOTBALL,
  CATEGORIES_ODDSPAPI, bookmaker 1xBet id=11, _normaliser_selection_api_football) — jamais
  dupliqués ni réécrits ici.
- Ne traduit JAMAIS un marché absent vers un marché différent : HANDICAP_EUROPEEN n'a pas
  d'équivalent API-Football (confirmé par 2 tests réels, voir shadow_capture.py) et n'est
  JAMAIS simulé à partir de HANDICAP_ASIATIQUE — invariant vérifié par construction (voir
  _NOMS_ODDSPAPI_PAR_CATEGORIE ci-dessous, qui exclut explicitement ce cas) et par test.
- Une correspondance ambiguë (même catégorie+ligne+sélection avec deux cotes différentes
  dans la même réponse) n'est jamais résolue au hasard : l'entrée est rejetée et signalée,
  jamais moyennée ni choisie arbitrairement.
- Une cote dont l'âge (mesuré depuis l'horodatage de mise à jour du fournisseur si connu,
  sinon depuis l'heure de réception) dépasse le TTL configuré n'est jamais présentée comme
  actuelle : le lot entier part dans `marches_perimes`, jamais mélangé avec `marches`.
- Sortie compatible avec le format déjà consommé par analyser_et_envoyer.py / models.Cote /
  persistance.enregistrer_collecte (liste de dicts {marche_id, marche, type, handicap,
  periode, selections:[{selection, cote}]}) — AUCUN de ces fichiers n'est modifié ici.

LIMITE CONNUE (à lever explicitement en Phase C, jamais deviné ici) : API-Football encode
l'Asian Handicap avec une ligne MIRORÉE par sélection ("Home -1.25" / "Away +1.25"), alors
qu'OddsPapi partage UNE seule valeur de handicap entre les sélections "1" et "2" d'un même
marché (confirmé par les données réelles du 10/10/2026 : les deux sélections OddsPapi
partagent exactement la même valeur de ligne, jamais mirorée). Deviner la convention de signe
pour les fusionner serait une correspondance inventée, explicitement interdite — donc chaque
(sélection, ligne) Asian Handicap API-Football reste ici un marché à UNE seule sélection,
jamais fusionné. Conséquence observée (voir test_adaptateur_api_football.py) :
estimer_expected_goals_depuis_marches() d'analyser_et_envoyer.py ne retrouve alors jamais les
deux côtés d'une ligne dans le même dict et retombe sur son repli (mu_diff=0.0, 50/50) — sans
planter, mais avec une perte d'information réelle sur le handicap. À corriger avant tout
remplacement effectif d'OddsPapi, par exemple via un test réel confirmant la bonne convention
de signe à appliquer pour fusionner les deux sélections d'une même ligne."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from shadow_capture import (API_FOOTBALL_BASE, API_FOOTBALL_BOOKMAKER_1XBET, API_FOOTBALL_KEY,
                           CATEGORIES_ODDSPAPI, MAPPING_API_FOOTBALL,
                           _normaliser_selection_api_football, maintenant_utc)

# Inverse de CATEGORIES_ODDSPAPI (catégorie canonique -> nom de marché style OddsPapi) —
# EXCLUT explicitement HANDICAP_EUROPEEN : API-Football n'a jamais produit cette catégorie
# (absente de MAPPING_API_FOOTBALL.values(), confirmé par 2 tests réels), donc elle ne peut
# jamais apparaître ici — exclusion défensive supplémentaire, jamais une substitution.
_NOMS_ODDSPAPI_PAR_CATEGORIE = {cat: nom for nom, cat in CATEGORIES_ODDSPAPI.items()
                                if cat != "HANDICAP_EUROPEEN"}

CATEGORIES_SANS_LIGNE = {"1X2", "DOUBLE_CHANCE", "BTTS"}  # même liste que shadow_capture.py


@dataclass
class ResultatAdaptateur:
    """Sortie complète d'un appel à l'adaptateur — distingue explicitement ce qui est prêt à
    consommer de ce qui est exclu (périmé, ambigu) ou absent (indisponible) : jamais fusionné
    silencieusement dans `marches`."""
    marches: list = field(default_factory=list)              # prêts à consommer, frais, non ambigus
    marches_indisponibles: list = field(default_factory=list)  # catégories canoniques absentes de cette réponse
    marches_perimes: list = field(default_factory=list)        # marchés trouvés mais trop anciens
    marches_ambigus: list = field(default_factory=list)        # (categorie, ligne, selection) à cotes incohérentes, rejetés
    fournisseur: str = "api_football"
    fixture_id: int | None = None
    bookmaker: str = "1xBet"
    statut_http: int | None = None
    erreur: str | None = None
    quota_epuise: bool = False
    recu_le_utc: datetime | None = None
    maj_fournisseur_utc: str | None = None
    perime: bool = False
    age_secondes: float | None = None
    nb_appels_consommes: int = 0


def _parser_age_iso(horodatage_iso):
    """datetime UTC ou None si absent/non parseable — jamais une valeur inventée."""
    if not horodatage_iso:
        return None
    try:
        dt = datetime.fromisoformat(str(horodatage_iso).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def calculer_age_secondes(maintenant, recu_le_utc, maj_fournisseur_utc=None):
    """Âge de la donnée : priorité à l'horodatage de MISE À JOUR du fournisseur (reflète la
    fraîcheur réelle de la cote elle-même) ; repli sur l'heure de RÉCEPTION (reflète seulement
    la latence réseau de cet appel, jamais garanti refléter la fraîcheur réelle — c'est un
    repli, pas une mesure équivalente)."""
    maj = _parser_age_iso(maj_fournisseur_utc)
    reference = maj if maj is not None else recu_le_utc
    if reference is None:
        return None
    return (maintenant - reference).total_seconds()


def extraire_cotations_brutes(data, bookmaker_id=API_FOOTBALL_BOOKMAKER_1XBET):
    """Parsing PUR (aucun appel réseau) du corps JSON déjà reçu de GET /odds — isolé pour être
    testable avec un JSON synthétique. Renvoie (cotations_brutes, maj_fournisseur_utc, erreur).
    cotations_brutes : [{"categorie", "selection", "ligne", "cote", "marche_id"}] — un marché
    brut non reconnu par MAPPING_API_FOOTBALL est IGNORÉ ici (jamais deviné) ; il sera comptabilisé
    comme "non_mappe" par l'appelant si besoin, jamais comme une catégorie inventée."""
    if not isinstance(data, dict):
        return [], None, "réponse non-dict"
    if data.get("errors"):
        return [], None, str(data["errors"])
    reponses = data.get("response", [])
    if not reponses:
        return [], None, "réponse vide"

    cotations, maj_fournisseur = [], None
    for rep in reponses:
        if maj_fournisseur is None:
            maj_fournisseur = rep.get("update")
        bookmaker = next((bm for bm in rep.get("bookmakers", []) if bm.get("id") == bookmaker_id), None)
        if not bookmaker:
            continue
        for bet in bookmaker.get("bets", []):
            nom_pari = bet.get("name")
            categorie = MAPPING_API_FOOTBALL.get(nom_pari, "non_mappe")
            if categorie == "non_mappe" or categorie not in _NOMS_ODDSPAPI_PAR_CATEGORIE:
                continue
            for v in bet.get("values", []):
                valeur_brute, cote_brute = v.get("value"), v.get("odd")
                selection, ligne = _normaliser_selection_api_football(categorie, valeur_brute)
                if selection is None:
                    continue
                try:
                    cote = float(cote_brute)
                except (TypeError, ValueError):
                    continue
                if cote <= 1.0:  # cote invalide : une cote décimale réelle est toujours > 1.0
                    continue
                cotations.append({"categorie": categorie, "selection": selection, "ligne": ligne,
                                  "cote": cote, "marche_id": str(bet.get("id"))})
    return cotations, maj_fournisseur, None


def traduire_en_marches_oddspapi(cotations_brutes):
    """Regroupe les cotations canoniques en marchés au format OddsPapi (marche_id, marche,
    type, handicap, periode, selections) — compatible avec analyser_et_envoyer.py SANS le
    modifier. Renvoie (marches, marches_ambigus) : une (categorie, ligne, selection) avec
    deux cotes DIFFÉRENTES dans le même lot est rejetée (jamais moyennée/choisie au hasard)."""
    groupes = {}            # (categorie, ligne) -> {selection: cote}
    rejets = {}              # (categorie, ligne) -> set(selections ambiguës)
    for c in cotations_brutes:
        cle_marche = (c["categorie"], c["ligne"])
        cle_selection = c["selection"]
        groupe = groupes.setdefault(cle_marche, {})
        if cle_selection in groupe and groupe[cle_selection] != c["cote"]:
            rejets.setdefault(cle_marche, set()).add(cle_selection)
            continue
        groupe[cle_selection] = c["cote"]

    marches, marches_ambigus = [], []
    for (categorie, ligne), selections in groupes.items():
        ambiguës = rejets.get((categorie, ligne), set())
        selections_valides = {s: cote for s, cote in selections.items() if s not in ambiguës}
        for s in ambiguës:
            marches_ambigus.append({"categorie": categorie, "ligne": ligne, "selection": s})
        if not selections_valides:
            continue
        marches.append({
            "marche_id": f"api_football:{categorie}:{ligne}",
            "marche": _NOMS_ODDSPAPI_PAR_CATEGORIE[categorie],
            "type": "",
            "handicap": ligne,
            "periode": None,  # periode=None -> "fulltime" par défaut côté analyser_et_envoyer.py
            "selections": [{"selection": s, "cote": cote} for s, cote in selections_valides.items()],
        })
    return marches, marches_ambigus


def categories_indisponibles(cotations_brutes):
    """Catégories canoniques ayant un équivalent API-Football connu (MAPPING_API_FOOTBALL)
    mais totalement absentes de cette réponse précise — jamais une catégorie inventée en
    remplacement, seulement un signalement explicite."""
    presentes = {c["categorie"] for c in cotations_brutes}
    toutes_possibles = set(MAPPING_API_FOOTBALL.values())
    return sorted(toutes_possibles - presentes)


def construire_resultat(data, fixture_id, statut_http, erreur_http, recu_le_utc,
                        nb_appels_consommes=1, ttl_secondes=90, maintenant=None):
    """Point d'entrée PUR (aucun appel réseau) : prend un corps JSON déjà reçu (ou None en cas
    d'échec réseau/HTTP) et produit un ResultatAdaptateur complet. Séparé de l'appel HTTP lui-
    même pour être testable avec des réponses synthétiques, y compris les cas d'erreur."""
    maintenant = maintenant or maintenant_utc()
    resultat = ResultatAdaptateur(fixture_id=fixture_id, statut_http=statut_http,
                                  recu_le_utc=recu_le_utc, nb_appels_consommes=nb_appels_consommes)

    if statut_http == 429:
        resultat.erreur = "quota_api_football_epuise_ou_limite_debit"
        resultat.quota_epuise = True
        return resultat
    if erreur_http:
        resultat.erreur = erreur_http
        return resultat
    if data is None:
        resultat.erreur = "aucune donnee"
        return resultat

    cotations_brutes, maj_fournisseur, erreur_parsing = extraire_cotations_brutes(data)
    resultat.maj_fournisseur_utc = maj_fournisseur
    if erreur_parsing:
        resultat.erreur = erreur_parsing
        return resultat

    age = calculer_age_secondes(maintenant, recu_le_utc, maj_fournisseur)
    resultat.age_secondes = age
    if age is not None and age > ttl_secondes:
        # Lot entier marqué périmé : jamais un mélange de cotes fraîches et périmées dans
        # `marches` — toute cette capture est trop ancienne pour être présentée comme actuelle.
        resultat.perime = True
        marches_brutes, _ = traduire_en_marches_oddspapi(cotations_brutes)
        resultat.marches_perimes = marches_brutes
        resultat.marches_indisponibles = categories_indisponibles(cotations_brutes)
        return resultat

    marches, marches_ambigus = traduire_en_marches_oddspapi(cotations_brutes)
    resultat.marches = marches
    resultat.marches_ambigus = marches_ambigus
    resultat.marches_indisponibles = categories_indisponibles(cotations_brutes)
    return resultat


# ============================================================
# APPEL RÉSEAU RÉEL — jamais exécuté à l'import, jamais appelé par ce fichier lui-même.
# ============================================================

def capturer_api_football_adapte(fixture_id_api_football, ttl_secondes=90):
    """1 appel réel GET /odds?fixture=&bookmaker=11 (même endpoint que
    shadow_capture.capturer_api_football) + construit un ResultatAdaptateur. Jamais de retry
    automatique ici (symétrique du choix déjà fait pour OddsPapi en budget strict — voir
    shadow_capture.capturer_oddspapi_sans_retry) : en cas de 429, l'appelant décide s'il
    réessaie plus tard, ce fichier ne le fait jamais lui-même."""
    import requests  # import local : aucun appel réseau tant que cette fonction n'est pas appelée

    recu_le = maintenant_utc()
    try:
        r = requests.get(f"{API_FOOTBALL_BASE}/odds",
                         headers={"x-apisports-key": API_FOOTBALL_KEY or ""},
                         params={"fixture": fixture_id_api_football, "bookmaker": API_FOOTBALL_BOOKMAKER_1XBET},
                         timeout=20)
    except Exception as e:
        return construire_resultat(None, fixture_id_api_football, None, str(e), recu_le, ttl_secondes=ttl_secondes)

    if r.status_code == 429:
        return construire_resultat(None, fixture_id_api_football, 429, None, recu_le, ttl_secondes=ttl_secondes)

    try:
        data = r.json()
    except ValueError:
        return construire_resultat(None, fixture_id_api_football, r.status_code, "réponse non-JSON",
                                   recu_le, ttl_secondes=ttl_secondes)

    return construire_resultat(data, fixture_id_api_football, r.status_code, None, recu_le,
                               ttl_secondes=ttl_secondes)
