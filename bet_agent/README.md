# bet_agent — Pipeline automatique de coupons de paris football

Chaque jour, le pipeline collecte les matchs et TOUS les marchés/cotes 1xBet (200-300 par match, sans filtre), puis compose **3 coupons combinés** — sûr, équilibré, audacieux (cote totale cible différente pour chacun) — à partir d'un catalogue de cotes brutes : c'est l'IA qui analyse et juge la valeur de chaque pari (Python ne calcule plus de probabilité/edge à sa place), match par match, avant de choisir combien de paris inclure dans chaque coupon selon la qualité des données du jour. Les 3 coupons sont rédigés en français et envoyés en 3 messages **Telegram** séparés dans le même run, puis les résultats sont vérifiés le soir.

> ⚠️ Outil d'analyse à titre indicatif. Aucun modèle ne garantit un gain. Pariez de façon responsable.

---

## 1. Langages

| Langage | Où | Rôle |
|---|---|---|
| **Python 3** | tous les `.py` | tout le pipeline (collecte, calcul, orchestration, envoi) |
| **JSON** | `donnees_collectees.json`, `ticket_du_jour.json`, `memoire_agents.json` | échange de données entre les étapes |
| **Markdown (Telegram)** | messages envoyés | mise en forme des coupons (repli en texte brut si le Markdown casse) |
| **YAML** | `.github/workflows/` | planification quotidienne (GitHub Actions) |
| **Français** | code, commentaires, logs, messages | langue du projet et des coupons |

---

## 2. Stack technique

### Exécution
- **Exécution** : **GitHub Actions** (serveurs de GitHub, gratuit) — voir [`../DEPLOIEMENT.md`](../DEPLOIEMENT.md). Plus de Termux.
- **Base de données** : **Supabase** (PostgreSQL) via le backend [`../backend/`](../backend/README.md).
- **Planification** : workflows GitHub (midi UTC+secours, vérification le soir) → journaux dans l'onglet **Actions**.
- **Configuration** : `envi.local` (clés API, **jamais committé**, voir `envi.local.example`).

### Bibliothèques Python (`requirements.txt`)
| Paquet | Usage |
|---|---|
| `requests` + `urllib3` | appels HTTP, session avec retry automatique (429/5xx) |
| `tenacity` | retry métier (`@retry`) sur chaque appel API |
| `rapidfuzz` | correspondance approximative des noms d'équipes entre sources |
| `unidecode` | normalisation des noms (accents : Havířov → Havirov) |
| `python-dotenv` | chargement de `envi.local` |

