"""Source UNIQUE des profils de coupons du moteur agent (Phase 2, 06/11/2026 ; refonte 07/11/2026). Module pur Python (aucune dépendance) : importé par
le formulaire « Run workflow » (backend/app/preparer_formulaire.py) ET par le profil de secours (analyser_et_envoyer.profils_agent_quotidien).

STRATÉGIE (demande du 07/11/2026) : l'IA choisit LIBREMENT les paris, les marchés, les sélections et les combinaisons ; elle construit TROIS coupons
selon un niveau de risque (PRUDENT, ÉQUILIBRÉ, GAINER ; le niveau technique du troisième reste « risque »). AUCUNE cote totale cible ni cote individuelle obligatoire n'est imposée : seules restent les
validations de Python (identifiants et cotes du catalogue, un pari par match et par event dans un coupon, pas de pari identique ni de match commun
entre coupons, deux jambes minimum, aucun coupon en double)."""

import os

COULEURS = ["🟢", "🟠", "🔴"]
# Demande du 07/11/2026 : chaque coupon compte de 5 à 12 jambes (un seul pari par match), la cote totale minimale est 5 et les trois coupons occupent
# des intervalles de cote totale ESPACÉS (aucun chevauchement). Bandes par défaut (08/11/2026, après l'étude des 3 derniers jours : 12-20 et 25-50 donnaient environ 7 % et 3 % de chance de
# gagner, soit 0 coupon sur 12 le 8/11) : PRUDENT 5-10, ÉQUILIBRÉ 11-15, GAINER 16-25 ; modifiables par les
# variables BANDE_COTE_PRUDENT / BANDE_COTE_EQUILIBRE / BANDE_COTE_RISQUE (« min-max »). Ce sont des contraintes vérifiées par Python, pas une promesse de gain.
NB_JAMBES_MIN_COUPON = 5
NB_JAMBES_MAX_COUPON = 12
BANDES_DEFAUT = {"prudent": (5.0, 10.0), "equilibre": (11.0, 15.0), "risque": (16.0, 25.0)}
# 14/11/2026 (« au lieu de cote haute, choisis plus de matchs ») : pour atteindre sa bande de cote, chaque profil combine PLUS de matchs à cote modérée plutôt que peu de jambes à cote haute.
# Minimum de jambes par défaut : prudent 6, équilibré 7, gainer 8 (maximum 12). Le champ « jambes » du formulaire (ex. « 5-12 ») remplace ces minimums pour les trois profils.
JAMBES_MIN_PAR_NIVEAU = {"prudent": 6, "equilibre": 7, "risque": 8}


def bande_cote(niveau):
    """(min, max) de cote totale du niveau ; la variable d'environnement valide « min-max » (min >= 5 > 0, min < max) remplace le défaut, sinon le défaut est gardé."""
    brut = (os.getenv("BANDE_COTE_" + niveau.upper()) or "").strip().replace(",", ".")
    try:
        bas, haut = (float(x) for x in brut.split("-"))
        if 0 < bas < haut:
            return bas, haut
    except ValueError:
        pass
    return BANDES_DEFAUT[niveau]

# (clé stable de l'historique, niveau, libellé, consigne donnée à l'IA). Les clés « couponN » sont conservées : elles sont enregistrées en base.
NIVEAUX = (
    ("coupon1", "prudent", "PRUDENT",
     "Profil PRUDENT : privilégie la SÉCURITÉ. Choisis les jambes dont la probabilité du catalogue est la plus élevée et dont le contexte "
     "(données, absences, enjeu) est le plus solide ; accepte le rendement que cela donne, même faible. N'ajoute jamais une jambe fragile "
     "pour faire monter le gain."),
    ("coupon2", "equilibre", "ÉQUILIBRÉ",
     "Profil ÉQUILIBRÉ : cherche le meilleur COMPROMIS entre probabilité et rendement. Combine des jambes solides et quelques jambes "
     "mieux valorisées (edge du catalogue positif), sans sacrifier la probabilité de passer le coupon en entier. Pour atteindre la bande de cote, ajoute des MATCHS "
     "(jambes à cote modérée) plutôt que de choisir quelques jambes à cote haute."),
    ("coupon3", "risque", "GAINER",
     "Profil GAINER (niveau de risque le plus élevé) : accepte davantage de risque pour viser un gain potentiel plus élevé. Tu peux retenir des jambes moins probables mais "
     "bien valorisées (cote et edge du catalogue intéressants) et des combinaisons plus ambitieuses, en restant dans le catalogue et en "
     "justifiant chaque pari. Vise le gain en COMBINANT PLUS DE MATCHS (au moins 8) à cote modérée, pas en cherchant des cotes individuelles élevées."),
)


