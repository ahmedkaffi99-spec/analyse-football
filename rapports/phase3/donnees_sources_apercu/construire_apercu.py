"""Recalcule, sur une base SQLite LOCALE temporaire, les études des 5 jours à partir des seuls coupons envoyés (données de ce dossier,
extraites en SELECT le 07/11/2026). N'écrit jamais en base de production. Usage : python construire_apercu.py  (depuis backend/ avec DATABASE_URL=sqlite:///...)"""
import json, os, sys
from datetime import date, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "backend"))
from app.database import SessionLocal, init_db
from app.models import Run, Coupon, Jambe
from app.services import apprentissage as ap

JOURS = ("2026-11-04", "2026-10-28", "2026-10-25", "2026-10-24", "2026-10-23")

def charger(db):
    runs, cps = {}, {}
    for l in open(os.path.join(HERE, "coupons.txt"), encoding="utf-8"):
        cid, jour, nom, statut, cote, run = l.rstrip("\n").split("|")
        if run not in runs:
            r = Run(source="api", statut="termine", envoye_telegram=True, lance_le=datetime.fromisoformat(jour + "T08:00:00+00:00"))
            db.add(r); db.flush(); runs[run] = r.id
        c = Coupon(run_id=runs[run], jour=date.fromisoformat(jour), profil=f"c{cid}", nom=nom, cote_totale=float(cote) if cote else None, statut=statut)
        db.add(c); db.flush(); cps[cid] = c.id
    for l in open(os.path.join(HERE, "jambes.txt"), encoding="utf-8"):
        cid, match, cat, marche, hand, sel, cote, proba, edge, res = l.rstrip("\n").split("|")
        db.add(Jambe(coupon_id=cps[cid], libelle_match=match, categorie=cat, marche=marche, handicap=float(hand) if hand else None, selection=sel,
                     cote=float(cote), proba_modele_pct=float(proba) if proba else None, edge_pct=float(edge) if edge else None, resultat=res))
    db.commit()

if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        charger(db)
        for jour in JOURS:
            j = date.fromisoformat(jour)
            faits = ap.faits_du_jour(db, j)
            stats = ap.statistiques(ap.jambes_jugees(db, jour=j))
            det = "\n".join(ap.lecons_deterministes(faits, stats))
            print(f"=== {jour} | deterministe={len(det)} car.")
            for f in faits["coupons"]:
                perdues = [f"{x['match']} — {x['marche']} {x['selection']} @{x['cote']} ({x['proba_pct']}%)" for x in f["jambes"] if x["resultat"] == "perdu"]
                print(f"  {f['coupon']} | {f['statut']} | {f['nb_jambes']} jambes | perdues: {perdues}")
            print("  pieges:", faits["matchs_pieges"])
            print("  stats:", json.dumps(stats, ensure_ascii=False, separators=(",", ":")))
