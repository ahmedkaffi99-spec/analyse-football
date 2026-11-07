"""Compare les trois moteurs (agent, central, déterministe) à partir de paris RÉGLÉS fournis dans un fichier JSON (aucun réseau, aucune base).

Usage : python outils/comparer_moteurs.py observations.json [--sortie rapport.md]
Format : {"agent": [obs, ...], "central": [obs, ...], "deterministe": [obs, ...]} ; obs = {"cle": [match, marche, selection], "jour": "AAAA-MM-JJ",
"p": 0-1, "p_marche": 0-1 ou null, "cote": >1, "issue": 1 | 0 | null, "marche": "famille"}. Les paris non réglés (issue null) sont exclus.
Le rapport applique moteur/evaluation.py : comparaison sur les MÊMES paris, Brier, log loss, calibration, face au marché, par marché, stabilité par jour, backtest
chronologique hors échantillon, forces et faiblesses. AUCUN classement tant que l'échantillon commun est inférieur à N_MIN_COMPARAISON."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from moteur import evaluation as ev  # noqa: E402


def charger(chemin):
    with open(chemin, encoding="utf-8") as f:
        brut = json.load(f)
    return {m: [dict(o, cle=tuple(o["cle"])) for o in obs] for m, obs in brut.items()}


def rapport(observations_par_moteur):
    comp = ev.comparer_moteurs(observations_par_moteur)
    L = ["# Comparaison des trois moteurs", "", f"**Verdict : {comp['verdict']}**", "",
         f"Paris réglés communs aux {len(observations_par_moteur)} moteurs : {comp['n_communs']} (seuil de comparaison : {ev.N_MIN_COMPARAISON}).", "",
         "| Moteur | Paris réglés (communs) | Brier | Log loss | Taux réel | Proba annoncée | Écart | ROI théorique | Brier marché | Bat le marché |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m, v in comp["moteurs"].items():
        g, mk = v["global"], v["face_au_marche"]
        L.append(f"| {m} | {g['n_regle']} | {g['brier']} | {g['log_loss']} | {g['taux_reussite']} | {g['proba_moyenne']} | {g['ecart_calibration']} | {g['roi']} | "
                 f"{mk['brier_marche']} | {mk['bat_le_marche']} (n={mk['n']}) |")
    for m, v in comp["moteurs"].items():
        L += ["", f"## {m}", "", f"- Paris réglés au total : {v['toutes_observations']['n_regle']} ({v['toutes_observations']['n_exclu']} exclus : non réglés ou sans probabilité)"]
        ff = v["forces_faiblesses"]
        L += [f"- Force : {x}" for x in ff["forces"]] + [f"- Faiblesse : {x}" for x in ff["faiblesses"]]
        bt = ev.backtest_chronologique(observations_par_moteur[m])
        L.append(f"- Backtest hors échantillon : " + (f"Brier brut {bt['brier_brut']} → calibré {bt['brier_calibre']} sur {bt['n_test']} paris ({bt['jours_test'][0]} à {bt['jours_test'][1]}) ; "
                                                      f"calibration {'utile' if bt['calibration_utile'] else 'non démontrée'}" if bt["disponible"] else f"indisponible ({bt['raison']})"))
        insuffisants = [k for k, mt in v["par_marche"].items() if not mt["suffisant"]]
        if insuffisants:
            L.append(f"- Marchés à échantillon insuffisant (< {ev.N_MIN_MARCHE}) : {', '.join(insuffisants)}")
        L.append(f"- Stabilité par jour : {len(ev.stabilite_par_jour(observations_par_moteur[m]))} jour(s) de paris réglés")
    L += ["", "Un écart de Brier ou de ROI n'est pas une preuve : vérifier l'échantillon, la stabilité par jour et la corrélation entre paris d'un même match.", ""]
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("observations")
    p.add_argument("--sortie")
    args = p.parse_args(argv)
    texte = rapport(charger(args.observations))
    if args.sortie:
        with open(args.sortie, "w", encoding="utf-8") as f:
            f.write(texte)
    else:
        print(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
