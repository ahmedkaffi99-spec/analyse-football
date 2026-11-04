"""Phase 2 — capture régulière de cotes GRATUITES (aucune dépense, aucun quota API) : fixtures.csv de Football-Data.co.uk
liste les prochains matchs des championnats suivis avec les cotes de plusieurs bookmakers. Chaque passage ajoute un
instantané horodaté (série temporelle) ; les cotes de clôture réelles arrivent ensuite dans les CSV de résultats
(bet_agent/phase2_comparaison.py), ce qui permet de mesurer ouverture -> clôture."""
import csv
import io
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models_historique import CoteGratuite

URL = "https://www.football-data.co.uk/fixtures.csv"
LIGUES = {"E0", "F1", "D1", "I1", "SP1"}
# (bookmaker, marché, sélection, colonne CSV)
COLONNES = [(bk, "1x2", s, f"{bk}{c}") for bk in ("B365", "PS", "Avg", "Max") for s, c in (("1", "H"), ("X", "D"), ("2", "A"))] + [
    ("B365", "ou25", "O", "B365>2.5"), ("B365", "ou25", "U", "B365<2.5"),
    ("PS", "ou25", "O", "P>2.5"), ("PS", "ou25", "U", "P<2.5"),
    ("Avg", "ou25", "O", "Avg>2.5"), ("Avg", "ou25", "U", "Avg<2.5"),
    ("PS", "ah", "H", "PAHH"), ("PS", "ah", "A", "PAHA"),
    ("B365", "ah", "H", "B365AHH"), ("B365", "ah", "A", "B365AHA")]


def telecharger():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("latin-1")


def _nombre(v):
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def lignes_depuis_csv(texte, instant):
    """CSV -> lignes prêtes à insérer (cotes valides uniquement)."""
    out = []
    for row in csv.DictReader(io.StringIO(texte)):
        if row.get("Div") not in LIGUES or not row.get("HomeTeam"):
            continue
        try:
            d = row["Date"]
            date_match = datetime.strptime(d, "%d/%m/%Y" if len(d) == 10 else "%d/%m/%y").date()
        except (KeyError, ValueError):
            continue
        for bk, marche, sel, col in COLONNES:
            cote = _nombre(row.get(col))
            if cote is None:
                continue
            ligne = _nombre(row.get("AHh")) if marche == "ah" else (2.5 if marche == "ou25" else None)
            if marche == "ah":  # la ligne peut être négative : on relit sans le filtre > 1
                try:
                    ligne = float(row.get("AHh") or "nan")
                    ligne = None if ligne != ligne else ligne
                except ValueError:
                    ligne = None
            out.append({"capture_le": instant, "ligue": row["Div"], "date_match": date_match,
                        "domicile": row["HomeTeam"], "exterieur": row["AwayTeam"], "bookmaker": bk,
                        "marche": marche, "ligne": ligne, "selection": sel, "cote": cote})
    return out


def enregistrer(db, lignes):
    """Insertion idempotente (contrainte d'unicité) ; retourne le nombre de lignes soumises."""
    if not lignes:
        return 0
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    for i in range(0, len(lignes), 500):
        db.execute(insert(CoteGratuite).values(lignes[i:i + 500]).on_conflict_do_nothing())
    db.commit()
    return len(lignes)


def capturer(db, texte=None):
    instant = datetime.now(timezone.utc).replace(microsecond=0)
    lignes = lignes_depuis_csv(texte if texte is not None else telecharger(), instant)
    return enregistrer(db, lignes), len({(l["ligue"], l["date_match"], l["domicile"]) for l in lignes})


if __name__ == "__main__":
    RACINE = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(RACINE / "backend"))
    from app.database import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        n, matchs = capturer(session)
    print(f"Capture gratuite : {n} cotes pour {matchs} match(s).")
