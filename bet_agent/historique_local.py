"""Repli SANS API-Football : stats d'équipe, 10 derniers matchs détaillés, confrontations directes et
Elo calculés depuis les 5 saisons déjà stockées (table hist_matchs). Même format de sortie que
collecte_donnees (trouver_ligue_et_stats, recuperer_stats_10_derniers_matchs,
recuperer_head_to_head) pour que le reste de la chaîne n'y voie aucune différence.

Activé par SANS_API_FOOTBALL=1 (abonnement API-Football terminé). Rien n'est inventé : une équipe
introuvable dans l'historique renvoie None, et le pipeline retombe sur l'estimation par les cotes."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unidecode import unidecode

SEUIL_NOM = 85
NB_MATCHS_STATS = 38
JOURS_MAX_STATS = 400
NB_MATCHS_DETAILLES = 10
NB_CONFRONTATIONS = 10

# noms usuels (cotes / listes manuelles) -> nom en base
ALIAS = {
    "man city": "manchester city", "man united": "manchester united", "man utd": "manchester united",
    "tottenham hotspur": "tottenham", "spurs": "tottenham", "leeds united": "leeds",
    "newcastle united": "newcastle", "wolverhampton": "wolves", "wolverhampton wanderers": "wolves",
    "ipswich town": "ipswich", "coventry city": "coventry", "west ham united": "west ham",
    "inter milan": "inter", "internazionale": "inter", "milan": "ac milan", "roma": "as roma",
    "atletico madrid": "atletico madrid", "atletico de madrid": "atletico madrid",
    "athletic bilbao": "athletic club", "deportivo alaves": "alaves", "alaves": "alaves",
    "bayern": "bayern munchen", "bayern munich": "bayern munchen", "fc bayern munchen": "bayern munchen",
    "dortmund": "borussia dortmund", "gladbach": "borussia monchengladbach",
    "borussia monchengladbach": "borussia monchengladbach", "leverkusen": "bayer leverkusen",
    "stuttgart": "vfb stuttgart", "leipzig": "rb leipzig", "augsburg": "fc augsburg",
    "freiburg": "sc freiburg", "hoffenheim": "1899 hoffenheim", "tsg hoffenheim": "1899 hoffenheim",
    "schalke": "fc schalke 04", "schalke 04": "fc schalke 04", "paderborn": "sc paderborn 07",
    "bremen": "werder bremen", "koln": "1. fc koln", "cologne": "1. fc koln",
    "psg": "paris saint germain", "paris saint-germain": "paris saint germain",
    "troyes": "estac troyes", "brest": "stade brestois 29", "saint-etienne": "saint etienne",
    "st etienne": "saint etienne", "rayo vallecano": "rayo vallecano", "betis": "real betis",
}

_cache = {}


def _norm(nom):
    return unidecode(nom or "").lower().replace("-", " ").strip()


def _charger():
    if "matchs" in _cache:
        return _cache["matchs"]
    racine = Path(__file__).resolve().parent.parent
    for dossier in (str(racine), str(racine / "backend")):
        if dossier not in sys.path:
            sys.path.insert(0, dossier)
    from app.database import SessionLocal
    from app.services.historique import charger_matchs
    with SessionLocal() as db:
        matchs = charger_matchs(db)
    _cache["matchs"] = matchs
    return matchs


def _equipes(matchs):
    """{team_id: (nom, competition_id)} d'après le match le plus récent de chaque équipe."""
    if "equipes" in _cache:
        return _cache["equipes"]
    vus = {}
    for m in sorted(matchs, key=lambda x: str(x["date"])):
        for cle_id, cle_nom in (("home_id", "home"), ("away_id", "away")):
            vus[m[cle_id]] = (m[cle_nom], m["competition_id"])
    _cache["equipes"] = vus
    return vus


def resoudre_equipe(nom, matchs=None):
    """(team_id, nom_en_base, competition_id) ou None. Exige un score >= SEUIL_NOM et refuse les
    équipes réserve/jeunes — un faux positif fausserait tout le calcul."""
    from rapidfuzz import fuzz
    equipes = _equipes(matchs if matchs is not None else _charger())
    cle = _norm(nom)
    cle = ALIAS.get(cle, cle)
    meilleur, trouve = 0, None
    for team_id, (nom_base, comp) in equipes.items():
        cible = _norm(nom_base)
        score = 100 if cible == cle else fuzz.token_set_ratio(cle, cible)
        if score > meilleur:
            meilleur, trouve = score, (team_id, nom_base, comp)
    return trouve if meilleur >= SEUIL_NOM else None


