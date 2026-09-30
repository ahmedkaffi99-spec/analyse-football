# Mise en production — GitHub Actions + Supabase

Aucun téléphone ni serveur à gérer : **GitHub Actions** lance le pipeline chaque jour et vérifie les résultats le soir, **Supabase** (PostgreSQL) conserve tout l'historique.

```
GitHub Actions ─┬─ 10h07 UTC  Pipeline quotidien  → collecte, coupon combiné IA → Supabase + Telegram
                ├─ 10h37, 11h07, 11h37 UTC         → secours : seulement si rien n'est parti sur Telegram
                └─ 15h13→23h13 UTC, chaque heure   → juge les paris terminés → Supabase + bilan Telegram
```

Minutes décalées exprès : GitHub saute souvent les tâches planifiées pile sur l'heure.

| Workflow | Fichier | Remplace (Termux) |
|---|---|---|
| Pipeline quotidien | `.github/workflows/pipeline-quotidien.yml` | `orchestrateur.py` + `relancer_si_echec.py` |
| Vérification des résultats | `.github/workflows/verification-resultats.yml` | `verifier_resultats.py` |
| Tests | `.github/workflows/tests.yml` | — (lancé à chaque push) |
| Envoyer sur Telegram | `.github/workflows/envoyer-telegram.yml` | — (à la main : envoie les coupons déjà calculés d'un run, ex. après un essai sans Telegram) |
| Tester l'API | `.github/workflows/tester-api.yml` | — (à la main et chaque lundi : vérifie l'API en ligne route par route) |

## Étape 1 — Le projet Supabase

La base est ton projet Supabase **`fpwsitpdkruoknwmgjzr`** (Francfort), **entièrement dédié à l'analyse** (anciennement « nombre-mystere », qui était vide) — aucun coût supplémentaire.

**Renommer le projet** (à faire une fois, dans le tableau de bord — impossible depuis les outils) : ouvre le projet → **Project Settings** → **General** → **Project name** → `analyse-football` → **Save**. L'identifiant `fpwsitpdkruoknwmgjzr` et la connexion ne changent pas.

Les tables sont **déjà créées** dans le schéma `public` (visibles directement dans **Table Editor**) :

| Table | Rôle |
|---|---|
| `runs` | exécutions du pipeline |
| `matchs` | matchs, scores, données d'équipe |
| `cotes` | cotes 1xBet |
| `coupons` | le(s) coupon(s) du jour (un seul par défaut) |
| `jambes` | chaque pari et son résultat |

**Sécurité** : RLS actif sur les 5 tables et **aucun droit** pour les rôles publics `anon` / `authenticated` — la clé publique du projet ne permet ni de lire ni d'écrire. Seul le pipeline (rôle `postgres`, via `DATABASE_URL`) y accède. Le backend réapplique ces protections à chaque démarrage.

**Mot de passe de la base** — c'est la seule information à fournir, rien à modifier à la main :
dans le projet → **Connect** → **Direct** → **Session pooler** → **Reset database password** → **Generate a password** → copie-le.

L'adresse de connexion (Session pooler `aws-0-eu-central-1.pooler.supabase.com:5432`, utilisateur `postgres.fpwsitpdkruoknwmgjzr`) est construite automatiquement par le programme à partir de ce mot de passe.

## Étape 2 — Ajouter les secrets dans GitHub

Dépôt → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Pour chaque ligne : **Name** = le nom de la 1re colonne, **Secret** = la valeur, puis **Add secret**.

| Secret | Obligatoire | Valeur |
|---|---|---|
| `SUPABASE_DB_PASSWORD` | ✅ | **uniquement le mot de passe** de la base (étape 1), collé tel quel |
| `ODDSPAPI_KEY` | ✅ | comme dans `envi.local` |
| `API_FOOTBALL_KEY` | ✅ | |
| `TELEGRAM_TOKEN` | ✅ | |
| `TELEGRAM_CHAT_ID` | ✅ | |
| `OPENROUTER_API_KEY` | ✅ | **seule IA utilisée** (rédaction des coupons) |
| `SERPER_API_KEY` | recommandé | contexte web |

Les secrets ne sont jamais visibles, même dans les logs (GitHub les remplace par `***`).

## Étape 3 — Fusionner dans `main`

GitHub ne lance les tâches planifiées **que depuis la branche par défaut** (`main`). Fusionne la branche de travail dans `main` (pull request → **Merge**).

## Étape 4 — Premier essai à la main

Onglet **Actions** → **Pipeline quotidien** → **Run workflow**. Laisse la case « Envoyer les coupons sur Telegram » **décochée** pour un premier essai : le run s'enregistre dans Supabase sans rien envoyer. Le journal du job affiche les coupons produits. La collecte brute est téléchargeable 7 jours (section **Artifacts**).

Ensuite, tout est automatique. Les runs planifiés, eux, **envoient sur Telegram**.

## Horaires

