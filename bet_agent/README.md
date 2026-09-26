# bet_agent — Pipeline automatique de coupons de paris football

Chaque jour, le pipeline collecte les matchs et les cotes 1xBet, calcule des probabilités (modèle de Poisson), compose **3 coupons combinés** de risque différent, les fait rédiger en français par un LLM, les envoie sur **Telegram**, puis vérifie les résultats le soir.

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
| **API-Football** | identité des matchs, stats par équipe (buts dom./ext., forme) | `API_FOOTBALL_KEY` | plan gratuit : 10 req/min, **saisons ≤ 2024 seulement** |
| **Understat** | xG / xGA de la saison en cours (5 grands championnats) | aucune | scraping HTML, 1 requête par ligue |
| **ClubElo** | rating Elo de tous les clubs | aucune | 1 requête par run |
| **football-data.org** | classement, points, forme (5 grands championnats) | `FOOTBALL_DATA_API_KEY` | 10 req/min |
| **TheSportsDB** | repli : forme récente (5 derniers matchs) | clé publique `3` (ou perso) | quota mondial partagé |
| **Serper** | contexte web (blessures, avant-match) | `SERPER_API_KEY` | — |

### IA (LLM)
| Rôle | Fournisseur / modèle | Repli |
|---|---|---|
| **Orchestrateur** (ancien `orchestrateur.py`, **non utilisé** sur GitHub Actions) | Groq · `openai/gpt-oss-120b` | message d'abandon Telegram |
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
          GitHub Actions (midi)
                        │
                 orchestrateur.py  ◄── LLM Groq (tool-calling)
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
| **2 — Stats & contexte** | `collecte_donnees.py` | Données | stats d'équipe (Understat → API-Football → TheSportsDB), Elo, classement, contexte web Serper |
| **3 — Calcul** | `analyser_et_envoyer.py` · `agent3_calcul_pool_candidats` | Calcul | buts attendus → probabilités Poisson → edge sur chaque marché → pool de candidats → 3 combinés |
| **3b — Stratège IA** | `agent_strategie.py` | IA | **analyse** chaque match (fiabilité, presse, Elo, écart modèle/marché), **planifie** une stratégie par profil et **choisit** les paris dans le catalogue de cotes réelles (par identifiant, jamais de cote inventée) ; Python **vérifie** (paris existants, 2 max par match, cote totale dans la cible) et renvoie ses calculs à l'IA qui corrige (3 allers-retours max) ; l'IA peut **s'abstenir** ; repli automatique (Monte Carlo) si elle échoue |
| **4 — Rédaction IA** | `analyser_et_envoyer.py` · `agent4_*` | IA | 3 tâches : analyse → pronostic + confiance → ticket pédagogique pour débutant |
| **5 — Livraison** | `analyser_et_envoyer.py` · `agent5_*` | Livraison | envoi Telegram, sauvegarde `ticket_du_jour.json` |
| **6 — Vérification** | `verifier_resultats.py` | Contrôle | attend la fin des matchs, récupère les scores, juge chaque jambe, envoie le bilan |
| **Filet de sécurité** | `relancer_si_echec.py` | — | relance l'orchestrateur si aucun ticket n'a été produit à midi |
| **Diagnostic** | `diagnostic.py` | — | teste chaque source une par une (clé, quota, réseau) |

---

## 4. Fonctionnalités

### Collecte
- Sélection automatique des matchs du jour avec cotes réelles, filtrée sur Ligue 1, Premier League, Serie A, Bundesliga, Liga (`FILTRE_LIGUES_UNIQUES`).
- Sélection manuelle possible (`MATCHS_MANUELS`), **ignorée automatiquement si sa date n'est pas celle du jour**.
- Rejet des équipes réserves/jeunes (II, U21, B team…).
- Correspondance des matchs **équipe par équipe** entre sources (seuil 80 %).
- Dédoublonnage des matchs, limitation de débit par API, retry réseau.

