"""Source UNIQUE des profils de coupons « smart » du moteur agent (Phase 2, 06/11/2026). Module pur Python (aucune dépendance) : importé par
le formulaire « Run workflow » (backend/app/preparer_formulaire.py) ET par le profil de secours (analyser_et_envoyer.profils_agent_quotidien).
Avant : deux définitions différentes — le formulaire (bandes 5-10 / 12-18 / 20-35, aucune contrainte) et le secours (bandes 5-10 / 10-18 /
18-35, probabilités min/max par jambe, couverture obligatoire de tous les matchs, plafond de coupons par match) : les règles retirées le
06/11/2026 revenaient dès que le formulaire n'envoyait pas de profils."""

BANDES_DEFAUT = [(5, 10), (12, 18), (20, 35)]
COULEURS = ["🟢", "🟠", "🔴", "🔵", "🟣"]
NB_COUPONS_DEFAUT = 3
CONSIGNE = ("Smart coupon : tu choisis LIBREMENT les paris et le nombre de jambes les plus probables et les mieux valorisés ; seule "
            "contrainte : la cote totale doit être dans la bande de ce profil (une seule sélection par match dans un coupon).")


def lire_bande(texte):
    """« 12-18 » -> (12.0, 18.0)."""
    a, _, b = texte.partition("-")
    return float(a), float(b)


def profils(nb_coupons=None, cotes=None, un_pari_par_match=True):
    """Liste de profils. `cotes` : une bande (« 12-18 ») ou None par coupon ; sans choix, bande smart du rang du coupon (5-10, 12-18,
    20-35, puis on recommence). Les choix au-delà du nombre de coupons sont ignorés."""
    n = nb_coupons or NB_COUPONS_DEFAUT
    cotes = list(cotes or [])
    bandes = [lire_bande(cotes[i]) if i < len(cotes) and cotes[i] else BANDES_DEFAUT[i % len(BANDES_DEFAUT)] for i in range(n)]
    sortie = []
    for i, (bas, haut) in enumerate(bandes):
        b0, b1 = f"{bas:g}", f"{haut:g}"
        sortie.append({
            "cle": f"coupon{i + 1}", "nom": f"{COULEURS[i % len(COULEURS)]} SMART COUPON — cote {b0} à {b1}",
            "cote_min": bas, "cote_max": haut, "cote_totale_min": bas, "cote_totale_max": haut,
            # 06/11/2026 : plus de nombre de jambes imposé (1 à 99 = libre), plus de probabilité minimale/maximale par jambe,
            # plus de plafond de coupons par match ; seule la bande de cote totale est vérifiée.
            "nb_jambes_min": 1, "nb_jambes": 99,
            "jambes_max_par_match": 1 if un_pari_par_match else 3, "match_repete_autorise": True,
            "un_seul_pari_par_event": True, "consigne": CONSIGNE})
    return sortie
