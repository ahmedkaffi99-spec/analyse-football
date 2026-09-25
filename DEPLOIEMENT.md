# Mise en production — GitHub Actions + Supabase

Aucun téléphone ni serveur à gérer : **GitHub Actions** lance le pipeline chaque jour et vérifie les résultats le soir, **Supabase** (PostgreSQL) conserve tout l'historique.

```
GitHub Actions ─┬─ 10h00 UTC  Pipeline quotidien  → collecte, 3 coupons, rédaction IA → Supabase + Telegram
                ├─ 11h30 UTC  passage de secours   → relance seulement si aucun ticket aujourd'hui
                └─ 15h→23h UTC, toutes les heures  → juge les paris terminés → Supabase + bilan Telegram
```

| Workflow | Fichier | Remplace (Termux) |
|---|---|---|
| Pipeline quotidien | `.github/workflows/pipeline-quotidien.yml` | `orchestrateur.py` + `relancer_si_echec.py` |
| Vérification des résultats | `.github/workflows/verification-resultats.yml` | `verifier_resultats.py` |
| Tests | `.github/workflows/tests.yml` | — (lancé à chaque push) |

## Étape 1 — Récupérer la connexion Supabase

La base utilisée est ton projet existant **`nombre-mystere`** (`fpwsitpdkruoknwmgjzr`, Francfort), sans coût supplémentaire. Les tables sont dans un **schéma séparé `analyse_football`**, qui ne touche jamais aux autres données du projet. Ce schéma est **déjà créé** :

| Table | Rôle |
|---|---|
| `analyse_football.runs` | exécutions du pipeline |
| `analyse_football.matchs` | matchs, scores, données d'équipe |
| `analyse_football.cotes` | cotes 1xBet |
| `analyse_football.coupons` | les 3 coupons du jour |
| `analyse_football.jambes` | chaque pari et son résultat |

RLS actif sur les 5 tables, aucun accès pour les rôles publics `anon` / `authenticated` : seul le pipeline (rôle `postgres`) y lit et écrit.

Pour la chaîne de connexion, ouvre `nombre-mystere` → **Connect** (en haut) → **Connection string** → **Session pooler**. Elle ressemble à :

```
postgresql://postgres.fpwsitpdkruoknwmgjzr:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

1. Remplace `[YOUR-PASSWORD]` par le mot de passe de la base (oublié ? **Project Settings → Database → Reset database password**).
2. Remplace `postgresql://` par `postgresql+psycopg://`.

- Utilise bien le **Session pooler** : la connexion directe (`db.xxxx.supabase.co`) passe par IPv6, que GitHub Actions ne gère pas.
- Ce n'est **pas** `SUPABASE_URL` (l'URL de l'API REST) ni la clé `service_role`.
- Le schéma `analyse_football` est la valeur par défaut (`DB_SCHEMA`) : rien d'autre à configurer.

## Étape 2 — Ajouter les secrets dans GitHub

Dépôt → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, un par ligne :

| Secret | Obligatoire | Valeur |
|---|---|---|
| `DATABASE_URL` | ✅ | la chaîne de l'étape 1 |
| `ODDSPAPI_KEY` | ✅ | comme dans `envi.local` |
| `API_FOOTBALL_KEY` | ✅ | |
| `TELEGRAM_TOKEN` | ✅ | |
| `TELEGRAM_CHAT_ID` | ✅ | |
| `GROQ_API_KEY` | ✅ | |
| `GEMINI_API_KEY` | recommandé | repli LLM |
| `OPENROUTER_API_KEY` | recommandé | repli LLM |
| `SERPER_API_KEY` | recommandé | contexte web |
| `FOOTBALL_DATA_API_KEY` | recommandé | classements |
| `THESPORTSDB_API_KEY` | optionnel | sinon clé publique partagée |

Les secrets ne sont jamais visibles, même dans les logs (GitHub les remplace par `***`).

## Étape 3 — Fusionner dans `main`

GitHub ne lance les tâches planifiées **que depuis la branche par défaut** (`main`). Fusionne la branche de travail dans `main` (pull request → **Merge**).

## Étape 4 — Premier essai à la main

Onglet **Actions** → **Pipeline quotidien** → **Run workflow**. Laisse la case « Envoyer les coupons sur Telegram » **décochée** pour un premier essai : le run s'enregistre dans Supabase sans rien envoyer. Le journal du job affiche les coupons produits. La collecte brute est téléchargeable 7 jours (section **Artifacts**).

Ensuite, tout est automatique. Les runs planifiés, eux, **envoient sur Telegram**.

## Horaires

Les heures sont en **UTC** (Paris = UTC+2 l'été, UTC+1 l'hiver). Pour les changer, modifie les lignes `cron:` des workflows. GitHub peut démarrer une tâche planifiée avec quelques minutes de retard.

## Coût

Dépôt privé : **2 000 minutes gratuites par mois** sur GitHub Actions. Estimation : pipeline ≈ 20-30 min/jour, vérifications ≈ 1 min × 9/jour → environ **1 000 min/mois**. Suivi : **Settings → Billing and plans**. Supabase : aucun coût supplémentaire (projet `nombre-mystere` déjà existant, quelques Mo par mois).

## Consulter les données

- **Supabase** (`nombre-mystere`) → **Table Editor** → schéma **`analyse_football`** : tables `runs`, `matchs`, `cotes`, `coupons`, `jambes`.
- **API privée** (optionnelle, sur ton PC) : `cd backend && uvicorn app.main:app` avec le même `DATABASE_URL` et un `API_TOKEN` dans `backend/.env` — voir [`backend/README.md`](backend/README.md).