Les heures sont en **UTC** (Paris = UTC+2 l'été, UTC+1 l'hiver). Pour les changer, modifie les lignes `cron:` des workflows. GitHub peut démarrer une tâche planifiée avec quelques minutes de retard.

## Coût

Dépôt privé : **2 000 minutes gratuites par mois** sur GitHub Actions. Estimation : pipeline ≈ 20-30 min/jour, vérifications ≈ 1 min × 9/jour → environ **1 000 min/mois**. Suivi : **Settings → Billing and plans**. Supabase : aucun coût supplémentaire (projet déjà existant, quelques Mo par mois).

## Consulter les données

- **Supabase** (projet `analyse-football`) → **Table Editor** : tables `runs`, `matchs`, `cotes`, `coupons`, `jambes`.
- **API privée** (optionnelle, sur ton PC) : `cd backend && uvicorn app.main:app` avec le même `DATABASE_URL` et un `API_TOKEN` dans `backend/.env` — voir [`backend/README.md`](backend/README.md).

## Option avancée

Au lieu de `SUPABASE_DB_PASSWORD`, un secret `DATABASE_URL` peut contenir une chaîne de connexion PostgreSQL complète (copiée depuis Supabase telle quelle, `postgresql://…` accepté). Elle est prioritaire.

## Supabase Storage et Edge Function (déjà en place)

| Élément | Rôle |
|---|---|
| Bucket **`archives`** (privé) | chaque run y archive `AAAA-MM-JJ/run_<id>_collecte.json` (collecte brute) et `run_<id>_coupons.json` — conservés sans limite de durée (les artefacts GitHub disparaissent après 7 jours) |
| Edge Function **`api`** | API privée **en ligne**, sans serveur : `https://fpwsitpdkruoknwmgjzr.supabase.co/functions/v1/api/<route>` |
| Secret Vault **`api_token`** | jeton exigé par l'API (en-tête `X-API-Key`), généré aléatoirement ; le pipeline le lit directement dans le Vault pour archiver |

Routes de l'Edge Function (toutes avec `X-API-Key`) : `/sante`, `/runs`, `/runs/{id}`, `/coupons` (filtres `jour`, `profil`, `statut`), `/coupons/{id}`, `/matchs` (filtres `jour`, `run_id`), `/matchs/{id}` (avec toutes les cotes), `/statistiques`, `/archives` (liste ; `?prefixe=AAAA-MM-JJ`), `/archives/lien?chemin=...` (lien de téléchargement valable 1 h).

**Voir ton jeton** : Supabase → projet → **Project Settings** → **Vault** → secret `api_token` → afficher. Exemple :

```bash
curl -H "X-API-Key: TON_JETON" "https://fpwsitpdkruoknwmgjzr.supabase.co/functions/v1/api/coupons?jour=2026-09-26"
```

**Sécurité** : bucket privé sans policy (aucun accès avec la clé publique), fonctions SQL `api_jeton_valide` / `api_statistiques` exécutables uniquement par le rôle serveur `service_role`, qui n'a qu'un droit de **lecture** sur les tables. Le code de la fonction est versionné dans [`edge-functions/api/index.ts`](edge-functions/api/index.ts) (volontairement hors d'un dossier `supabase/`, pour ne pas déclencher les branches de prévisualisation payantes de l'intégration GitHub de Supabase).

Redéployer après modification : `supabase functions deploy api --no-verify-jwt --project-ref fpwsitpdkruoknwmgjzr` (depuis `edge-functions/`), ou demander à Claude.

## IA : OpenRouter uniquement

Toute la rédaction IA passe par **OpenRouter** (secret `OPENROUTER_API_KEY`). Les secrets `GROQ_API_KEY` et `GEMINI_API_KEY` ne sont plus utilisés : tu peux les supprimer de GitHub.
IA : **Groq, Gemini et OpenRouter en parallèle**, par vagues de 4 (la première réponse valide l'emporte). 1re vague : Groq `openai/gpt-oss-120b`, Gemini `gemini-3.8-flash` et 2 modèles gratuits d'OpenRouter ; puis Groq `qwen/qwen3.8-27b`, Gemini `gemini-3.7-flash` et les autres modèles gratuits d'OpenRouter (`nvidia/nemotron-3.5-lightning:free`, `qwen/qwen3.8-27b:free`, `google/gemma-4-31b-it:free`… jusqu'au routeur `openrouter/free`). Secrets : `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` (un fournisseur sans clé, ou dont la clé est refusée, est simplement écarté). L'IA dispose de 4 minutes au total par run (`BUDGET_IA_SECONDES`) et de 60 s par vague. Listes modifiables sans toucher au code avec les variables `GROQ_MODELES`, `GEMINI_MODELES`, `OPENROUTER_MODELES` (séparées par des virgules). Vérifier les clés : workflow « Tester les IA ».
Si OpenRouter ne répond pas, les coupons sont quand même produits : le ticket est rédigé automatiquement à partir des chiffres calculés.
