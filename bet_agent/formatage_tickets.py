"""Mise en forme des tickets (extrait de analyser_et_envoyer.py, qui le ré-exporte à l'identique) :
explications de marché, rédaction courte / sans IA, contrôle de fidélité du texte, découpe Telegram.
Texte pur : aucun réseau, aucune IA."""
import re

# Catégories "Handicap" où OddsPapi renvoie TOUJOURS la ligne du point de vue de l'équipe
# DOMICILE, alors que 1xBet affiche la ligne du point de vue de l'équipe SÉLECTIONNÉE — bug
# réel trouvé le 03/10/2026 dans un vrai ticket (Poland vs Romania, Asian Handicap, sélection
# extérieure) : le marché affiché disait "Asian Handicap (-1.5)" alors que la vraie ligne jouée
# sur 1xBet pour la Roumanie est "Handicap (1.5)" — le signe domicile-référencé d'OddsPapi avait
# fuité tel quel dans le texte du ticket, au lieu d'être ramené du point de vue de l'équipe
# choisie (ce que le guide pédagogique, lui, faisait déjà correctement).
CATEGORIES_HANDICAP_SIGNE = ("Handicap Asiatique", "Handicap", "Handicap Européen",
                              "Handicap Corners", "Handicap Cartons", "Handicap Fautes",
                              "Handicap Tirs", "Handicap Tirs Cadrés", "Handicap Hors-jeux")


def _handicap_point_de_vue_equipe(categorie, selection_brute, handicap):
    """Convertit la ligne domicile-référencée d'OddsPapi vers le point de vue de l'équipe
    SÉLECTIONNÉE (celle que 1xBet affiche à l'écran). "or 0.0" évite le zéro négatif (-0.0) que
    Python produit sur une ligne à 0 pour l'équipe extérieure (-0.0 >= 0 est pourtant True, mais
    s'affiche avec un signe moins trompeur)."""
    if categorie not in CATEGORIES_HANDICAP_SIGNE or handicap is None:
        return handicap
    sel = (selection_brute or "").lower()
    if sel in ("away", "2"):
        return (-handicap) or 0.0
    return handicap or 0.0


