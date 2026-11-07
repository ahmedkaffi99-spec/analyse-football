"""Génère etudes_finales_a_valider.md et 07_remplacement_etudes_PRET_NON_EXECUTE.sql à partir des données de ce dossier (aucune écriture en base).
Usage (depuis backend/) : DATABASE_URL=sqlite:////tmp/x.db python ../rapports/phase3/donnees_sources_apercu/generer_etudes_finales.py"""
import json, os, sys
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import construire_apercu as ca
from app.database import SessionLocal, init_db
from app.services import apprentissage as ap

ID = {"2026-11-04": 15, "2026-10-28": 11, "2026-10-25": 10, "2026-10-24": 9, "2026-10-23": 8}
OLDMD5 = {15: "0e6c7ae951e899cbcb3fa42c6e35d2dd", 11: "22b65812c8b051e29aa3d2072f37b953", 10: "edae0c7914996aa5e6e4bdd20aea9c8c",
          9: "25f13428326eaea78835a64a8e65c793", 8: "e36b963db44d6fdee50bd99f53214abb"}
OLDSTATSMD5 = {15: "db93ac69f8efaf0c40dc60585cde73bf", 11: "6c40d8ec8d46b5844b68e05e6594f5df", 10: "81c152484fb5efae8ff6ce7301c67f67",
               9: "405ce56e950292deca3ba3faa9ecef9e", 8: "cbee242c67f675aa65d947209f7ebf22"}
LECONS = json.load(open(os.path.join(HERE, "lecons_redigees.json"), encoding="utf-8"))
ANCIENNES = {e["jour"]: e["contenu"] for e in json.load(open(os.path.join(HERE, "..", "sauvegardes", "memoire_agent_instantane_lecture_2026-11-07.json"), encoding="utf-8"))["etudes"]}
RACINE = os.path.join(HERE, "..", "..", "..")

if __name__ == "__main__":
    init_db()
    md = [open(os.path.join(HERE, "entete_etudes.md"), encoding="utf-8").read().rstrip() + "\n"]
    sql = ["-- Phase 3 — REMPLACEMENT des 5 études mélangées. PRÊT, NON EXÉCUTÉ. Ne PAS lancer sans la validation expresse de l'utilisateur.",
           "-- Garde-fous : chaque UPDATE vérifie l'empreinte md5 du texte ET des stats d'origine (l'étude n'a pas changé depuis la sauvegarde) ;",
           "-- le bloc entier échoue si le nombre de lignes modifiées n'est pas exactement 5. Retour arrière : memoire_agent_sauvegarde_20261107 (copie exacte).",
           "-- Pour exécuter après validation : supprimer le bloc « garde de validation » ci-dessous.",
           "do $$ begin raise exception 'NON VALIDÉ : remplacement des études interdit tant que l''utilisateur ne l''a pas autorisé'; end $$; -- garde de validation",
           "do $$", "declare nb integer := 0; n1 integer;", "begin"]
    with SessionLocal() as db:
        ca.charger(db)
        for jour, i in ID.items():
            j = date.fromisoformat(jour)
            faits = ap.faits_du_jour(db, j)
            stats = ap.statistiques(ap.jambes_jugees(db, jour=j))
            det = "\n".join(ap.lecons_deterministes(faits, stats))
            contenu = det + "\nLEÇONS : " + LECONS[jour]
            assert len(contenu) <= ap.LONGUEUR_ETUDE_MAX and "None" not in contenu and "n=" in LECONS[jour].replace(" ", "")
            md.append(f"## {jour} (étude {i}) — {len(contenu)} caractères\n")
            md.append("### Ancienne étude (base, tronquée à 1 400 caractères)\n```\n" + ANCIENNES[jour] + "\n```\n")
            md.append("### Nouvelle étude finale proposée\n```\n" + contenu + "\n```\n")
            sp = f" dont {stats['jambes_sans_proba']} sans probabilité enregistrée" if stats.get("jambes_sans_proba") else ""
            md.append(f"Jambes jugées dans les statistiques enregistrées : {stats['jambes_jugees']}{sp} (coupons envoyés seulement).\n")
            tag = f"e{i}"
            sql.append(f"  update memoire_agent set contenu = ${tag}c${contenu}${tag}c$, stats = ${tag}s${json.dumps(stats)}${tag}s$::json")
            sql.append(f"   where id = {i} and jour = '{jour}' and md5(contenu) = '{OLDMD5[i]}' and md5(stats::text) = '{OLDSTATSMD5[i]}';")
            sql.append("  get diagnostics n1 = row_count; nb := nb + n1;")
    sql += ["  if nb <> 5 then raise exception 'ANNULATION : % études modifiées au lieu de 5', nb; end if;", "end $$;"]
    open(os.path.join(RACINE, "rapports", "phase3", "etudes_finales_a_valider.md"), "w", encoding="utf-8").write("\n".join(md))
    open(os.path.join(RACINE, "backend", "migrations", "phase3", "07_remplacement_etudes_PRET_NON_EXECUTE.sql"), "w", encoding="utf-8").write("\n".join(sql) + "\n")
    print("ok")