### Modèle mathématique
- Buts attendus, par ordre de priorité :
  1. **xG Understat de la saison en cours** (≥ 3 matchs par équipe) ;
  2. stats API-Football (saison 2024, signalées comme anciennes) ;
  3. estimation depuis les cotes (ligne Total et Handicap les plus équilibrées).
- Probabilités de **Poisson** sur : Total (match, équipe 1, équipe 2), BTTS, Double Chance, Draw No Bet, Handicap asiatique, Pair/Impair, Clean Sheet, Win to Nil, corners/cartons.
- Lignes quart (.25/.75) exclues des paris proposés.
- **Edge** = (proba modèle − proba implicite de la cote) / proba implicite.
- Sélection **« 12 » interdite** partout.

### Les 3 coupons (8 jambes chacun)
| Coupon | Cote totale visée |
|---|---|
| 🛡️ Coupon 1 — sûr | 5 à 10 |
| ⚖️ Coupon 2 — équilibré | 10 à 50 |
| 🔥 Coupon 3 — audacieux | 50 à 100 |

Recherche Monte Carlo pondérée (4000 essais) : cote dans la cible → maximum de matchs distincts → maximum de types de paris → meilleure probabilité moyenne. Avertissement automatique si plusieurs jambes viennent du même match (probabilité combinée optimiste).

### Rédaction et envoi
- Chaque jambe : match, marché avec sa ligne, cote, edge, confiance, **guide débutant** et **onglet 1xBet** (générés par Python, recopiés par le LLM).
- Contrôles : 8 blocs ⚽ présents, pas de « 12 », 3 essais maximum.
- Cote totale et probabilité combinée ajoutées **par Python**, pas par le LLM.

### Suivi
- Vérification des résultats après l'heure estimée de fin du dernier match (+130 min), sans consommer de quota avant.
- Bilan par coupon : ✅ gagné · ❌ perdu · ➖ remboursé · ❓ non vérifiable (corners/cartons).
- Un seul bilan envoyé par ticket.

---

## 5. Fichiers

| Fichier | Rôle | Versionné |
|---|---|---|
| `orchestrateur.py` | point d'entrée du run de midi | ✅ |
| `collecte_donnees.py` | Agents 1-2 | ✅ |
| `analyser_et_envoyer.py` | Agents 3-4-5 | ✅ |
| `verifier_resultats.py` | Agent 6 | ✅ |
| `relancer_si_echec.py` | relance de secours | ✅ |
| `diagnostic.py` | test des sources | ✅ |
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
python orchestrateur.py              # run complet (ENVOIE sur Telegram)
python verifier_resultats.py         # bilan du soir
```

En production, ces scripts ne sont plus lancés par cron : GitHub Actions exécute le pipeline via le backend (`python -m app.taches`), voir [`../DEPLOIEMENT.md`](../DEPLOIEMENT.md).

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
- [x] `diagnostic.py` teste Understat sur la saison en cours.

### ⏳ Prochaines étapes
1. **Mise en production** : suivre [`../DEPLOIEMENT.md`](../DEPLOIEMENT.md) (secrets GitHub, `DATABASE_URL` Supabase, fusion dans `main`).
2. **Handicaps asiatiques au-delà de ±2** : vérifier la convention de signe d'OddsPapi (incohérence constatée sur Troyes–Paris FC) ; en attendant, exclure ces lignes.
3. **Clés dans les messages d'erreur** : les URL d'erreur contiennent `apiKey=`. Masquées par GitHub dans les journaux Actions et par le backend en base, mais pas encore à la source (`print` du pipeline).
4. **Nettoyage** : `ODDS_API_KEY` et la clé `service_role` Supabase ne sont pas utilisées (le backend se connecte via `DATABASE_URL`).

### 💡 Améliorations possibles
- Normaliser les buts attendus par la moyenne de la ligue (modèle Dixon-Coles).
- Utiliser l'Elo ClubElo et le classement dans le calcul (aujourd'hui collectés mais pas utilisés).
- Tableau de bord du taux de réussite par coupon à partir de l'historique des bilans.
- Réduire la corrélation : interdire deux jambes contradictoires sur le même match.
