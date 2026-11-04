"""Phase 4 — base historique Football-Data (5 championnats, ~10 saisons) : import INSERT-ONLY + contrôles de qualité mesurés.
Une requête par fichier (pause, User-Agent déclaré), une seule passe ; les saisons terminées ne sont jamais modifiées."""
import csv
import hashlib
import io
import time
import urllib.request
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models_historique import FdMatch

URL = "https://www.football-data.co.uk/mmz4281/{saison}/{ligue}.csv"
LIGUES = ["E0", "F1", "D1", "I1", "SP1"]
SAISONS = ["1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425", "2526", "2627"]
UA = "analyse-football-phase4/1.0 (recherche, 1 appel par fichier)"
STATS = ["HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"]
# bookmaker -> préfixes de colonnes (Pinnacle : PS puis PP selon les saisons)
BK = {"pin": ("PS", "PP"), "b365": ("B365",), "moy": ("Avg",), "max": ("Max",)}


def telecharger(saison, ligue, essais=3):
    url = URL.format(saison=saison, ligue=ligue)
    derniere = None
    for i in range(essais):
        try:
            time.sleep(0.5)
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return url, r.read()
        except Exception as e:  # noqa: BLE001
            derniere = e
            time.sleep(2 * (i + 1))
    raise derniere


def decoder(brut):
    try:
        t = brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        t = brut.decode("latin-1")
    return t.lstrip("﻿").replace("ï»¿", "")


def _num(row, *cols):
    for c in cols:
        try:
            v = float(row.get(c, "") or "nan")
        except ValueError:
            continue
        if v == v:
            return v
    return None


def _cote(row, *cols):
    v = _num(row, *cols)
    return v if v is not None and v > 1.0 else None


def extraire_cotes(row):
    """Cotes d'ouverture ('ouv') et de clôture ('clo') par bookmaker et marché ; listes complètes uniquement."""
    out = {}
    for nom, pref in BK.items():
        for suffixe, tag in (("", "ouv"), ("C", "clo")):
            h3 = [_cote(row, *[f"{p}{suffixe}{x}" for p in pref]) for x in ("H", "D", "A")]
            if all(h3):
                out[f"{nom}_1x2_{tag}"] = h3
    # Over/Under 2,5 : ouverture « P>2.5 » (Pinnacle), « B365>2.5 », « Avg>2.5 », « Max>2.5 » ; clôture « PC>2.5 », « B365C>2.5 »...
    ou = {"pin": (("P>2.5", "PP>2.5"), ("P<2.5", "PP<2.5"), ("PC>2.5", "PPC>2.5"), ("PC<2.5", "PPC<2.5")),
          "b365": (("B365>2.5",), ("B365<2.5",), ("B365C>2.5",), ("B365C<2.5",)),
          "moy": (("Avg>2.5",), ("Avg<2.5",), ("AvgC>2.5",), ("AvgC<2.5",)),
          "max": (("Max>2.5",), ("Max<2.5",), ("MaxC>2.5",), ("MaxC<2.5",))}
    for nom, (oo, uo, oc, uc) in ou.items():
        for o, u, tag in ((oo, uo, "ouv"), (oc, uc, "clo")):
            a, b = _cote(row, *o), _cote(row, *u)
            if a and b:
                out[f"{nom}_ou25_{tag}"] = [a, b]
    ah = {"pin": (("PAHH", "PPAHH"), ("PAHA", "PPAHA"), ("PCAHH", "PPCAHH"), ("PCAHA", "PPCAHA")),
          "b365": (("B365AHH",), ("B365AHA",), ("B365CAHH",), ("B365CAHA",)),
          "moy": (("AvgAHH",), ("AvgAHA",), ("AvgCAHH",), ("AvgCAHA",)),
          "max": (("MaxAHH",), ("MaxAHA",), ("MaxCAHH",), ("MaxCAHA",))}
    for nom, (ho, ao, hc, ac) in ah.items():
        for h, a, tag in ((ho, ao, "ouv"), (hc, ac, "clo")):
            x, y = _cote(row, *h), _cote(row, *a)
            if x and y:
                out[f"{nom}_ah_{tag}"] = [x, y]
    for cle, col in (("ah_ligne_ouv", "AHh"), ("ah_ligne_clo", "AHCh")):
        v = _num(row, col)
        if v is not None:
            out[cle] = v
    return out


def lignes(texte, ligue, saison):
    """Lignes de matchs terminés (score connu) prêtes à insérer."""
    out = []
    for row in csv.DictReader(io.StringIO(texte)):
        row = {(k or "").strip(): v for k, v in row.items()}
        try:
            d = row["Date"]
            dt = datetime.strptime(d, "%d/%m/%Y" if len(d) == 10 else "%d/%m/%y").date()
            gd, ge = int(row["FTHG"]), int(row["FTAG"])
        except (KeyError, ValueError):
            continue
        if not row.get("HomeTeam") or not row.get("AwayTeam"):
            continue
        st = {k: int(float(row[k])) for k in STATS if row.get(k) not in (None, "") and _num(row, k) is not None}
        out.append({"ligue": ligue, "saison": saison, "date_match": dt, "domicile": row["HomeTeam"].strip(),
                    "exterieur": row["AwayTeam"].strip(), "buts_dom": gd, "buts_ext": ge,
                    "mt_dom": int(_num(row, "HTHG")) if _num(row, "HTHG") is not None else None,
                    "mt_ext": int(_num(row, "HTAG")) if _num(row, "HTAG") is not None else None,
                    "arbitre": (row.get("Referee") or None), "stats": st or None, "cotes": extraire_cotes(row) or None})
    return out


