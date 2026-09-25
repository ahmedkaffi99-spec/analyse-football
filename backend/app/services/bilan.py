"""Bilan Telegram du soir, construit depuis la base (remplace l'envoi de verifier_resultats.py) :
un message par run, envoyé une seule fois, quand TOUS ses coupons sont jugés."""

from collections import defaultdict

from sqlalchemy import select

from app.models import Coupon

ICONES = {"gagne": "✅", "perdu": "❌", "push": "➖ remboursé", "non_verifiable": "❓ non vérifiable",
          "en_attente": "⏳"}
VERDICTS = {"gagne": "✅ GAGNÉ", "perdu": "❌ PERDU", "incertain": "❓ INCERTAIN (au moins une jambe non vérifiable)"}


def construire_message(coupons):
    sections = []
    for c in sorted(coupons, key=lambda c: c.profil):
        if not c.jambes:
            sections.append(f"{c.nom}\n_Aucune sélection ce jour-là pour ce profil._")
            continue
        lignes = []
        for j in c.jambes:
            score = ""
            if j.match and j.match.score_domicile is not None:
                score = f" ({j.match.score_domicile}-{j.match.score_exterieur})"
            lignes.append(f"{ICONES.get(j.resultat, '❓')} {j.libelle_match}{score} — {j.marche} : {j.selection} @ {j.cote}")
        compte = defaultdict(int)
        for j in c.jambes:
            compte[j.resultat] += 1
        detail = f"✅ {compte['gagne']} · ❌ {compte['perdu']}"
        if compte["push"]:
            detail += f" · ➖ {compte['push']} remboursé(s)"
        if compte["non_verifiable"]:
            detail += f" · ❓ {compte['non_verifiable']} non vérifiable(s)"
        sections.append(f"{c.nom} — {VERDICTS.get(c.statut, c.statut)}\n\n" + "\n".join(lignes)
                        + f"\n\n{detail}\n💰 Cote totale : *{c.cote_totale}*")
    jour = coupons[0].jour.isoformat()
    separateur = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n"
    return f"🏁 *RÉSULTATS DU JOUR — 3 PROFILS — {jour}*\n━━━━━━━━━━━━━━━━━━━━\n\n" + separateur.join(sections)


def envoyer_bilans(db, notifier):
    """notifier(message) -> bool (analyser_et_envoyer.notifier_telegram). Renvoie le nombre de
    bilans envoyés. Un run dont un coupon est encore en attente est laissé pour plus tard."""
    par_run = defaultdict(list)
    for c in db.scalars(select(Coupon).where(Coupon.bilan_envoye.is_(False))):
        par_run[c.run_id].append(c)

    envoyes = 0
    for coupons in par_run.values():
        if not any(c.jambes for c in coupons) or any(c.statut == "en_attente" for c in coupons):
            continue
        if notifier(construire_message(coupons)):
            for c in coupons:
                c.bilan_envoye = True
            db.commit()
            envoyes += 1
    return envoyes
