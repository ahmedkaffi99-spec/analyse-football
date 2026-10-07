"""Backfill de matchs terminés (score + statistiques) depuis API-Football, pour le moteur
d'analyse (moteur/backtest.py). Réutilise les fonctions bas niveau de collecte_donnees.py
(clé, limite de débit, lecture des statistiques) via le même pont que pipeline.py — jamais de
duplication de la logique d'appel réseau.

Convertit chaque fixture API-Football au format attendu par moteur.features (voir
HistMatch.vers_dict), les enregistre (upsert par match_id), et expose un chargeur qui relit la
base pour nourrir moteur.backtest.executer SANS jamais republier côté pipeline quotidien."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models_historique import HistMatch

# Nom API-Football -> clé moteur (moteur.modeles.marches.STATS_PAR_FAMILLE + xG/possession pour
# les features) ; une statistique absente du bloc n'est jamais inventée (voir _valeur_stat).
STATS_CLES = {
    "Corner Kicks": "corners", "Yellow Cards": "yellow_cards", "Red Cards": "red_cards",
    "Total Shots": "shots", "Shots on Goal": "shots_on_target", "Fouls": "fouls",
    "Ball Possession": "possession", "Expected goals": "xg",
}
STATUTS_TERMINES = ("FT", "AET", "PEN")


def _fixtures_ligue_saison(cd, league_id, season):
    cd._respecter_rate_limit_api_football()
    r = cd.SESSION.get("https://v3.football.api-sports.io/fixtures",
                       headers={"x-apisports-key": cd.API_FOOTBALL_KEY},
                       params={"league": league_id, "season": season}, timeout=20)
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"API-Football erreur (ligue {league_id}, saison {season}) : {data['errors']}")
    return data.get("response", [])


def _stats_par_equipe(cd, fixture_id, home_id):
    """(dict stats) ou None si indisponible — jamais une statistique inventée."""
    try:
        blocs = cd._appel_statistiques_fixture(fixture_id)
    except Exception:
        return None
    if len(blocs) != 2:
        return None
    par_equipe = {}
    for bloc in blocs:
        team_id = (bloc.get("team") or {}).get("id")
        brut = bloc.get("statistics") or []
        valeurs = {cle: v for nom_af, cle in STATS_CLES.items() if (v := cd._valeur_stat(brut, nom_af)) is not None}
        if team_id is not None:
            par_equipe[team_id] = valeurs
    if home_id not in par_equipe:
        return None
    away_id = next((k for k in par_equipe if k != home_id), None)
    return {"home": par_equipe[home_id], "away": par_equipe.get(away_id, {})}


def fixture_vers_match(fx, cd, avec_stats):
    """1 fixture API-Football brute -> 1 dict au format moteur.features (HistMatch.vers_dict)."""
    fixture, league, teams, goals = (fx.get(k) or {} for k in ("fixture", "league", "teams", "goals"))
    home, away = teams.get("home") or {}, teams.get("away") or {}
    statut = (fixture.get("status") or {}).get("short")
    termine = statut in STATUTS_TERMINES
    match_id = fixture.get("id")
    m = {
        "match_id": match_id, "date": fixture.get("date"), "competition_id": league.get("id"),
        "competition": league.get("name"), "saison": league.get("season"),
        "home_id": home.get("id"), "home": home.get("name"), "away_id": away.get("id"), "away": away.get("name"),
        "arbitre": fixture.get("referee"), "statut": statut,
        "home_score": goals.get("home") if termine else None, "away_score": goals.get("away") if termine else None,
        "stats": None,
    }
    if termine and avec_stats and match_id and home.get("id"):
        m["stats"] = _stats_par_equipe(cd, match_id, home["id"])
    return m


def upsert_matchs(db, matchs):
    """Insère ou met à jour (par match_id) — idempotent : relancer le backfill ne duplique rien
    et rafraîchit un match déjà présent (ex: passé de 'NS' à 'FT' entre deux passages)."""
    if not matchs:
        return 0
    moteur_insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    colonnes = ("date", "competition_id", "competition", "saison", "home_id", "home", "away_id", "away",
               "arbitre", "statut", "home_score", "away_score", "stats")
    lignes = [{"match_id": m["match_id"], **{c: m.get(c) for c in colonnes}} for m in matchs if m.get("match_id")]
    for ligne in lignes:
        if isinstance(ligne["date"], str):
            d = datetime.fromisoformat(ligne["date"].replace("Z", "+00:00"))
            ligne["date"] = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if not lignes:
        return 0
    stmt = moteur_insert(HistMatch).values(lignes)
    stmt = stmt.on_conflict_do_update(index_elements=["match_id"],
                                      set_={c: stmt.excluded[c] for c in colonnes})
    db.execute(stmt)
    db.commit()
    return len(lignes)


def backfill_ligue_saison(db, league_id, season, avec_stats=True, limite_appels_stats=None):
    """Télécharge et enregistre tous les matchs d'une (ligue, saison). limite_appels_stats :
    plafond du nombre de matchs dont on va chercher les statistiques dans CET appel (le reste
    est enregistré sans stats, rattrapable par un futur passage) — pour piloter le budget de
    quota d'un run plutôt que de le découvrir en cours de route."""
    from app.services.pipeline import modules

    cd, _, _ = modules()
    fixtures = _fixtures_ligue_saison(cd, league_id, season)
    matchs, appels_stats = [], 0
    for fx in fixtures:
        statut = ((fx.get("fixture") or {}).get("status") or {}).get("short")
        peut_stats = avec_stats and statut in STATUTS_TERMINES and (limite_appels_stats is None or appels_stats < limite_appels_stats)
        matchs.append(fixture_vers_match(fx, cd, avec_stats=peut_stats))
        if peut_stats:
            appels_stats += 1
    n = upsert_matchs(db, matchs)
    termines = sum(1 for m in matchs if m["statut"] in STATUTS_TERMINES)
    avec_stats_n = sum(1 for m in matchs if m.get("stats"))
    print(f"   ✓ Ligue {league_id}, saison {season} : {n} match(s) enregistré(s) "
          f"({termines} terminé(s), {avec_stats_n} avec statistiques).")
    return {"ligue": league_id, "saison": season, "matchs": n, "termines": termines, "avec_stats": avec_stats_n}


def charger_matchs(db, competition_id=None, saisons=None):
    """Relit la base -> liste de dicts au format moteur.features, pour moteur.backtest.executer."""
    requete = select(HistMatch)
    if competition_id is not None:
        requete = requete.where(HistMatch.competition_id == competition_id)
    if saisons:
        requete = requete.where(HistMatch.saison.in_(saisons))
    return [m.vers_dict() for m in db.scalars(requete)]
