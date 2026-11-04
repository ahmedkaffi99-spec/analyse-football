"""Phase 2 — capture régulière de cotes GRATUITES (aucune dépense, aucun quota API) : fixtures.csv de Football-Data.co.uk
liste les prochains matchs des championnats suivis avec les cotes de plusieurs bookmakers. Série temporelle en
« changement seulement » : une valeur n'est insérée que si elle diffère de la dernière observation (aucun doublon,
historique conservé, jamais d'UPDATE ni de DELETE). Chaque tentative est journalisée (ok / vide / erreur) ;
une capture vide ou en erreur fait échouer le processus (jamais de succès silencieux)."""
import csv
import hashlib
import io
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

from app.models_historique import CaptureGratuiteJournal, CoteGratuite

URL = "https://www.football-data.co.uk/fixtures.csv"
LIGUES = {"E0", "F1", "D1", "I1", "SP1"}
# (bookmaker, marché, sélection, colonne CSV)
COLONNES = [(bk, "1x2", s, f"{bk}{c}") for bk in ("B365", "PS", "Avg", "Max") for s, c in (("1", "H"), ("X", "D"), ("2", "A"))] + [
    ("B365", "ou25", "O", "B365>2.5"), ("B365", "ou25", "U", "B365<2.5"),
    ("PS", "ou25", "O", "P>2.5"), ("PS", "ou25", "U", "P<2.5"),
    ("Avg", "ou25", "O", "Avg>2.5"), ("Avg", "ou25", "U", "Avg<2.5"),
    ("PS", "ah", "H", "PAHH"), ("PS", "ah", "A", "PAHA"),
    ("B365", "ah", "H", "B365AHH"), ("B365", "ah", "A", "B365AHA")]
CLE = ("ligue", "date_match", "domicile", "exterieur", "bookmaker", "marche", "selection")


def telecharger():
    """(octets bruts) — l'appelant décode ; User-Agent déclaré, un seul appel."""
    req = urllib.request.Request(URL, headers={"User-Agent": "analyse-football-phase2/1.0 (cotes gratuites, 1 appel/6 h)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def decoder(brut):
    """Décode en retirant l'éventuel BOM UTF-8 (sinon la première colonne s'appelle « ï»¿Div » et AUCUNE ligne n'est lue)."""
    try:
        t = brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        t = brut.decode("latin-1")
    return t.lstrip("﻿").replace("ï»¿", "")


def _nombre(v):
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def lire_csv(texte):
    """Lignes de matchs des ligues suivies (clés d'en-tête nettoyées) — sans interpréter les cotes."""
    return [{(k or "").strip(): v for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(texte)) if (row.get("Div") or "").strip() in LIGUES]


def lignes_depuis_csv(texte, instant, url=URL, hash_fichier=None):
    out = []
    for row in lire_csv(texte):
        if not row.get("HomeTeam"):
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
            ligne = None
            if marche == "ou25":
                ligne = 2.5
            elif marche == "ah":
                try:
                    v = float(row.get("AHh") or "nan")
                    ligne = None if v != v else v
                except ValueError:
                    ligne = None
            out.append({"capture_le": instant, "ligue": row["Div"].strip(), "date_match": date_match,
                        "domicile": row["HomeTeam"], "exterieur": row["AwayTeam"], "bookmaker": bk,
                        "marche": marche, "ligne": ligne, "selection": sel, "cote": cote,
                        "url_source": url, "hash_fichier": hash_fichier})
    return out


def _cle(l):
    return tuple(l[c] for c in CLE) + (l.get("ligne"),)


def dernieres_valeurs(db, lignes):
    """{clé: (cote, ligne)} de la DERNIÈRE observation connue pour les matchs du fichier."""
    dates = {l["date_match"] for l in lignes}
    if not dates:
        return {}
    res = {}
    q = select(CoteGratuite).where(CoteGratuite.date_match.in_(dates)).order_by(CoteGratuite.capture_le)
    for r in db.execute(q).scalars():
        res[tuple(getattr(r, c) for c in CLE)] = (r.cote, r.ligne)
    return res


def enregistrer(db, lignes):
    """Insère uniquement les valeurs nouvelles/modifiées. Retourne (insérées, inchangées)."""
    connues = dernieres_valeurs(db, lignes)
    nouvelles, inchangees = [], 0
    for l in lignes:
        k = tuple(l[c] for c in CLE)
        if k in connues and connues[k] == (l["cote"], l["ligne"]):
            inchangees += 1
        else:
            nouvelles.append(l)
    for i in range(0, len(nouvelles), 500):
        db.add_all([CoteGratuite(**l) for l in nouvelles[i:i + 500]])
    db.commit()
    return len(nouvelles), inchangees


def assurer_colonnes(db):
    """Tables créées avant l'ajout des colonnes de provenance : ajout idempotent (PostgreSQL), sans toucher aux données."""
    if db.bind.dialect.name == "postgresql":
        for col, typ in (("url_source", "VARCHAR(200)"), ("hash_fichier", "VARCHAR(64)")):
            db.execute(text(f"ALTER TABLE cotes_gratuites ADD COLUMN IF NOT EXISTS {col} {typ}"))
        db.commit()


def capturer(db, brut=None):
    """Une tentative complète ; toujours journalisée. Retourne le journal (statut ok | vide | erreur)."""
    j = CaptureGratuiteJournal(debut=datetime.now(timezone.utc), statut="erreur", url_source=URL)
    db.add(j)
    db.commit()
    try:
        brut = brut if brut is not None else telecharger()
        j.octets, j.hash_fichier = len(brut), hashlib.sha256(brut).hexdigest()
        texte = decoder(brut)
        lignes_csv = lire_csv(texte)
        j.lignes_csv = len(lignes_csv)
        lignes = lignes_depuis_csv(texte, j.debut, URL, j.hash_fichier)
        j.cotes_lues = len(lignes)
        j.matchs = len({(l["ligue"], l["date_match"], l["domicile"], l["exterieur"]) for l in lignes})
        if not lignes:
            tous = list(csv.DictReader(io.StringIO(texte)))
            divs = sorted({(r.get("Div") or "").strip() for r in tous})
            dates = sorted({(r.get("Date") or "") for r in tous})[:6]
            j.statut = "vide"
            j.erreur = (f"aucune cote lue pour {sorted(LIGUES)} : fichier de {len(tous)} matchs, championnats présents {divs}, "
                        f"dates {dates}")[:500]
        else:
            j.inserees, j.inchangees = enregistrer(db, lignes)
            j.statut = "ok"
    except Exception as e:  # noqa: BLE001 — journalisé puis relevé par l'appelant (exit non nul)
        db.rollback()
        j.statut, j.erreur = "erreur", f"{type(e).__name__}: {e}"[:500]
    j.fin = datetime.now(timezone.utc).replace(microsecond=0)
    db.merge(j)
    db.commit()
    return j


if __name__ == "__main__":
    RACINE = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(RACINE / "backend"))
    from app.database import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        assurer_colonnes(session)
        journal = capturer(session)
        print(f"Capture gratuite : statut={journal.statut} octets={journal.octets} lignes_csv={journal.lignes_csv} "
              f"matchs={journal.matchs} cotes_lues={journal.cotes_lues} inserees={journal.inserees} "
              f"inchangees={journal.inchangees} hash={str(journal.hash_fichier)[:12]} erreur={journal.erreur}")
    sys.exit(0 if journal.statut == "ok" else 1)
