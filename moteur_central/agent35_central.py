"""Validation IA du moteur central (demande explicite du 10/10/2026) : "L'Agent 3.5 ne doit pas
pouvoir remplacer arbitrairement une sélection validée par le moteur central. Le moteur central
calcule d'abord la sélection. L'IA peut seulement : vérifier la cohérence ; signaler un problème ;
proposer une alternative parmi les candidats déjà validés. Toute décision finale doit être
contrôlable par Python."

Différence volontaire avec bet_agent.agent35_validation_ia (qui peut remplacer librement une
jambe sur un marché mesuré moins fiable) : ici, une proposition de remplacement n'est JAMAIS
appliquée sur la seule parole de l'IA — Python revalide avec le MÊME score_central et REFUSE
toute proposition qui dégraderait le score moyen du combo ou romprait la diversité."""

from moteur_central.score_central import score_central


def verifier_coherence(combo, pool):
    """Vérifications purement Python (aucune IA) : chaque jambe du combo vient bien du pool
    déjà validé, chaque match n'apparaît qu'une fois. Une anomalie ici est un bug du moteur
    central lui-même — jamais quelque chose que l'IA doit « réparer »."""
    problemes = []
    matchs = [c.match for c in combo]
    if len(matchs) != len(set(matchs)):
        problemes.append("plusieurs jambes sur le même match dans le combo")
    pool_cles = {(c.match, c.marche, c.selection) for c in pool}
    for c in combo:
        if (c.match, c.marche, c.selection) not in pool_cles:
            problemes.append(f"{c.match} / {c.marche} / {c.selection} n'appartient pas au pool déjà validé")
    return problemes


def proposer_alternative_ia(combo, pool, proposition):
    """proposition : {"ancien": (match, marche, selection), "nouveau": (match, marche, selection)}.
    "nouveau" DOIT désigner un candidat déjà présent dans pool (jamais un chiffre inventé par
    l'IA) ET le remplacement ne doit ni dégrader le score moyen du combo, ni rompre la diversité
    (un match déjà présent ailleurs dans le combo). Renvoie (combo_final, appliquee: bool, raison)."""
    ancien_cle, nouveau_cle = proposition.get("ancien"), proposition.get("nouveau")
    ancien = next((c for c in combo if (c.match, c.marche, c.selection) == ancien_cle), None)
    nouveau = next((c for c in pool if (c.match, c.marche, c.selection) == nouveau_cle), None)

    if ancien is None:
        return combo, False, "jambe à remplacer absente du combo actuel"
    if nouveau is None:
        return combo, False, "candidat proposé absent du pool déjà validé — jamais appliqué sans validation Python"
    autres_matchs = {c.match for c in combo if c is not ancien}
    if nouveau.match != ancien.match and nouveau.match in autres_matchs:
        return combo, False, "le candidat proposé romprait la diversité (match déjà présent dans le combo)"

    score_avant = sum(score_central(c)[0] for c in combo) / len(combo)
    combo_propose = [nouveau if c is ancien else c for c in combo]
    score_apres = sum(score_central(c)[0] for c in combo_propose) / len(combo_propose)
    if score_apres < score_avant:
        return combo, False, f"score moyen dégradé ({score_apres:.4f} < {score_avant:.4f}) — refusé"
    return combo_propose, True, f"remplacement appliqué ({score_avant:.4f} -> {score_apres:.4f})"