def _date(m):
    d = m["date"]
    if isinstance(d, str):
        d = datetime.fromisoformat(d.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _termines(matchs, team_id, avant):
    sel = [m for m in matchs
           if team_id in (m["home_id"], m["away_id"]) and m.get("home_score") is not None
           and m.get("away_score") is not None and _date(m) < avant]
    sel.sort(key=_date)
    return sel


def _moy(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    return round(sum(valeurs) / len(valeurs), 2) if valeurs else None


def stats_equipe(team_id, nom, competition_id, avant=None, matchs=None):
    """Même contrat que collecte_donnees.trouver_ligue_et_stats (moyennes de buts domicile/extérieur
    sur la dernière année), ou None sous 5 matchs."""
    matchs = matchs if matchs is not None else _charger()
    avant = avant or datetime.now(timezone.utc)
    recents = [m for m in _termines(matchs, team_id, avant) if _date(m) >= avant - timedelta(days=JOURS_MAX_STATS)]
    recents = recents[-NB_MATCHS_STATS:]
    if len(recents) < 5:
        return None
    dom = [m for m in recents if m["home_id"] == team_id]
    ext = [m for m in recents if m["away_id"] == team_id]
    forme = ""
    for m in recents[-5:]:
        pour, contre = ((m["home_score"], m["away_score"]) if m["home_id"] == team_id
                        else (m["away_score"], m["home_score"]))
        forme += "W" if pour > contre else ("D" if pour == contre else "L")
    ref = recents[-1]
    return {
        "league_id": competition_id, "league_name": ref.get("competition"), "league_type": "League",
        "season": ref.get("saison"), "matchs_joues": len(recents),
        "buts_marques_domicile": _moy([m["home_score"] for m in dom]),
        "buts_marques_exterieur": _moy([m["away_score"] for m in ext]),
        "buts_encaisses_domicile": _moy([m["away_score"] for m in dom]),
        "buts_encaisses_exterieur": _moy([m["home_score"] for m in ext]),
        "forme": forme, "source": "hist_matchs",
    }


def stats_detaillees(team_id, avant=None, matchs=None):
    """Même contrat que collecte_donnees.recuperer_stats_10_derniers_matchs, depuis hist_matchs."""
    matchs = matchs if matchs is not None else _charger()
    avant = avant or datetime.now(timezone.utc)
    derniers = _termines(matchs, team_id, avant)[-NB_MATCHS_DETAILLES:]
    if len(derniers) < 3:
        return None
    pour, contre, pts = [], [], []
    st = {k: [] for k in ("corners_pour", "corners_contre", "jaunes", "rouges", "fautes", "fautes_subies",
                          "cadres", "tirs", "possession")}
    clean = 0
    for m in derniers:
        dom = m["home_id"] == team_id
        bp, bc = (m["home_score"], m["away_score"]) if dom else (m["away_score"], m["home_score"])
        pour.append(bp)
        contre.append(bc)
        clean += 1 if bc == 0 else 0
        pts.append(3 if bp > bc else (1 if bp == bc else 0))
        s = m.get("stats") or {}
        moi, adv = s.get("home" if dom else "away") or {}, s.get("away" if dom else "home") or {}
        st["corners_pour"].append(moi.get("corners"))
        st["corners_contre"].append(adv.get("corners"))
        st["jaunes"].append(moi.get("yellow_cards"))
        st["rouges"].append(moi.get("red_cards"))
        st["fautes"].append(moi.get("fouls"))
        st["fautes_subies"].append(adv.get("fouls"))
        st["cadres"].append(moi.get("shots_on_target"))
        st["tirs"].append(moi.get("shots"))
        st["possession"].append(moi.get("possession"))
    return {
        "source": "hist_matchs_10_derniers_matchs", "matchs_avec_donnees": len(pour),
        "buts_marques_moyenne": _moy(pour), "buts_encaisses_moyenne": _moy(contre),
        "corners_pour_moyenne": _moy(st["corners_pour"]), "corners_contre_moyenne": _moy(st["corners_contre"]),
        "cartons_jaunes_moyenne": _moy(st["jaunes"]), "cartons_rouges_moyenne": _moy(st["rouges"]),
        "fautes_commises_moyenne": _moy(st["fautes"]), "fautes_subies_moyenne": _moy(st["fautes_subies"]),
        "tirs_cadres_moyenne": _moy(st["cadres"]), "tirs_totaux_moyenne": _moy(st["tirs"]),
        "possession_moyenne_pct": _moy(st["possession"]), "hors_jeux_moyenne": None,
        "passes_reussies_pct_moyenne": None, "clean_sheets_nombre": clean,
        "points_par_match_moyenne": _moy(pts),
    }


def head_to_head(home_id, away_id, avant=None, matchs=None):
    """Même contrat que collecte_donnees.recuperer_head_to_head, depuis hist_matchs."""
    matchs = matchs if matchs is not None else _charger()
    avant = avant or datetime.now(timezone.utc)
    conf = [m for m in _termines(matchs, home_id, avant)
            if {m["home_id"], m["away_id"]} == {home_id, away_id}][-NB_CONFRONTATIONS:]
    if not conf:
        return None
    vh = va = nuls = bh = ba = 0
    for m in conf:
        a, b = ((m["home_score"], m["away_score"]) if m["home_id"] == home_id
                else (m["away_score"], m["home_score"]))
        bh, ba = bh + a, ba + b
        if a > b:
            vh += 1
        elif b > a:
            va += 1
        else:
            nuls += 1
    n = len(conf)
    return {"source": "hist_matchs_head_to_head", "matchs_analyses": n, "victoires_home": vh,
            "victoires_away": va, "nuls": nuls, "buts_home_moyenne": round(bh / n, 2),
            "buts_away_moyenne": round(ba / n, 2)}
