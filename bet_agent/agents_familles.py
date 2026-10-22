"""Les 10 agents spécialistes par famille de marchés (20/10/2026, demande explicite : "ajoute les
10 agents en production").

Les agents travaillent en parallèle (un appel IA par famille, tous lancés ensemble).
Chaque agent connaît UNE famille de marchés, ses faits MESURÉS en production (audit des 10
agents, vrais coupons dédupliqués + backtests walk-forward) et passe en revue les candidats de sa
famille AVANT que le stratège IA ne compose le coupon :
  1. Python (veto dur, déterministe) : edge suspect (> EDGE_MAX_AGENT, au-delà les paris réels
     tombent à 34 % de réussite pour 62 % annoncés) ou catégorie exclue.
  2. IA (un appel DeepSeek par famille présente dans le catalogue, voir ae.appel_llm) : lit les
     faits mesurés de sa famille et peut ÉCARTER des candidats avec une raison. L'IA ne peut jamais
     écarter plus de la moitié d'une famille, ni inventer un pari : seuls les identifiants du
     catalogue sont acceptés.
Toute défaillance (budget IA épuisé, réponse invalide) laisse le catalogue inchangé — jamais un
run bloqué. Désactivable : AGENTS_FAMILLES_ACTIFS=0."""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import analyser_et_envoyer as ae

EDGE_MAX_AGENT = 20.0
PART_MAX_ECARTEE = 0.5

# (id, nom, catégories exactes, faits mesurés). Tout ce qui n'est dans aucune liste → "derives".
FAMILLES = (
    ("resultat", "Résultat 1X2 / Double Chance",
     ("Double Chance", "Double Chance Full Time", "Full Time Result", "Draw No Bet"),
     "Backtest 6997 matchs (5 championnats) : P(1X) est calibrée en moyenne (+0,5 pt) mais "
     "surestimée de 4 à 5 pts quand l'équipe à domicile est l'OUTSIDER (Elo domicile+avantage < "
     "Elo extérieur). En production (dédupliqué) : 1X = 7/21 (33 %) pour ~69 % annoncé ; 12 = 10/11 "
     "(91 %) pour 76 % ; 2X = 7/9 (78 %) pour 69 %. Méfie-toi d'un 1X avec un gros edge sur un "
     "match où l'équipe à domicile est nettement plus faible."),
    ("buts_total", "Buts Total du match",
     ("Total", "Over Under Full Time", "Pair/Impair"),
     "Après déduplication, le signal « Over 3.5 sous-performe de 15 pts » était un artefact des "
     "runs répétés (écart réel +1,1 pt). Lissage additif du xG buts appliqué le 17/10/2026."),
    ("buts_equipe", "Buts par équipe / Win To Nil",
     ("Total Équipe 1", "Total Équipe 2", "Over Under Team 1", "Over Under Team 2",
      "Win To Nil Équipe 1", "Win To Nil Équipe 2", "Team 1 Win To Nil", "Team 2 Win To Nil",
      "Team 1 Clean Sheet", "Team 2 Clean Sheet", "Clean Sheet Équipe 1", "Clean Sheet Équipe 2"),
     "Motif observé (n=23, pas encore significatif) : les « Over » d'équipe 1 sont à surveiller. "
     "Les lignes d'équipe à cote > 4 sont des paris longs à faible probabilité."),
    ("btts", "BTTS (les deux équipes marquent)",
     ("BTTS", "Both Teams To Score"),
     "Exclu du 03/10 au 20/10/2026 (35 paris à 48 % réel pour ~63 % annoncé) mais ces paris "
     "datent d'AVANT le lissage additif du 17/10. Réintégré le 20/10/2026 en essai borné : à "
     "remesurer après 2 semaines."),
    ("handicap", "Handicaps (asiatique, européen)",
     ("Handicap", "Handicap Asiatique", "Asian Handicap", "European Handicap"),
     "Backtest de calibration du handicap fait le 17/10/2026 (lissage additif K_LISSAGE_BUTS). "
     "Aucun écart structurel mesuré depuis."),
    ("corners", "Corners",
     ("Total Corners", "Handicap Corners", "Corners - Over Under Full Time",
      "Total Corners Équipe 1", "Total Corners Équipe 2"),
     "Handicap Corners EXCLU (mesure réelle dédupliquée n=6 : 33 % réel pour 63 % annoncé). "
     "Total Corners : pas d'écart structurel mesuré."),
    ("cartons", "Cartons",
     ("Total Cartons", "Total Cartons Équipe 1", "Total Cartons Équipe 2", "Handicap Cartons"),
     "Handicap Cartons EXCLU. L'effet arbitre (poids 0,6, backtest 6780 matchs) est appliqué "
     "quand l'arbitre est assigné et a >= 5 matchs d'historique ; sinon aucun ajustement — les "
     "cartons restent un marché très variable."),
    ("tirs", "Tirs",
     ("Total Tirs", "Total Tirs Cadrés", "Handicap Tirs", "Handicap Tirs Cadrés",
      "Total Tirs Équipe 1", "Total Tirs Équipe 2", "Total Tirs Cadrés Équipe 1", "Total Tirs Cadrés Équipe 2"),
     "Total Tirs : l'écart de 50 % réel pour 69 % annoncé (26 paris, tous « Under ») venait d'un BUG de "
     "calcul corrigé le 21/10/2026 (somme de Poisson tronquée à 25 : P(Over 25.5 | mu=26) valait 0). "
     "Depuis : binomiale négative (dispersion mesurée 1.35), priors recalés ; backtest sur 6 996 matchs : "
     "côté probable 60-70 % annoncé 63.6 % pour 63.4 % réel. Remesure en production en cours."),
    ("fautes", "Fautes et hors-jeux",
     ("Total Fautes", "Handicap Fautes", "Total Hors-jeux", "Handicap Hors-jeux",
      "Total Fautes Équipe 1", "Total Fautes Équipe 2", "Total Hors-jeux Équipe 1", "Total Hors-jeux Équipe 2"),
     "Marchés ajoutés au flux le 22/10/2026 : aucune mesure réelle en production. Backtest sur 6 996 matchs "
     "(fautes) : mu sous-estimé de 0.56 avant recalage des priors, dispersion 1.22, calibré après ; hors-jeux "
     "non validés par backtest (statistique absente de l'historique). Traite ces paris avec prudence."),
)
FAMILLE_DERIVES = ("derives", "Marchés dérivés (score exact, mi-temps, marge de victoire...)",
                   "Aucune mesure réelle suffisante en production : paris longs, très variables.")