def expliquer_marche(categorie, selection_brute, handicap):
    """Traduit une catégorie déjà connue avec certitude (calculée plus haut par le code,
    JAMAIS devinée depuis le texte brut du marché) en un guide pédagogique + l'onglet 1xbet
    correspondant. Fait exprès de bien SÉPARER 'Total' (match entier) de 'Total Équipe 1/2'
    (une seule équipe) — c'est la confusion que le LLM faisait en improvisant ce texte lui-même."""
    sel = (selection_brute or "").lower()

    if categorie in ("Total", "Total Équipe 1", "Total Équipe 2", "Total Corners", "Total Cartons",
                      "Total Cartons Équipe 1", "Total Cartons Équipe 2",
                      "Total Fautes", "Total Tirs", "Total Tirs Cadrés", "Total Hors-jeux"):
        sens = "inférieur" if "under" in sel else "supérieur"
        objet_par_categorie = {
            "Total": ("le nombre total de buts du match", "onglet Total (buts du match entier)"),
            "Total Équipe 1": ("le nombre de buts marqués par l'ÉQUIPE 1 (domicile) SEULE — pas le match entier",
                                "onglet Total équipe 1 / Total buts équipe domicile"),
            "Total Équipe 2": ("le nombre de buts marqués par l'ÉQUIPE 2 (extérieure) SEULE — pas le match entier",
                                "onglet Total équipe 2 / Total buts équipe extérieure"),
            "Total Corners": ("le nombre total de corners du match", "onglet Corners / Total corners"),
            # "Total Cartons" = cartons JAUNES uniquement — confirmé le 03/10/2026 par capture
            # d'écran 1xBet (onglet "Yellow Cards", aucun marché carton rouge n'existe sur
            # 1xBet) : cohérent avec calculer_mu_cartons_depuis_stats_detaillees, qui exclut
            # déjà les rouges (trop rares sur 10 matchs). Texte corrigé en conséquence —
            # l'ancien "(jaunes + rouges)" était faux et trompeur sur le ticket Telegram.
            "Total Cartons": ("le nombre de cartons JAUNES du match", "onglet Yellow Cards / Total"),
            # Total 1/Total 2 (demande explicite du 03/10/2026, capture d'écran 1xBet) : cartons
            # JAUNES d'UNE SEULE équipe, jamais le total du match — même distinction Équipe 1/2
            # que pour les buts ci-dessus.
            "Total Cartons Équipe 1": ("le nombre de cartons JAUNES reçus par l'ÉQUIPE 1 (domicile) SEULE — "
                                        "pas le match entier", "onglet Yellow Cards / Total 1"),
            "Total Cartons Équipe 2": ("le nombre de cartons JAUNES reçus par l'ÉQUIPE 2 (extérieure) SEULE — "
                                        "pas le match entier", "onglet Yellow Cards / Total 2"),
            "Total Fautes": ("le nombre total de fautes commises du match", "onglet Fautes / Total fautes"),
            "Total Tirs": ("le nombre total de tirs (cadrés + non cadrés) du match", "onglet Tirs / Total tirs"),
            "Total Tirs Cadrés": ("le nombre total de tirs CADRÉS du match", "onglet Tirs cadrés / Shots on target"),
            "Total Hors-jeux": ("le nombre total de hors-jeux du match", "onglet Hors-jeux / Offsides"),
        }
        objet, onglet = objet_par_categorie[categorie]
        return f"{objet} doit être {sens} à {handicap}", onglet

    if categorie == "BTTS":
        oui = sel in ("yes", "oui")
        guide = ("les deux équipes doivent marquer au moins un but chacune" if oui
                 else "au moins une des deux équipes ne doit PAS marquer")
        return guide, "onglet Les deux équipes marquent (BTTS)"

    if categorie == "Double Chance":
        sel_norm = re.sub(r"[^a-z0-9]", "", sel)
        if sel_norm == "1x":
            guide = "le match doit se terminer par une victoire à domicile OU un match nul"
        elif sel_norm in ("x2", "2x"):
            guide = "le match doit se terminer par un match nul OU une victoire à l'extérieur"
        else:
            guide = f"double chance : {selection_brute}"
        return guide, "onglet Double Chance"

    if categorie == "Draw No Bet":
        cote_txt = "domicile" if sel in ("home", "1") else "extérieure"
        return (f"l'équipe {cote_txt} doit gagner (en cas de match nul, la mise est intégralement remboursée)",
                "onglet Nul remboursé (Draw No Bet)")

    if categorie == "Pair/Impair":
        if sel == "odd":
            return "le nombre total de buts du match doit être IMPAIR (1, 3, 5, ...)", "onglet Pair/Impair (Odd/Even)"
        return "le nombre total de buts du match doit être PAIR (0, 2, 4, ...)", "onglet Pair/Impair (Odd/Even)"

    if categorie in ("Clean Sheet Équipe 1", "Clean Sheet Équipe 2"):
        num = "1" if categorie.endswith("1") else "2"
        cote_txt = "domicile" if num == "1" else "extérieure"
        oui = sel in ("yes", "oui")
        guide = (f"l'équipe {num} ({cote_txt}) ne doit encaisser AUCUN but sur tout le match" if oui
                 else f"l'équipe {num} ({cote_txt}) doit encaisser au moins un but")
        return guide, f"onglet Clean Sheet équipe {num}"

    if categorie in ("Win To Nil Équipe 1", "Win To Nil Équipe 2"):
        num = "1" if categorie.endswith("1") else "2"
        cote_txt = "domicile" if num == "1" else "extérieure"
        oui = sel in ("yes", "oui")
        guide = (f"l'équipe {num} ({cote_txt}) doit GAGNER le match ET l'adversaire ne doit marquer aucun but"
                 if oui else
                 f"soit l'équipe {num} ({cote_txt}) ne gagne pas, soit l'adversaire marque au moins un but")
        return guide, f"onglet Win to Nil équipe {num}"

    if categorie in ("Handicap Asiatique", "Handicap", "Handicap Européen"):
        # Marché OddsPapi "Asian Handicap" unique, affiché par 1xBet sous DEUX onglets selon
        # la granularité de la ligne (vérifié le 01/10/2026, voir commentaire dans
        # _evaluer_marches_brut) : "Asian Handicap" pour les lignes de quart (.25/.75),
        # "Handicap" tout court pour les lignes entières/demi — categorie suit cette
        # distinction pour que le ticket nomme le bon onglet à l'utilisateur. "Handicap
        # Européen" gardé en compatibilité : un renommage bref le 01/10/2026 (annulé le même
        # jour, collision avec le vrai marché OddsPapi distinct "European Handicap", 3 voies
        # 1/X/2) a pu être persisté entre-temps sur d'éventuels tickets.
        onglet_nom = {"Handicap Asiatique": "Asian Handicap", "Handicap": "Handicap"}.get(categorie, "Handicap Asiatique")
        if sel in ("home", "1"):
            cote_txt = "domicile"
        elif sel in ("away", "2"):
            cote_txt = "extérieure"
        else:
            return f"handicap : {selection_brute}", f"onglet {onglet_nom}"
        h_effectif = _handicap_point_de_vue_equipe(categorie, selection_brute, handicap)
        if h_effectif >= 0:
            guide = f"l'équipe {cote_txt} part avec un avantage fictif de {h_effectif} but(s)"
        else:
            guide = f"l'équipe {cote_txt} part avec un désavantage fictif de {abs(h_effectif)} but(s)"
        return guide, f"onglet {onglet_nom}"

    if categorie in ("Handicap Corners", "Handicap Cartons", "Handicap Fautes", "Handicap Tirs",
                      "Handicap Tirs Cadrés", "Handicap Hors-jeux"):
        unite = {
            "Handicap Corners": "corner(s)", "Handicap Cartons": "carton(s) jaune(s)",
            "Handicap Fautes": "faute(s)", "Handicap Tirs": "tir(s)",
            "Handicap Tirs Cadrés": "tir(s) cadré(s)", "Handicap Hors-jeux": "hors-jeu(x)",
        }[categorie]
        # "Handicap Cartons" vit sous l'onglet "Yellow Cards" sur 1xbet (confirmé le 03/10/2026
        # par capture d'écran : aucun marché carton rouge n'existe) — jamais "Handicap Cartons",
        # qui n'est pas le nom réel affiché sur 1xbet.
        onglet_categorie = "Yellow Cards - Handicap" if categorie == "Handicap Cartons" else categorie
        if sel in ("home", "1"):
            cote_txt = "domicile"
        elif sel in ("away", "2"):
            cote_txt = "extérieure"
        else:
            return f"handicap {unite} : {selection_brute}", f"onglet {onglet_categorie}"
        h_effectif = _handicap_point_de_vue_equipe(categorie, selection_brute, handicap)
        if h_effectif >= 0:
            guide = f"l'équipe {cote_txt} part avec un avantage fictif de {h_effectif} {unite}"
        else:
            guide = f"l'équipe {cote_txt} part avec un désavantage fictif de {abs(h_effectif)} {unite}"
        return guide, f"onglet {onglet_categorie}"

    return None, None


