"""Source UNIQUE des profils de coupons du moteur agent (Phase 2, 06/11/2026 ; refonte 07/11/2026). Module pur Python (aucune dépendance) : importé par
le formulaire « Run workflow » (backend/app/preparer_formulaire.py) ET par le profil de secours (analyser_et_envoyer.profils_agent_quotidien).

STRATÉGIE (demande du 07/11/2026) : l'IA choisit LIBREMENT les paris, les marchés, les sélections et les combinaisons ; elle construit TROIS coupons
selon un niveau de risque (PRUDENT, ÉQUILIBRÉ, RISQUE). AUCUNE cote totale cible ni cote individuelle obligatoire n'est imposée : seules restent les
validations de Python (identifiants et cotes du catalogue, un pari par match et par event dans un coupon, pas de pari identique ni de match commun
entre coupons, deux jambes minimum, aucun coupon en double)."""

COULEURS = ["🟢", "🟠", "🔴"]
NB_JAMBES_MIN_COUPON = 2

# (clé stable de l'historique, niveau, libellé, consigne donnée à l'IA). Les clés « couponN » sont conservées : elles sont enregistrées en base.
NIVEAUX = (
    ("coupon1", "prudent", "PRUDENT",
     "Profil PRUDENT : privilégie la SÉCURITÉ. Choisis les jambes dont la probabilité du catalogue est la plus élevée et dont le contexte "
     "(données, absences, enjeu) est le plus solide ; accepte le rendement que cela donne, même faible. N'ajoute jamais une jambe fragile "
     "pour faire monter le gain."),
    ("coupon2", "equilibre", "ÉQUILIBRÉ",
     "Profil ÉQUILIBRÉ : cherche le meilleur COMPROMIS entre probabilité et rendement. Combine des jambes solides et quelques jambes "
     "mieux valorisées (edge du catalogue positif), sans sacrifier la probabilité de passer le coupon en entier."),
    ("coupon3", "risque", "RISQUE",
     "Profil RISQUE : accepte davantage de risque pour viser un gain potentiel plus élevé. Tu peux retenir des jambes moins probables mais "
     "bien valorisées (cote et edge du catalogue intéressants) et des combinaisons plus ambitieuses, en restant dans le catalogue et en "
     "justifiant chaque pari."),
)


def profils(un_pari_par_match=True):
    """Les TROIS profils de risque. Aucune bande de cote, aucun plancher ni plafond de cote par jambe ou total."""
    sortie = []
    for i, (cle, niveau, libelle, consigne) in enumerate(NIVEAUX):
        sortie.append({
            "cle": cle, "nom": f"{COULEURS[i]} {libelle}", "niveau_risque": niveau, "consigne": consigne,
            # Deux jambes minimum (un « combiné » d'une seule jambe n'en est pas un ; vérifié par Python dans valider) ; pas de maximum.
            "nb_jambes_min": NB_JAMBES_MIN_COUPON, "nb_jambes": 99,
            "jambes_max_par_match": 1 if un_pari_par_match else 3,
            # Un même match ne figure que dans UN coupon du run tant que le catalogue a assez de matchs ; sinon agent_strategie.ajuster_repetition
            # l'autorise (le pari exact reste interdit dans deux coupons).
            "match_repete_autorise": False, "un_seul_pari_par_event": True})
    return sortie