_PAR_CATEGORIE = {cat: f for f in FAMILLES for cat in f[2]}


def actif():
    return (os.getenv("AGENTS_FAMILLES_ACTIFS") or "1").strip().lower() not in ("0", "false", "non", "no")


def famille_de(categorie):
    """(id, nom, faits) de la famille d'une catégorie ; "derives" pour toute catégorie inconnue."""
    f = _PAR_CATEGORIE.get(categorie)
    return (f[0], f[1], f[3]) if f else FAMILLE_DERIVES


def veto_python(pick):
    """Raison du veto déterministe, ou None."""
    edge = pick.get("edge_pct")
    if edge is not None and edge > EDGE_MAX_AGENT:
        return f"edge suspect ({edge:g} % > {EDGE_MAX_AGENT:g} %)"
    if pick.get("categorie") in ae.CATEGORIES_EXCLUES:
        return f"catégorie exclue ({pick.get('categorie')})"
    return None


def _prompt_famille(fid, nom, faits, lignes):
    return (
        f"System: Tu es l'agent spécialiste « {nom} » d'un système de paris combinés. Tu ne connais QUE ta "
        "famille de marchés. Réponds UNIQUEMENT en français, avec UN objet JSON valide (aucun texte autour).\n\n"
        f"FAITS MESURÉS EN PRODUCTION POUR TA FAMILLE (données réelles, ne les contredis pas) :\n{faits}\n\n"
        "MISSION : parmi les candidats ci-dessous (probabilité et edge calculés par Python), écarte ceux qui te "
        "semblent peu fiables compte tenu de ces faits. Tu ne peux écarter qu'un identifiant de la liste, jamais "
        "plus de la moitié des candidats, et tu n'inventes jamais de pari ni de chiffre. Si rien n'est douteux, "
        "n'écarte rien.\n\n"
        "CANDIDATS :\n" + "\n".join(lignes) + "\n\n"
        'FORMAT JSON EXACT : {"ecartes": [{"id": "P3", "raison": "1 phrase concrète"}], '
        '"avis": [{"id": "P5", "note": "1 phrase courte pour le stratège"}]}'
    )


