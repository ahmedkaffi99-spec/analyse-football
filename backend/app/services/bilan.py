"""Bilan Telegram du soir, construit depuis la base (remplace l'envoi de verifier_resultats.py) :
un message par run, envoyé une seule fois, quand TOUS ses coupons sont jugés."""

from collections import defaultdict

from sqlalchemy import select

from app.models import Coupon

ICONES = {"gagne": "✅", "perdu": "❌", "push": "➖ remboursé", "non_verifiable": "❓ non vérifiable",
          "en_attente": "⏳", "annule": "🚫 match annulé/reporté (remboursé)",
          "perime": "⌛ périmé (résultat jamais confirmé)"}
VERDICTS = {"gagne": "✅ GAGNÉ", "perdu": "❌ PERDU", "incertain": "❓ INCERTAIN (au moins une jambe non vérifiable)"}


def construire_message(coupons, partiel=False):
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
        if compte["annule"]:
            detail += f" · 🚫 {compte['annule']} annulé(s)/remboursé(s)"
        if compte["perime"]:
            detail += f" · ⌛ {compte['perime']} périmé(s)"
        sections.append(f"{c.nom} — {VERDICTS.get(c.statut, c.statut)}\n\n" + "\n".join(lignes)
                        + f"\n\n{detail}\n💰 Cote totale : *{c.cote_totale}*")
    jour = coupons[0].jour.isoformat()
    separateur = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n"
    nb = len(coupons)
    suffixe = f" — {nb} PROFILS" if nb > 1 else ""
    entete = f"🏁 *RÉSULTATS DU JOUR{suffixe} — {jour}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if partiel:
        entete += "⚠️ *Rapport final partiel* : heure limite atteinte, certains matchs n'ont pas pu être jugés (⏳).\n\n"
    return entete + separateur.join(sections)


LIMITE_TELEGRAM = 3800  # Telegram refuse au-delà de 4096 caractères (« message is too long »)


def decouper_message(texte, limite=LIMITE_TELEGRAM):
    """Découpe un message trop long en morceaux ≤ limite, en coupant d'abord entre sections (lignes de séparation),
    puis entre lignes — jamais au milieu d'une ligne de pari."""
    if len(texte) <= limite:
        return [texte]
    morceaux, courant = [], ""
    for bloc in texte.split("\n\n"):
        for ligne in ([bloc] if len(bloc) <= limite else bloc.split("\n")):
            candidat = f"{courant}\n\n{ligne}" if courant else ligne
            if len(candidat) > limite and courant:
                morceaux.append(courant)
                courant = ligne
            else:
                courant = candidat
    if courant:
        morceaux.append(courant)
    return morceaux


def envoyer_bilans(db, notifier, forcer_runs=()):
    """notifier(message) -> bool (analyser_et_envoyer.notifier_telegram). Renvoie le nombre de
    bilans envoyés. Un run dont un coupon est encore en attente est laissé pour plus tard."""
    par_run = defaultdict(list)
    for c in db.scalars(select(Coupon).where(Coupon.bilan_envoye.is_(False))):
        par_run[c.run_id].append(c)

    envoyes = 0
    for coupons in par_run.values():
        incomplet = any(c.statut == "en_attente" for c in coupons)
        forcer = coupons[0].run_id in forcer_runs
        if not any(c.jambes for c in coupons) or (incomplet and not forcer):
            continue
        morceaux = decouper_message(construire_message(coupons, partiel=incomplet))
        # bilan marqué envoyé SEULEMENT si tous les morceaux sont partis
        if all([notifier(m) for m in morceaux]):
            for c in coupons:
                c.bilan_envoye = True
            db.commit()
            envoyes += 1
    return envoyes