def niveau_confiance(proba_pct):
    """Même règle que celle donnée au LLM (tâche 2) : <70% Faible, 70-85% Moyen, >85% Élevé.

    Basé sur la PROBABILITÉ du modèle, pas sur l'edge (corrigé le 09/10/2026) : depuis le
    03/10/2026 ("on choisit les cotes avec chance de réussite, pas un edge"), la probabilité
    est le SEUL critère de sélection (PROBA_MIN_FORTE) — baser la confiance affichée sur
    l'edge produisait un contresens visible dans les tickets réels (run 118, 08/10/2026) :
    5 jambes à 70-76% de probabilité (le critère qui les a fait sélectionner) affichées
    "Faible confiance" parce que leur edge était négatif, alors que c'étaient précisément les
    choix les plus solides du modèle ce jour-là."""
    if proba_pct is None or proba_pct < 70:
        return "Faible"
    return "Moyen" if proba_pct <= 85 else "Élevé"


def rediger_ticket_sans_ia(selections_finales):
    """Ticket au MÊME format que celui demandé au LLM, construit en pur Python à partir des
    chiffres déjà calculés. Utilisé quand aucun LLM ne répond : une panne de l'IA ne doit
    plus jamais faire perdre les coupons du jour (constaté le 2026-09-26 : run entier en
    erreur pour une limite de débit). Réutilisé aussi par l'agent pilote pour rédiger CHAQUE
    coupon qu'il compose lui-même (agent_pilote.py:rediger_coupon_outil), pas seulement en
    repli — d'où le nom historique un peu trompeur.

    Format compact — une seule ligne par match (pas de Guide/Où parier/Pourquoi détaillés) :
    avec un coupon combiné de 10 à 15 matchs, la version détaillée dépassait régulièrement la
    limite dure de 4096 caractères de Telegram et le message finissait tronqué au milieu,
    perdant des matchs entiers (constaté sur le run du 26/09/2026). Un résumé tient en UN
    seul message Telegram, sans jamais avoir besoin de le découper.

    Si l'IA a fourni une raison pour ce pari (raison_ia, agent pilote/stratège), on l'affiche :
    c'est la vraie justification de son choix depuis que le catalogue ne contient plus de
    probabilité/edge calculée (30/09/2026). Quand Python a AUSSI un guide précis pour ce pari
    (p["guide"] : explication du handicap calculée par expliquer_marche, ou note sur une ligne
    de quart — _note_ligne_quart, 01/10/2026), il est ajouté à la suite, jamais à la place : la
    rédaction libre de l'IA peut être ambiguë ou incomplète sur un mécanisme précis (constaté le
    01/10/2026, signalé par l'utilisateur — un "Over 3.25" rédigé "je joue plus de trois buts"
    sans mentionner le résultat partiel possible pile sur la ligne) ; le guide Python, toujours
    exact, comble ce qui manque sans jamais remplacer l'analyse propre de l'IA. Sinon (repli
    100% Python sans IA, selectionner_combo_cote_cible), le niveau de confiance (Faible/Moyen/
    Élevé, calculé depuis la PROBABILITÉ du modèle — corrigé le 09/10/2026, c'était l'edge
    avant, jamais estimé par l'IA — demande du 27/09/2026) reste affiché : c'est alors la
    SEULE justification du choix. Ne jamais afficher "edge None%" (constaté le
    30/09/2026, run 59 : une jambe sur un marché brut sans edge calculé affichait "edge None% ·
    Faible" dans le vrai message Telegram envoyé)."""
    blocs = []
    for s in selections_finales:
        p = s["pick"]
        raison = (s.get("raison_ia") or "").strip()
        guide = (p.get("guide") or "").strip()
        if raison and guide:
            detail = f"{raison} — {guide}"
        elif raison:
            detail = raison
        elif guide:
            detail = guide
        elif p.get("proba_modele_pct") is not None:
            edge_txt = f"edge {p['edge_pct']}% · " if p.get("edge_pct") is not None else ""
            detail = f"{edge_txt}{niveau_confiance(p['proba_modele_pct'])} (proba {p['proba_modele_pct']}%)"
        else:
            detail = "marché brut, sans calcul Python"
        # marche_affichage (ligne du point de vue de l'équipe sélectionnée) prioritaire sur
        # "marche" (ligne brute domicile-référencée, gardée pour les lookups internes
        # uniquement — voir _candidat) ; absent sur d'anciens tickets déjà en base, d'où le repli.
        marche_txt = p.get("marche_affichage") or p["marche"]
        blocs.append(f"⚽ *{s['match']}* — {marche_txt} : {p['selection']} @ {p['cote']} ({detail})")
    return "\n".join(blocs)


