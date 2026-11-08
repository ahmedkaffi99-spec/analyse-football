"""Récapitulatif « coupon par modèle » (08/11/2026) : un message Telegram qui associe chaque coupon enregistré au modèle qui l'a composé, relu dans le journal du run
(champ modele_pilote). Texte pur : aucune IA, aucun réseau ; l'envoi est fait par l'appelant."""
import re

from sqlalchemy import select

from app.models import Coupon, Run

NOMS_MODELES = {
    "deepseek/deepseek-v4.1-flash": "DeepSeek via OpenRouter",
    "deepseek (deepseek-flash)": "DeepSeek officiel",
    "openai/gpt-6.1-sol": "GPT-6.1 Sol",
    "google/gemini-4-argon": "Gemini 4 Argon",
    "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5",
}
PROFILS = {"coupon1": "🟢 Prudent", "coupon2": "🟠 Équilibré", "coupon3": "🔴 Gainer"}
MODELE_INCONNU = "modèle non enregistré"


def modele_du_run(detail):
    """Identifiant du modèle pilote d'un run, lu dans son journal ; None si absent."""
    m = re.search(r'"modele_pilote"\s*:\s*"([^"]*)"', detail or "")
    return m.group(1) if m else None


def nom_modele(identifiant):
    return NOMS_MODELES.get(identifiant) or identifiant or MODELE_INCONNU


def lignes_recapitulatif(db, ids):
    """Une ligne par coupon demandé (ordre des numéros)."""
    ids = sorted(set(ids))
    coupons = db.scalars(select(Coupon).where(Coupon.id.in_(ids)).order_by(Coupon.id)).all()
    runs = {r.id: r for r in db.scalars(select(Run).where(Run.id.in_({c.run_id for c in coupons}))).all()} if coupons else {}
    lignes = []
    for c in coupons:
        identifiant = modele_du_run(runs[c.run_id].detail) if c.run_id in runs else None
        lignes.append({"coupon": c.id, "run": c.run_id, "jour": c.jour, "profil": PROFILS.get(c.profil) or c.nom, "cote": c.cote_totale,
                       "proba": c.proba_combinee_pct, "jambes": len(c.jambes), "modele": identifiant})
    return lignes


def construire_message(lignes):
    """Texte Telegram (Markdown simple) : un bloc par run, avec le modèle en titre. Aucun coupon n'est modifié."""
    if not lignes:
        return "Aucun coupon trouvé pour ce récapitulatif."
    jours = sorted({str(l["jour"]) for l in lignes})
    sortie = [f"*📋 Récapitulatif des coupons par modèle — {', '.join(jours)}*"]
    par_run = {}
    for l in lignes:
        par_run.setdefault(l["run"], []).append(l)
    for run in sorted(par_run):
        bloc = par_run[run]
        sortie.append(f"\n*{nom_modele(bloc[0]['modele'])}* (run {run})")
        for l in bloc:
            cote = f"{l['cote']:.2f}" if l["cote"] is not None else "?"
            proba = f" · probabilité {l['proba']:g} %" if l["proba"] is not None else ""
            sortie.append(f"• coupon {l['coupon']} · {l['profil']} · cote {cote} · {l['jambes']} jambe{'s' if l['jambes'] > 1 else ''}{proba}")
    return "\n".join(sortie)


def reference_recapitulatif(reference):
    """« recap:410-427 » -> liste des numéros ; None si ce n'est pas une demande de récapitulatif ; ValueError si la plage est invalide."""
    if not str(reference).startswith("recap:"):
        return None
    debut, _, fin = str(reference)[len("recap:"):].partition("-")
    a, b = int(debut), int(fin or debut)
    if a <= 0 or b < a or b - a > 200:
        raise ValueError(f"plage de coupons invalide : {reference}")
    return list(range(a, b + 1))
