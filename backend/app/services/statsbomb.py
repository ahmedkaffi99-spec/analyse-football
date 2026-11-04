"""StatsBomb Open Data — intégration (Phase 3). Source ouverte et gratuite, publiée sur GitHub ; conditions : citer StatsBomb comme
source (et son logo en cas de publication) — la mention figure dans la provenance de chaque ligne. Couverture limitée aux saisons
publiées par StatsBomb (aucune saison en cours) : donnée de RECHERCHE (modèle xG, calibration, forces d'équipes), pas de prédiction du jour.
Collecte courtoise (pause entre fichiers, plafond de matchs, jamais deux fois le même match)."""
import hashlib
import json
import time
import urllib.request
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models_historique import SbMatch, SbTir

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
UA = "analyse-football-phase3/1.0 (recherche, faible volume)"
PAUSE_S = 0.3


def telecharger(url, essais=3):
    """(octets bruts) avec ré-essais ; lève la dernière erreur."""
    derniere = None
    for i in range(essais):
        try:
            time.sleep(PAUSE_S)
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            derniere = e
            time.sleep(2 * (i + 1))
    raise derniere


def competitions(telecharge=telecharger):
    return json.loads(telecharge(f"{BASE}/competitions.json"))


def matchs_competition(competition_id, saison_id, telecharge=telecharger):
    url = f"{BASE}/matches/{competition_id}/{saison_id}.json"
    return url, json.loads(telecharge(url))


def analyser_evenements(evenements, equipe_dom, equipe_ext):
    """Tirs + buts reconstitués + xG par équipe à partir de la liste d'événements d'un match. Les tirs de la séance de tirs au but
    (période 5) sont exclus du xG et des buts du match."""
    tirs, buts = [], {equipe_dom: 0, equipe_ext: 0}
    xg = {equipe_dom: 0.0, equipe_ext: 0.0}
    nb = {equipe_dom: 0, equipe_ext: 0}
    for e in evenements:
        t = (e.get("type") or {}).get("name")
        equipe = (e.get("team") or {}).get("name")
        if e.get("period") == 5:
            continue
        if t == "Own Goal For" and equipe in buts:
            buts[equipe] += 1
        if t != "Shot":
            continue
        s = e.get("shot") or {}
        loc = e.get("location") or [None, None]
        tirs.append({"tir_id": e.get("id"), "equipe": equipe, "joueur": (e.get("player") or {}).get("name"),
                     "periode": e.get("period"), "minute": e.get("minute"), "xg": s.get("statsbomb_xg"),
                     "resultat": (s.get("outcome") or {}).get("name"), "type_tir": (s.get("type") or {}).get("name"),
                     "partie_corps": (s.get("body_part") or {}).get("name"), "x": loc[0], "y": loc[1]})
        if equipe in buts:
            nb[equipe] += 1
            xg[equipe] += s.get("statsbomb_xg") or 0.0
            if (s.get("outcome") or {}).get("name") == "Goal":
                buts[equipe] += 1
    return tirs, buts, xg, nb


def importer_match(db, meta, telecharge=telecharger):
    """Importe un match (déjà présent : ignoré). Retourne 'ajoute' | 'existant'."""
    mid = meta["match_id"]
    if db.get(SbMatch, mid) is not None:
        return "existant"
    url = f"{BASE}/events/{mid}.json"
    brut = telecharge(url)
    h = hashlib.sha256(brut).hexdigest()
    dom, ext = meta["home_team"]["home_team_name"], meta["away_team"]["away_team_name"]
    tirs, buts, xg, nb = analyser_evenements(json.loads(brut), dom, ext)
    coherent = None if meta.get("home_score") is None else (buts[dom] == meta["home_score"] and buts[ext] == meta["away_score"])
    db.add(SbMatch(
        match_id=mid, competition_id=meta["competition"]["competition_id"], saison_id=meta["season"]["season_id"],
        competition=meta["competition"].get("competition_name"), saison=meta["season"].get("season_name"),
        date_match=date.fromisoformat(meta["match_date"]) if meta.get("match_date") else None,
        domicile=dom, exterieur=ext, buts_dom=meta.get("home_score"), buts_ext=meta.get("away_score"),
        xg_dom=round(xg[dom], 3), xg_ext=round(xg[ext], 3), tirs_dom=nb[dom], tirs_ext=nb[ext], coherent=coherent,
        url_source=url, hash_fichier=h, collecte_le=datetime.now(timezone.utc)))
    for t in tirs:
        if t["tir_id"] and db.get(SbTir, t["tir_id"]) is None:
            db.add(SbTir(match_id=mid, url_source=url, hash_fichier=h, **t))
    db.commit()
    return "ajoute"


def importer(db, competition_id, saison_id, max_matchs=30, telecharge=telecharger):
    """Importe jusqu'à `max_matchs` nouveaux matchs d'une compétition/saison. Retourne un compte rendu."""
    _, matchs = matchs_competition(competition_id, saison_id, telecharge)
    cr = {"matchs_disponibles": len(matchs), "ajoutes": 0, "existants": 0, "erreurs": []}
    for meta in sorted(matchs, key=lambda m: m.get("match_date") or ""):
        if cr["ajoutes"] >= max_matchs:
            break
        try:
            cr["ajoutes" if importer_match(db, meta, telecharge) == "ajoute" else "existants"] += 1
        except Exception as e:  # noqa: BLE001 — un fichier en échec ne bloque pas les autres, il est rapporté
            db.rollback()
            cr["erreurs"].append(f"{meta.get('match_id')}: {str(e)[:80]}")
    return cr


def controle_qualite(db, competition_id=None):
    """Cohérence des données importées : buts reconstitués = score, rapport xG/buts, matchs sans tirs."""
    q = select(SbMatch)
    if competition_id:
        q = q.where(SbMatch.competition_id == competition_id)
    ms = list(db.execute(q).scalars())
    if not ms:
        return {"matchs": 0}
    ok = sum(1 for m in ms if m.coherent)
    verifiables = sum(1 for m in ms if m.coherent is not None)
    xg = sum((m.xg_dom or 0) + (m.xg_ext or 0) for m in ms)
    buts = sum((m.buts_dom or 0) + (m.buts_ext or 0) for m in ms)
    return {"matchs": len(ms), "scores_coherents": f"{ok}/{verifiables}", "xg_total": round(xg, 1), "buts_total": buts,
            "ratio_buts_sur_xg": round(buts / xg, 3) if xg else None, "sans_tirs": sum(1 for m in ms if not (m.tirs_dom or m.tirs_ext))}


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.database import SessionLocal, init_db
    from app.services import sources

    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "couverture"
    with SessionLocal() as session:
        sources.initialiser(session)
        sources.exiger_autorisation(session, "statsbomb")          # garde-fou juridique du registre
        if cmd == "couverture":
            for c in sorted(competitions(), key=lambda r: (r["competition_name"], r["season_name"])):
                if c["competition_gender"] == "male" and not c["competition_youth"]:
                    print(f"{c['competition_id']:>5} {c['season_id']:>4} {c['competition_name']} {c['season_name']}")
        elif cmd == "importer":
            cid, sid, n = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 30
            print("import :", importer(session, cid, sid, n))
            print("contrôle :", controle_qualite(session, cid))