def _libelle_pari_court(selection_finale):
    """Pari en français courant, sur une ligne : « Total buts : moins de 4 », « Total 2 (Sparta) corners : plus de 2.5 »,
    « Sturm Graz ou Marseille (pas de match nul) ». Les marchés qu'on ne sait pas reformuler gardent
    leur libellé brut."""
    p = selection_finale["pick"]
    domicile, _, exterieur = selection_finale["match"].partition(" vs ")
    categorie, sel = p["categorie"], str(p["selection"])
    marche_txt = p.get("marche_affichage") or p["marche"]
    ligne = p.get("handicap")
    if ligne is None:
        m = re.search(r"\((-?[\d.]+)\)", marche_txt)
        ligne = m.group(1) if m else None
    if sel in ("Over", "Under") and ligne is not None and categorie.startswith("Total"):
        sens = "plus de" if sel == "Over" else "moins de"
        reste = categorie[len("Total"):].strip()
        equipe = None   # « Total 1 (domicile) » / « Total 2 (extérieur) » comme sur 1xBet
        for numero, nom in (("1", domicile), ("2", exterieur)):
            if reste.endswith(f"Équipe {numero}"):
                equipe, reste = f"Total {numero} ({nom})", reste[:-len(f"Équipe {numero}")].strip()
        sujet = {"cartons": "cartons jaunes", "tirs": "tirs vers le but"}.get(reste.lower(), (reste or "buts").lower())
        ligne_txt = f"{float(ligne):g}"
        return f"{equipe or 'Total'} {sujet} : {sens} {ligne_txt}"
    sel_norm = re.sub(r"[^a-z0-9]", "", sel.lower())
    if categorie == "Full Time Result":
        # Vocabulaire de 1xBet (demande du 25/10/2026 : « 1X2 ou W1 ou autre proche ») : W1 / X / W2
        if sel_norm == "1":
            return f"{domicile} gagne (1X2 : W1)"
        if sel_norm in ("x", "draw"):
            return "Match nul (1X2 : X)"
        if sel_norm == "2":
            return f"{exterieur} gagne (1X2 : W2)"
    if categorie == "Double Chance":
        return {"1x": f"{domicile} ou match nul", "x2": f"Match nul ou {exterieur}",
                "2x": f"Match nul ou {exterieur}",
                "12": f"{domicile} ou {exterieur} (pas de match nul)"}.get(sel_norm, f"Double chance {sel}")
    if categorie == "Draw No Bet":
        equipe = domicile if sel_norm in ("home", "1") else exterieur
        return f"{equipe} gagne (match nul remboursé)"
    if categorie == "BTTS":
        return "Les deux équipes marquent : " + ("Oui" if sel_norm in ("yes", "oui") else "Non")
    if categorie.startswith("Handicap") and sel_norm in ("1", "2") and ligne is not None:
        valeur = float(ligne) if sel_norm == "1" else -float(ligne)   # ligne exprimée côté domicile
        return f"{domicile if sel_norm == '1' else exterieur} {valeur:+g} (handicap)"
    return f"{marche_txt} : {sel}"


