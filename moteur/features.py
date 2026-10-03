"""Features chronologiques. RÈGLE ABSOLUE : pour un match au coup d'envoi t, seules les données
de matchs TERMINÉS dont le coup d'envoi est STRICTEMENT antérieur à t sont utilisées (jamais le
score, les corners, cartons, tirs... du match lui-même, ni d'un match postérieur). Vérifié par
test_features.TestAucuneFuite, qui modifie le match et tout le futur puis exige des features
identiques.

Format d'un match (dict) :
    match_id, date (datetime tz-aware ou ISO), competition_id, competition, saison,
    home_id, home, away_id, away, home_score, away_score, arbitre (optionnel),
    stats (optionnel) = {"home": {corners, yellow_cards, red_cards, shots, shots_on_target,
                                  fouls, possession, xg}, "away": {...}}
"""

import bisect
from datetime import datetime, timezone

STATS_COMPTAGE = ("corners", "yellow_cards", "shots", "shots_on_target", "fouls")
VERSION_FEATURES = "1.0.0"
ELO_DEPART = 1500.0
ELO_K = 20.0
ELO_AVANTAGE_DOMICILE = 60.0


def en_datetime(valeur):
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def est_termine(m):
    return m.get("home_score") is not None and m.get("away_score") is not None


def _moyenne(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    return sum(valeurs) / len(valeurs) if valeurs else None


class Historique:
    """Index chronologique des matchs terminés, par équipe et par compétition. Toutes les
    requêtes prennent une date de référence et ne renvoient QUE ce qui la précède."""

    def __init__(self, matchs):
        termines = sorted((m for m in matchs if est_termine(m)), key=lambda m: en_datetime(m["date"]))
        self._par_equipe, self._par_competition, self._par_arbitre = {}, {}, {}
        for m in termines:
            t = en_datetime(m["date"])
            stats = m.get("stats") or {}
            for cote, adverse in (("home", "away"), ("away", "home")):
                vue = {
                    "date": t, "match_id": m["match_id"], "domicile": cote == "home",
                    "buts_pour": m[f"{cote}_score"], "buts_contre": m[f"{adverse}_score"],
                    "stats_pour": stats.get(cote) or {}, "stats_contre": stats.get(adverse) or {},
                }
                self._par_equipe.setdefault(m[f"{cote}_id"], []).append(vue)
            self._par_competition.setdefault(m.get("competition_id"), []).append((t, m))
            if m.get("arbitre"):
                self._par_arbitre.setdefault(m["arbitre"], []).append((t, m))
        self._dates_equipe = {k: [v["date"] for v in vues] for k, vues in self._par_equipe.items()}
        self._dates_competition = {k: [t for t, _ in v] for k, v in self._par_competition.items()}
        self._dates_arbitre = {k: [t for t, _ in v] for k, v in self._par_arbitre.items()}
        self.elo_avant = self._calculer_elo(termines)

    def equipe_avant(self, equipe_id, t, n=None, domicile=None):
        vues = self._par_equipe.get(equipe_id, [])
        fin = bisect.bisect_left(self._dates_equipe.get(equipe_id, []), t)  # strictement avant t
        retenues = vues[:fin]
        if domicile is not None:
            retenues = [v for v in retenues if v["domicile"] == domicile]
        return retenues[-n:] if n else retenues

    def competition_avant(self, competition_id, t, n=380):
        fin = bisect.bisect_left(self._dates_competition.get(competition_id, []), t)
        return [m for _, m in self._par_competition.get(competition_id, [])[max(0, fin - n):fin]]

    def arbitre_avant(self, arbitre, t, n=30):
        if not arbitre:
            return []
        fin = bisect.bisect_left(self._dates_arbitre.get(arbitre, []), t)
        return [m for _, m in self._par_arbitre.get(arbitre, [])[max(0, fin - n):fin]]

    @staticmethod
    def _calculer_elo(termines):
        """Elo AVANT chaque match (mis à jour seulement après) : jamais de fuite."""
        elo, avant = {}, {}
        for m in termines:
            h, a = elo.get(m["home_id"], ELO_DEPART), elo.get(m["away_id"], ELO_DEPART)
            avant[m["match_id"]] = (h, a)
            attendu = 1 / (1 + 10 ** ((a - h - ELO_AVANTAGE_DOMICILE) / 400))
            reel = 1.0 if m["home_score"] > m["away_score"] else 0.5 if m["home_score"] == m["away_score"] else 0.0
            ecart = abs(m["home_score"] - m["away_score"])
            k = ELO_K * (1 + ecart) ** 0.5
            elo[m["home_id"]] = h + k * (reel - attendu)
            elo[m["away_id"]] = a - k * (reel - attendu)
        avant["_courant"] = elo
        return avant

    def elo(self, match):
        if match["match_id"] in self.elo_avant:
            return self.elo_avant[match["match_id"]]
        courant = self.elo_avant["_courant"]
        # Match futur (prédiction) : Elo courant = après le dernier match connu, toujours < t
        # puisque l'historique ne contient que des matchs terminés.
        return courant.get(match["home_id"], ELO_DEPART), courant.get(match["away_id"], ELO_DEPART)


def _profil_equipe(hist, equipe_id, t, fenetre):
    vues = hist.equipe_avant(equipe_id, t)
    profil = {"n_matchs": len(vues)}
    for n in (3, 5, 10):
        derniers = vues[-n:]
        profil[f"buts_pour_moy_{n}"] = _moyenne([v["buts_pour"] for v in derniers])
        profil[f"buts_contre_moy_{n}"] = _moyenne([v["buts_contre"] for v in derniers])
    derniers = vues[-fenetre:]
    profil["points_par_match"] = _moyenne([3 if v["buts_pour"] > v["buts_contre"] else 1 if v["buts_pour"] == v["buts_contre"] else 0
                                           for v in derniers])
    for dom, nom in ((True, "dom"), (False, "ext")):
        sous = hist.equipe_avant(equipe_id, t, fenetre, domicile=dom)
        profil[f"buts_pour_moy_{nom}"] = _moyenne([v["buts_pour"] for v in sous])
        profil[f"buts_contre_moy_{nom}"] = _moyenne([v["buts_contre"] for v in sous])
    avec_stats = [v for v in vues if v["stats_pour"]][-fenetre:]
    profil["n_matchs_stats"] = len(avec_stats)
    for stat in STATS_COMPTAGE:
        profil[f"{stat}_pour_moy"] = _moyenne([v["stats_pour"].get(stat) for v in avec_stats])
        profil[f"{stat}_contre_moy"] = _moyenne([v["stats_contre"].get(stat) for v in avec_stats])
    profil["xg_pour_moy"] = _moyenne([v["stats_pour"].get("xg") for v in avec_stats])
    profil["xg_contre_moy"] = _moyenne([v["stats_contre"].get("xg") for v in avec_stats])
    profil["fenetre_buts_pour"] = [v["buts_pour"] for v in derniers]
    profil["fenetre_buts_contre"] = [v["buts_contre"] for v in derniers]
    return profil


def _moyennes_ligue(hist, competition_id, t):
    matchs = hist.competition_avant(competition_id, t)
    moy = {"n_matchs": len(matchs),
           "buts_dom": _moyenne([m["home_score"] for m in matchs]),
           "buts_ext": _moyenne([m["away_score"] for m in matchs])}
    for stat in STATS_COMPTAGE:
        valeurs = [((m.get("stats") or {}).get(c) or {}).get(stat) for m in matchs for c in ("home", "away")]
        valeurs = [v for v in valeurs if v is not None]
        moy[f"{stat}_par_equipe"] = _moyenne(valeurs)
        moy[f"{stat}_variance_par_equipe"] = (
            sum((v - moy[f"{stat}_par_equipe"]) ** 2 for v in valeurs) / (len(valeurs) - 1) if len(valeurs) > 1 else None)
    return moy


def construire_features(match, hist, fenetre=10):
    t = en_datetime(match["date"])
    home = _profil_equipe(hist, match["home_id"], t, fenetre)
    away = _profil_equipe(hist, match["away_id"], t, fenetre)
    ligue = _moyennes_ligue(hist, match.get("competition_id"), t)
    elo_h, elo_a = hist.elo(match)
    arbitre = hist.arbitre_avant(match.get("arbitre"), t)
    cartons_arbitre = _moyenne([sum(((m.get("stats") or {}).get(c) or {}).get("yellow_cards") or 0 for c in ("home", "away"))
                                for m in arbitre if m.get("stats")])
    f = {
        "match_id": match["match_id"], "date": t, "version_features": VERSION_FEATURES,
        "home": home, "away": away, "ligue": ligue,
        "elo_home": elo_h, "elo_away": elo_a, "elo_difference": elo_h - elo_a,
        "arbitre_n": len(arbitre), "arbitre_cartons_moy": cartons_arbitre,
    }
    for n in (3, 5, 10):
        if home[f"buts_pour_moy_{n}"] is not None and away[f"buts_pour_moy_{n}"] is not None:
            f[f"difference_buts_{n}"] = ((home[f"buts_pour_moy_{n}"] - home[f"buts_contre_moy_{n}"])
                                         - (away[f"buts_pour_moy_{n}"] - away[f"buts_contre_moy_{n}"]))
    for stat in STATS_COMPTAGE:
        if home[f"{stat}_pour_moy"] is not None and away[f"{stat}_pour_moy"] is not None:
            f[f"difference_{stat}"] = home[f"{stat}_pour_moy"] - away[f"{stat}_pour_moy"]
    return f