def importer_fichier(db, ligue, saison, brut, url):
    """Insert-only : retourne (ajoutes, existants, lignes_lues)."""
    h = hashlib.sha256(brut).hexdigest()
    ls = lignes(decoder(brut), ligue, saison)
    connus = {(r.date_match, r.domicile, r.exterieur) for r in db.execute(
        select(FdMatch.date_match, FdMatch.domicile, FdMatch.exterieur).where(FdMatch.ligue == ligue, FdMatch.saison == saison))}
    ajoutes = 0
    vus = set()
    for l in ls:
        k = (l["date_match"], l["domicile"], l["exterieur"])
        if k in connus or k in vus:
            continue
        vus.add(k)
        db.add(FdMatch(url_source=url, hash_fichier=h, collecte_le=datetime.now(timezone.utc), **l))
        ajoutes += 1
    db.commit()
    return ajoutes, len(ls) - ajoutes, len(ls)


def importer(db, saisons=None, ligues=None, telecharge=telecharger):
    cr = {"fichiers": 0, "ajoutes": 0, "existants": 0, "echecs": []}
    for saison in saisons or SAISONS:
        for ligue in ligues or LIGUES:
            try:
                url, brut = telecharge(saison, ligue)
                a, e, _ = importer_fichier(db, ligue, saison, brut, url)
                cr["fichiers"] += 1
                cr["ajoutes"] += a
                cr["existants"] += e
            except Exception as ex:  # noqa: BLE001 — un fichier absent (saison non publiée) est rapporté, pas fatal
                db.rollback()
                cr["echecs"].append(f"{ligue} {saison}: {str(ex)[:60]}")
    return cr


def _marge(c):
    return sum(1 / x for x in c) - 1


def rapport_qualite(db):
    """Qualité mesurée : couverture par ligue/saison, scores/statistiques, cotes (marge, valeurs aberrantes)."""
    par = {}
    for m in db.execute(select(FdMatch)).scalars():
        r = par.setdefault((m.ligue, m.saison), {"n": 0, "pin1x2_clo": 0, "pin1x2_ouv": 0, "ou_clo": 0, "ah_clo": 0, "tirs": 0, "corners": 0,
                                                 "cartons": 0, "marges": [], "aberrantes": 0, "hors_saison": 0})
        r["n"] += 1
        c = m.cotes or {}
        r["pin1x2_clo"] += "pin_1x2_clo" in c
        r["pin1x2_ouv"] += "pin_1x2_ouv" in c
        r["ou_clo"] += any(k.endswith("_ou25_clo") for k in c)
        r["ah_clo"] += any(k.endswith("_ah_clo") for k in c)
        s = m.stats or {}
        r["tirs"] += "HS" in s and "AS" in s
        r["corners"] += "HC" in s and "AC" in s
        r["cartons"] += "HY" in s and "AY" in s
        if "pin_1x2_clo" in c:
            r["marges"].append(_marge(c["pin_1x2_clo"]))
        r["aberrantes"] += any(isinstance(v, list) and any(x < 1.01 or x > 250 for x in v) for v in c.values())
        debut = int("20" + m.saison[:2])
        r["hors_saison"] += not (date(debut, 7, 1) <= m.date_match <= date(debut + 1, 7, 31))
    out = []
    for (lg, sa), r in sorted(par.items()):
        mg = r["marges"]
        out.append({"ligue": lg, "saison": sa, "matchs": r["n"], "pin_1x2_cloture_%": round(100 * r["pin1x2_clo"] / r["n"]),
                    "pin_1x2_ouverture_%": round(100 * r["pin1x2_ouv"] / r["n"]), "ou25_cloture_%": round(100 * r["ou_clo"] / r["n"]),
                    "ah_cloture_%": round(100 * r["ah_clo"] / r["n"]), "tirs_%": round(100 * r["tirs"] / r["n"]),
                    "corners_%": round(100 * r["corners"] / r["n"]), "cartons_%": round(100 * r["cartons"] / r["n"]),
                    "marge_pin_moy_%": round(100 * sum(mg) / len(mg), 2) if mg else None,
                    "cotes_aberrantes": r["aberrantes"], "dates_hors_saison": r["hors_saison"]})
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.database import SessionLocal, init_db
    from app.services import sources

    from sqlalchemy.exc import OperationalError
    for essai in range(1, 5):               # verrous possibles avec un autre job : nouvelle tentative
        try:
            init_db()
            break
        except OperationalError as e:
            print(f"init_db tentative {essai}/4 : {str(e)[:100]}")
            if essai == 4:
                raise
            time.sleep(10 * essai)
    with SessionLocal() as session:
        sources.initialiser(session)
        sources.exiger_autorisation(session, "football-data")
        if len(sys.argv) < 2 or sys.argv[1] == "importer":
            print("import :", importer(session))
        for l in rapport_qualite(session):
            print(l)