def rediger_ticket_court(selections_finales):
    """Ticket Telegram minimal (demande du 22/10/2026 : « simple et court, sur l'essentiel »,
    « noms d'équipes complets, écrit clair ») : par jambe, le match avec les noms complets
    puis le pari en français et la cote — sans guide, probabilité ni justification."""
    blocs = []
    for i, s in enumerate(selections_finales, start=1):
        blocs.append(f"{i}. {s['match']}\n    {_libelle_pari_court(s)} @{s['pick']['cote']}")
    return "\n".join(blocs)


_COTE_RE = re.compile(r"@\s*([\d]+[.,][\d]+)")


_EDGE_RE = re.compile(r"edge\s*(-?[\d]+(?:[.,][\d]+)?)\s*%", re.IGNORECASE)


_CONFIANCE_RE = re.compile(r"Confiance\s*:\s*([A-Za-zÀ-ÿ]+)", re.IGNORECASE)


def verifier_fidelite_ticket(texte, selections_finales):
    """Contrôle automatique post-génération (demande explicite du 10/10/2026, section
    TELEGRAM) : le LLM ne doit JAMAIS pouvoir modifier silencieusement une cote, un edge ou
    une probabilité (via le niveau de confiance, qui en dérive directement). Pour chaque
    jambe, vérifie que le bloc du ticket contient EXACTEMENT (à l'arrondi d'affichage près) :
    le marché (texte exact), la sélection (texte exact), la cote, l'edge si calculé, et un
    niveau de confiance cohérent avec la probabilité interne — jamais recalculés ici, juste
    comparés aux chiffres déjà produits par Agent 3 (calc_edge, niveau_confiance).

    Ne vérifie PAS "cote totale" ni "probabilité combinée" : ces deux chiffres sont ajoutés
    APRÈS le texte du LLM, par calculer_stats_combine() en pur Python (voir agent4_rediger_
    coupons) — jamais vus ni touchés par le LLM, donc déjà garantis exacts par construction.

    Renvoie False (jamais d'exception) si le texte est incomplet, mal formé, ou si UN SEUL
    chiffre ne correspond pas — l'appelant doit alors utiliser rediger_ticket_sans_ia (pur
    Python, toujours fidèle) plutôt que d'envoyer un texte potentiellement inventé."""
    if not texte:
        return False
    blocs = texte.split("⚽")[1:]  # le premier split est vide ou l'intro éventuelle
    if len(blocs) != len(selections_finales):
        return False
    for bloc, s in zip(blocs, selections_finales):
        p = s["pick"]
        marche_txt = p.get("marche_affichage") or p["marche"]
        if marche_txt not in bloc or str(p["selection"]) not in bloc:
            return False
        cote_trouvee = _COTE_RE.search(bloc)
        if not cote_trouvee or abs(float(cote_trouvee.group(1).replace(",", ".")) - p["cote"]) > 0.01:
            return False
        if p.get("edge_pct") is not None:
            edge_trouve = _EDGE_RE.search(bloc)
            if not edge_trouve or abs(float(edge_trouve.group(1).replace(",", ".")) - p["edge_pct"]) > 0.15:
                return False
        if p.get("proba_modele_pct") is not None:
            confiance_trouvee = _CONFIANCE_RE.search(bloc)
            if confiance_trouvee and confiance_trouvee.group(1).strip().lower() \
                    != niveau_confiance(p["proba_modele_pct"]).lower():
                return False
    return True