### Sources de données
| Service | Donne | Clé | Limite connue |
|---|---|---|---|
| **OddsPapi** | liste des matchs + **toutes les cotes 1xBet** + scores finaux | `ODDSPAPI_KEY` | certificat intercepté (Fortinet) → `verify=False` sur ce seul domaine |
| **API-Football** | identité des matchs, stats par équipe (buts dom./ext., forme), classement, stats détaillées 10 derniers matchs (corners/cartons/fautes, 15 métriques, source des buts attendus — voir `calculer_xg_depuis_stats_detaillees`), confrontations directes, blessures/suspensions déclarées, prédictions propriétaires (second avis) | `API_FOOTBALL_KEY` | plan Pro (30/09/2026) : 300 req/min, 7 500/jour — réglable via `API_FOOTBALL_QUOTA_PAR_MINUTE`/`SAISON_MAX_PLAN_GRATUIT` (secrets) si repli sur un plan inférieur — consolidé le 30/09/2026 : remplace football-data.org, TheSportsDB, Understat et ClubElo (retirés du pipeline, demande explicite : ne garder qu'API-Football + OddsPapi + IA, hors Serper conservé pour son actualité fraîche) |
| **Serper** | contexte web (blessures, avant-match) | `SERPER_API_KEY` | — |

### IA (LLM)
| Rôle | Fournisseur / modèle | Repli |
|---|---|---|
| **Agent pilote** (`bet_agent/agent_pilote.py`, moteur alternatif activable via l'input `moteur=agent` du workflow `pipeline-quotidien.yml` ; remplace l'ancien `orchestrateur.py` — Groq tool-calling — supprimé le 10/10/2026, code mort non référencé) | DeepSeek (`agent_pilote.py`) | message d'abandon Telegram |
| **Rédaction** des coupons (3 tâches) | **OpenRouter** (modèles `openrouter/free`, puis 2 autres modèles gratuits ; liste modifiable via `OPENROUTER_MODELES`) | → ticket rédigé en Python si aucun modèle ne répond |

Le LLM **n'invente jamais un chiffre** : cotes, probabilités et edges sont calculés en Python. Il ne fait que décider et rédiger.

### Livraison
- **Telegram Bot API** (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) : un message par coupon (limite 4096 caractères).

### Clés présentes mais non utilisées par le code actuel
- `ODDS_API_KEY` (The Odds API, ancienne source du 1X2)
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` (aucun appel Supabase dans le code)

---

## 3. Architecture — les agents

```
          GitHub Actions (cron horaire, pipeline-quotidien.yml)
                        │
       backend/app/taches.py run  ◄── --moteur deterministe (défaut) ou agent (DeepSeek)
                        │
        ┌───────────────┼──────────────────────────┐
        ▼               ▼                          ▼
 collecter_donnees  generer_et_envoyer_       abandonner
 (Agents 1-2)       trois_coupons             (message Telegram)
        │           (Agents 3-4-5)
        ▼               │
 donnees_collectees ────┘──► ticket_du_jour.json
        .json                        │
                                     ▼
            GitHub Actions (soir, toutes les heures)
                        │
                verifier_resultats.py (Agent 6) ──► bilan Telegram
```

| Agent | Fichier / fonction | Pilier | Ce qu'il fait |
|---|---|---|---|
| **1 — Matchs & cotes** | `collecte_donnees.py` | Données | sélectionne 8 à 15 matchs (5 grands championnats en priorité), récupère tous les marchés 1xBet sauf le 1X2 |
| **2 — Stats & contexte** | `collecte_donnees.py` | Données | stats d'équipe (API-Football : 10 derniers matchs, classement, confrontations directes, blessures, prédictions), contexte web Serper |
| **3 — Calcul** | `analyser_et_envoyer.py` · `agent3_calcul_pool_candidats` | Calcul | buts attendus (API-Football) → probabilités Poisson → edge sur chaque marché → pool de candidats → 3 combinés |
| **3b — Stratège IA** | `agent_strategie.py` | IA | **analyse** chaque match (fiabilité, presse, confrontations directes, écart modèle/marché), **planifie** une stratégie par profil et **choisit** les paris dans le catalogue de cotes réelles (par identifiant, jamais de cote inventée) ; Python **vérifie** (paris existants, 2 max par match, cote totale dans la cible) et renvoie ses calculs à l'IA qui corrige (3 allers-retours max) ; l'IA peut **s'abstenir** ; repli automatique (Monte Carlo) si elle échoue |
| **4 — Rédaction IA** | `analyser_et_envoyer.py` · `agent4_*` | IA | 3 tâches : analyse → pronostic + confiance → ticket pédagogique pour débutant |
| **5 — Livraison** | `analyser_et_envoyer.py` · `agent5_*` | Livraison | envoi Telegram, sauvegarde `ticket_du_jour.json` |
| **6 — Vérification** | `verifier_resultats.py` (bibliothèque, appelée via `backend/app/services/verification.py`) | Contrôle | récupère les scores, juge chaque jambe, envoie le bilan |
| **Diagnostic** | `diagnostic.py` | — | teste chaque source une par une (clé, quota, réseau) — outil manuel |

`orchestrateur.py` et `relancer_si_echec.py` (ancien entrypoint Termux et son filet de
sécurité) ont été supprimés le 10/10/2026 : remplacés depuis le passage à GitHub Actions
par `backend/app/taches.py` + le cron natif du workflow (plus besoin de relance manuelle).

---

## 4. Fonctionnalités

### Collecte
- Sélection automatique des matchs du jour avec cotes réelles, filtrée sur Ligue 1, Premier League, Serie A, Bundesliga, Liga (`FILTRE_LIGUES_UNIQUES`).
- Sélection manuelle possible (`MATCHS_MANUELS`), **ignorée automatiquement si sa date n'est pas celle du jour**.
- En mode manuel, un **complément automatique** (`selectionner_matchs_du_jour`, mêmes règles que la sélection du jour) est ajouté à la suite des matchs manuels depuis le 01/10/2026 (demande explicite : "si les coupons ont une cote totale faible, ajoute une sélection automatique pour augmenter le nombre de matchs") — jamais à la place des matchs manuels (tous traités en premier, sans restriction), jamais en double emploi (déduplication par similarité de noms d'équipe, seuil 80 %).
- Rejet des équipes réserves/jeunes (II, U21, B team…).
- Correspondance des matchs **équipe par équipe** entre sources (seuil 80 %).
- Dédoublonnage des matchs, limitation de débit par API, retry réseau.

### Modèle mathématique
- Buts attendus, par ordre de priorité :
  1. **stats API-Football des 10 derniers matchs joués** (`calculer_xg_depuis_stats_detaillees`, nécessite `STATS_DETAILLEES_ACTIVE=true`) ;
  2. stats API-Football de saison (`/teams/statistics`) ;
  3. estimation depuis les cotes (ligne Total et Handicap les plus équilibrées).
- Probabilités de **Poisson** sur : Total (match, équipe 1, équipe 2), BTTS, Double Chance, Draw No Bet, Handicap asiatique, Pair/Impair, Clean Sheet, Win to Nil, corners/cartons.
- Lignes quart (.25/.75) exclues des paris proposés (jamais modélisées par Poisson ; visibles en marché brut, sans calcul, sous le nom "Handicap Asiatique").
- OddsPapi n'envoie en réalité qu'UN SEUL marché "Asian Handicap" (2 voies) qui couvre à la fois les lignes de quart ET les lignes entières/demi — mais 1xBet l'affiche à l'utilisateur sous DEUX onglets séparés selon la granularité de la ligne : "Asian Handicap" pour les lignes de quart, "Handicap" (tout court) pour les lignes entières/demi (vérifié le 01/10/2026 via captures 1xBet + requête Supabase : les cotes de nos lignes entières correspondent exactement à celles de l'onglet "Handicap" de 1xBet, pas de son onglet "Asian Handicap"). Le libellé categorie suit donc cette distinction : "Handicap Asiatique" (lignes de quart, en brut uniquement) vs "Handicap" (lignes entières/demi, modélisées par Poisson). OddsPapi expose en plus un marché réellement distinct "European Handicap" (3 voies 1/X/2, un vrai nul), jamais confondu avec les deux précédents.
- **Edge** = (proba modèle − proba implicite de la cote) / proba implicite.
- Sélection **« 12 »** (Double Chance domicile-ou-extérieur) : plus interdite depuis le 01/10/2026 (demande explicite) — modélisée en Poisson comme "1X"/"2X", traitée comme n'importe quel autre marché.

### Les 3 coupons du jour (sûr / équilibré / audacieux)
3 profils (`PROFILS_COUPON` dans `analyser_et_envoyer.py`), traités l'un après l'autre dans le MÊME run à partir d'un seul catalogue calculé une fois : **un seul pari par match** (`MAX_JAMBES_PAR_MATCH = 1`). Depuis le 01/10/2026 (demande explicite : "ne oblige pas l'IA à atteindre le 50+ et 15-50, mon but c'est tout cote individuel et total qui a la chance de réussite élevée"), la cote totale n'est **plus une contrainte de fourchette** — Python ne vérifie plus qu'elle tombe dans une cible précise. Seul le **nombre de jambes** différencie désormais les 3 profils : sûr 1-5, équilibré 6-9, audacieux 10-15. Un **plancher absolu** reste vérifié (même jour, demande explicite : "interdit les cote total moins de 5") : `agent_strategie.COTE_TOTALE_MIN = 5.0`, quel que soit le profil — pas de plafond haut en contrepartie. Le stratège IA choisit lui-même, pour CHAQUE profil, quels paris combiner dans cette fourchette de jambes, en priorisant la probabilité réelle de gain (le catalogue ne contient que des cotes brutes, aucune probabilité/edge calculée : c'est l'IA qui juge). Chaque coupon est envoyé dans son propre message Telegram.

Si l'IA échoue ou s'abstient sur un profil, la composition automatique (Monte Carlo pondéré, 4000 essais) prend le relais pour celui-là : cote dans la cible → maximum de matchs distincts → maximum de types de paris → meilleure probabilité moyenne. Avertissement automatique si plusieurs jambes viennent du même match (probabilité combinée optimiste).

`PROFILS_COUPON` reste une liste générique : en retirer ou en ajouter change le nombre de coupons composés, sans toucher au code du pipeline.

### Rédaction et envoi
- Chaque jambe : match, marché avec sa ligne, cote, edge, confiance, **guide débutant** et **onglet 1xBet** (générés par Python, recopiés par le LLM).
- Contrôles : autant de blocs ⚽ que de jambes attendues, pas de « 12 », 3 essais maximum.
- Cote totale et probabilité combinée ajoutées **par Python**, pas par le LLM.

### Suivi
- Vérification des résultats après l'heure estimée de fin du dernier match (+130 min), sans consommer de quota avant.
- Bilan par coupon : ✅ gagné · ❌ perdu · ➖ remboursé · ❓ non vérifiable (corners/cartons).
- Un seul bilan envoyé par ticket.

---

## 5. Fichiers

| Fichier | Rôle | Versionné |
|---|---|---|
| `collecte_donnees.py` | Agents 1-2 | ✅ |
| `analyser_et_envoyer.py` | Agents 3-4-5 | ✅ |
| `verifier_resultats.py` | Agent 6 (bibliothèque, appelée via `backend/`) | ✅ |
| `agent_pilote.py` / `agent_strategie.py` | moteur alternatif (`--moteur agent`, DeepSeek) | ✅ |
| `diagnostic.py` | test des sources (outil manuel) | ✅ |
| `test_correctifs.py` | tests hors-ligne | ✅ |
| `MEMOIRE.md` | notes de développement | ✅ |
| `envi.local` | **clés API** | ❌ (`.gitignore`) |
| `*.log`, `*.json` générés | sorties de run (usage local) | ❌ (`.gitignore`) |

---

## 6. Installation et lancement

```bash
pip install -r requirements.txt
cp envi.local.example envi.local     # puis remplir les clés
python diagnostic.py                 # vérifier que chaque source répond
python -m unittest test_correctifs   # tests hors-ligne
```

`orchestrateur.py` (ancien run complet en CLI) a été supprimé le 10/10/2026 ; `verifier_resultats.py`
n'a plus de point d'entrée CLI depuis le 03/10/2026 (c'est maintenant une bibliothèque pure).
En production, le pipeline est lancé via le backend (`python -m app.taches run`/`verifier`),
exécuté par GitHub Actions (cron), voir [`../DEPLOIEMENT.md`](../DEPLOIEMENT.md).

---

## 7. Plan / feuille de route

### ✅ Fait
- [x] Le cron utilise enfin la version améliorée de la collecte (`abdi.py` → `collecte_donnees.py`).
- [x] Correspondance des matchs équipe par équipe (fin des faux positifs Benfica→Estrela, Malmö→Brommapojkarna).
- [x] Liste manuelle datée : ignorée si périmée.
- [x] Saison Understat automatique + xG de la saison en cours prioritaires.
- [x] Repli Telegram en texte brut si le Markdown est rejeté.
- [x] `.gitignore`, `envi.local.example`, `requirements.txt`, tests hors-ligne.

- [x] Backend API + base de données : voir [`../backend/`](../backend/README.md).
- [x] Plus de Termux : GitHub Actions + Supabase ([`../DEPLOIEMENT.md`](../DEPLOIEMENT.md)).
- [x] Certificat OddsPapi vérifié par défaut (`ODDSPAPI_SSL_NON_VERIFIE=true` seulement sur un réseau qui l'intercepte).
- [x] Understat et ClubElo retirés du pipeline (30/09/2026) : ne reste qu'API-Football, OddsPapi, Serper et les IA.

### ⏳ Prochaines étapes
1. **Mise en production** : suivre [`../DEPLOIEMENT.md`](../DEPLOIEMENT.md) (secrets GitHub, `DATABASE_URL` Supabase, fusion dans `main`).
2. **Handicaps asiatiques au-delà de ±2** : vérifier la convention de signe d'OddsPapi (incohérence constatée sur Troyes–Paris FC) ; en attendant, exclure ces lignes.
3. **Clés dans les messages d'erreur** : les URL d'erreur contiennent `apiKey=`. Masquées par GitHub dans les journaux Actions et par le backend en base, mais pas encore à la source (`print` du pipeline).
4. **Nettoyage** : `ODDS_API_KEY` et la clé `service_role` Supabase ne sont pas utilisées (le backend se connecte via `DATABASE_URL`).

### 💡 Améliorations possibles
- Normaliser les buts attendus par la moyenne de la ligue (modèle Dixon-Coles).
- Utiliser le classement API-Football dans le calcul (aujourd'hui collecté mais pas utilisé).
- Tableau de bord du taux de réussite par coupon à partir de l'historique des bilans.
- Réduire la corrélation : interdire deux jambes contradictoires sur le même match.