def _ligne(cid, c):
    p = c["pick"]
    return (f"- {cid} : {c['match']} — {p.get('marche_affichage') or p['marche']} → {p['selection']} @ {p['cote']} "
            f"(proba {p['proba_modele_pct']} %, edge {p['edge_pct']} %)")


def revoir_catalogue(catalogue, appel=None):
    """catalogue : {id: candidat} (voir agent_strategie.construire_catalogue). Renvoie
    (ids_ecartes, avis_par_id{id: texte}). Les vetos Python s'appliquent toujours ; l'IA de chaque
    famille ne s'ajoute que si le budget IA le permet."""
    appel = appel or ae.appel_llm
    familles = {}
    for cid, c in catalogue.items():
        familles.setdefault(famille_de(c["pick"].get("categorie"))[0], []).append(cid)

    ecartes, avis = set(), {}
    for cid, c in catalogue.items():
        raison = veto_python(c["pick"])
        if raison:
            ecartes.add(cid)
            avis[cid] = f"[écarté par l'agent {famille_de(c['pick'].get('categorie'))[1]}] {raison}"
    if ecartes:
        print(f"   🧑‍⚖️ [Agents familles] {len(ecartes)} pari(s) écarté(s) par veto Python.")

    # Les agents travaillent EN PARALLÈLE (20/10/2026, demande explicite) : un appel IA par
    # famille présente, tous lancés ensemble ; la fusion des résultats se fait ensuite dans
    # l'ordre des familles, dans le fil principal (aucun état partagé modifié par les fils).
    taches = []
    for fid, ids in familles.items():
        restants = [i for i in ids if i not in ecartes]
        if not restants:
            continue
        nom, faits = (next((f[1], f[3]) for f in FAMILLES if f[0] == fid) if fid != "derives"
                      else (FAMILLE_DERIVES[1], FAMILLE_DERIVES[2]))
        taches.append((fid, nom, faits, restants))
    if taches and ae.budget_ia_epuise():
        print("   ⏱️ [Agents familles] budget IA épuisé — vetos Python seulement.")
        return ecartes, avis

    def revue(tache):
        fid, nom, faits, restants = tache
        texte = appel(_prompt_famille(fid, nom, faits, [_ligne(i, catalogue[i]) for i in restants]),
                      max_tokens=3000, json_attendu=True)
        reponse = json.loads(texte) if isinstance(texte, str) else texte
        return reponse if isinstance(reponse, dict) else {}

    if taches:
        print(f"   🧑‍⚖️ [Agents familles] {len(taches)} agent(s) spécialiste(s) lancé(s) en parallèle...")
    with ThreadPoolExecutor(max_workers=max(1, len(taches)), thread_name_prefix="agent-famille") as pool:
        futurs = [(t, pool.submit(revue, t)) for t in taches]
    for (fid, nom, faits, restants), futur in futurs:
        try:
            reponse = futur.result()
            proposes = [e for e in (reponse.get("ecartes") or []) if isinstance(e, dict) and e.get("id") in restants]
        except Exception as e:
            print(f"   ⚠️ [Agent {nom}] réponse inexploitable ({ae._cause(e)[:120]}) — famille inchangée.")
            continue
        plafond = int(len(restants) * PART_MAX_ECARTEE)  # floor : une famille d'un seul candidat n'est jamais vidée
        for e in proposes[:plafond]:
            ecartes.add(e["id"])
            avis[e["id"]] = f"[écarté par l'agent {nom}] {str(e.get('raison') or '').strip()[:160]}"
        for a in (reponse.get("avis") or []):
            if isinstance(a, dict) and a.get("id") in restants and a["id"] not in ecartes and a.get("note"):
                avis[a["id"]] = f"[agent {nom}] {str(a['note']).strip()[:160]}"
        if proposes:
            print(f"   🧑‍⚖️ [Agent {nom}] {min(len(proposes), plafond)} pari(s) écarté(s) sur {len(restants)}.")
    return ecartes, avis