def calculer_stats_combine(selections_finales):
    """Calcule la cote totale (produit des cotes réelles, un fait brut) et, quand disponible,
    la probabilité combinée (produit des probabilités modèle de chaque jambe) — en pur Python,
    jamais laissé au LLM. Depuis le 30/09/2026, les marchés bruts (sans probabilité calculée,
    voir completer_avec_marches_bruts) peuvent composer un coupon : la probabilité combinée
    n'est alors plus calculable honnêtement (au moins une jambe sans probabilité modèle) et
    vaut None plutôt qu'un chiffre trompeur (ex: 0%, ou une probabilité partielle qui omet
    silencieusement une jambe)."""
    cote_totale = 1.0
    proba_combinee = 1.0
    for s in selections_finales:
        cote_totale *= s["pick"]["cote"]
        p = s["pick"].get("proba_modele_pct")
        if p is None:
            proba_combinee = None
        elif proba_combinee is not None:
            proba_combinee *= p / 100
    return round(cote_totale, 2), (round(proba_combinee * 100, 1) if proba_combinee is not None else None)


TELEGRAM_LIMITE_CARACTERES = 4096  # limite dure de l'API Telegram par message


def decouper_message_telegram(entete, section, pied, limite=TELEGRAM_LIMITE_CARACTERES):
    """Découpe une section (un profil de coupon) en un ou plusieurs messages Telegram sans
    jamais couper un bloc de match en plein milieu (chaque bloc commence par "⚽ "). Avec
    10 à 15 matchs détaillés dans un seul coupon, le texte dépasse régulièrement la limite
    dure de 4096 caractères de Telegram ('Bad Request: message is too long') — on répartit
    les blocs sur plusieurs messages successifs plutôt que de tronquer et perdre des matchs."""
    marge_continuation = len("\n\n_(suite 9/9 dans le message suivant...)_") + 10
    blocs = re.split(r"(?=\n⚽ )", section)  # garde le "⚽ " en tête de chaque bloc conservé
    morceaux = [blocs[0]]
    for bloc in blocs[1:]:
        disponible = limite - len(pied) - marge_continuation
        if len(morceaux[-1]) + len(bloc) > disponible and morceaux[-1].strip():
            morceaux.append(bloc)
        else:
            morceaux[-1] += bloc

    total = len(morceaux)
    messages = []
    for i, morceau in enumerate(morceaux, start=1):
        prefixe = entete if i == 1 else entete.split("\n", 1)[0] + f" — partie {i}/{total}\n\n"
        suffixe = pied if i == total else f"\n\n_(suite {i}/{total} dans le message suivant...)_"
        message = prefixe + morceau + suffixe
        if len(message) > limite:
            # Cas extrême : un seul bloc de match dépasse à lui seul la limite (ne devrait
            # jamais arriver en pratique) — filet de sécurité, coupe proprement ce morceau-là.
            coupe = limite - len("\n\n_[message tronqué — trop long pour Telegram]_")
            message = message[:coupe] + "\n\n_[message tronqué — trop long pour Telegram]_"
        messages.append(message)
    return messages