def _entier_env(nom, defaut):
    try:
        return max(0, int(os.getenv(nom) or defaut))
    except ValueError:
        return defaut


def analyser_intervalle(texte, entier=False):
    """« 5-12 » (ou « 5 - 12 », « 5,5-10 ») -> (min, max) ou None si le texte est vide ou invalide (le défaut est alors gardé : jamais d'erreur silencieuse sur la config)."""
    brut = str(texte or "").strip().replace(",", ".").replace(" ", "")
    if not brut or brut.count("-") != 1:
        return None
    try:
        bas, haut = (float(x) for x in brut.split("-"))
    except ValueError:
        return None
    if not (0 < bas < haut) and not (entier and 0 < bas <= haut):
        return None
    return (int(bas), int(haut)) if entier else (bas, haut)


def profils(un_pari_par_match=True, contraintes=True, jambes=None, bandes=None, max_coupons_par_match=None):
    """jambes : (min, max) de jambes par coupon pour les trois profils (défaut : minimum par profil JAMBES_MIN_PAR_NIVEAU, maximum 12). bandes : {niveau: (min, max)} de cote totale (défaut : variables BANDE_COTE_* puis 5-10 / 11-15 / 16-25).
    max_coupons_par_match : nombre maximal de coupons du run où un même match peut figurer (défaut 2, variable MAX_COUPONS_PAR_MATCH ; 0 = pas de plafond)."""
    jambes_max = jambes[1] if jambes else NB_JAMBES_MAX_COUPON
    plafond_match = _entier_env("MAX_COUPONS_PAR_MATCH", 2) if max_coupons_par_match is None else max_coupons_par_match
    """Les TROIS profils de risque : 5 à 12 jambes, cote totale dans une bande propre à chaque profil (bandes espacées, minimum 5). Aucune cote imposée par jambe."""
    sortie = []
    # contraintes=False : profils « libres » (2 jambes minimum, aucune bande de cote), réservés aux tests des règles de cohérence indépendantes de la bande.
    for i, (cle, niveau, libelle, consigne) in enumerate(NIVEAUX):
        sortie.append({
            "cle": cle, "nom": f"{COULEURS[i]} {libelle}", "niveau_risque": niveau, "consigne": consigne,
            # 5 à 12 jambes (vérifié par Python dans valider) et bande de cote totale espacée des autres profils.
            "nb_jambes_min": (jambes[0] if jambes else JAMBES_MIN_PAR_NIVEAU.get(niveau, NB_JAMBES_MIN_COUPON)) if contraintes else 2,
            "nb_jambes": jambes_max if contraintes else 99,
            **({"cote_totale_min": (bandes or {}).get(niveau, bande_cote(niveau))[0], "cote_totale_max": (bandes or {}).get(niveau, bande_cote(niveau))[1]} if contraintes else {}),
            **({"max_coupons_par_match": plafond_match} if contraintes and plafond_match else {}),
            "jambes_max_par_match": 1 if un_pari_par_match else 3,
            # Demande du 07/11/2026 : un même match peut figurer dans PLUSIEURS coupons du run à condition que les paris soient DIFFÉRENTS (le pari exact reste
            # interdit dans deux coupons) ; dans un coupon, un seul pari par match. Sans cela, 3 coupons de 5 à 12 jambes épuisent les 19 matchs et le 3e s'abstient.
            "match_repete_autorise": bool(contraintes), "un_seul_pari_par_event": True})
    return sortie
