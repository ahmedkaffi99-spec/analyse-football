# bet_agent — Backend (API + base de données)

API REST **FastAPI**, **entièrement privée**, au-dessus du pipeline `../bet_agent/` : elle lance le pipeline, **enregistre tout en base** (matchs, cotes 1xBet, données d'équipe, coupons, jambes), juge les résultats et calcule les performances dans la durée.

Le pipeline n'est pas dupliqué : le backend importe ses modules (`collecte_donnees`, `analyser_et_envoyer`, `verifier_resultats`) tels quels.

## Stack

| Couche | Choix |
|---|---|
| Langage | Python 3.10+ |
| API | FastAPI + Uvicorn · documentation `/docs` désactivée par défaut (`ACTIVER_DOCS=true`) |
| ORM | SQLAlchemy 2 |
| Base | **SQLite** par défaut (zéro installation) · **PostgreSQL / Supabase** en production via `DATABASE_URL` |
| Validation | Pydantic 2 |
| Tests | pytest (base SQLite temporaire, pipeline simulé, aucun appel réseau) |

## Base de données

```
runs ──< matchs ──< cotes
  │         ▲
  └──< coupons ──< jambes (match_id → matchs)
```

| Table | Contenu |
|---|---|
| `runs` | une exécution du pipeline ou un import : statut (`en_cours`, `termine`, `abandonne`, `erreur`), compteurs, envoi Telegram |
| `matchs` | équipes, ligue, coup d'envoi, ids OddsPapi / API-Football, score final, données d'équipe (JSON : stats, xG, Elo, classement, contexte web) |
| `cotes` | chaque sélection de chaque marché 1xBet collecté |
| `coupons` | les 3 profils du jour : cote totale, probabilité combinée, texte rédigé, statut (`en_attente`, `gagne`, `perdu`, `incertain`, `vide`) |
| `jambes` | chaque pari : marché, ligne, sélection, cote, proba modèle, edge, guide, résultat (`gagne`, `perdu`, `push`, `non_verifiable`) |

Le schéma PostgreSQL est dans [`schema.sql`](schema.sql), régénéré depuis les modèles par `python -m app.generer_schema_sql`. Il active le **RLS** sur chaque table : sans ça, Supabase rendrait les tables lisibles et modifiables avec la clé publique `anon`.

## Routes

**Toutes les routes exigent le jeton** (en-tête `X-API-Key: <API_TOKEN>`), lecture comprise, y compris `/api/sante`. Sans jeton valide : `401`. Sans `API_TOKEN` configuré côté serveur, toute l'API est fermée (`503`), jamais ouverte à tous.

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/sante` | état du serveur et de la base |
| GET | `/api/runs` · `/api/runs/{id}` | historique des runs (détail avec coupons et jambes) |
| POST | `/api/runs` | lance le pipeline en arrière-plan · corps : `{"envoyer_telegram": false, "rediger": true}` |
| POST | `/api/runs/{id}/verification` | juge les jambes d'un run dont les matchs sont terminés |
| GET | `/api/coupons` | filtres `jour`, `profil`, `statut` |
| GET | `/api/coupons/{id}` | un coupon et ses jambes |
| POST | `/api/coupons/verification` | juge toutes les jambes en attente (cron du soir) |
| GET | `/api/matchs` · `/api/matchs/{id}` | matchs (filtres `jour`, `run_id`) · détail avec toutes les cotes |
| GET | `/api/statistiques` | taux de réussite et rendement (1 unité par coupon) par profil, réussite par type de pari |
| POST | `/api/imports` | importe `{"collecte": <donnees_collectees.json>, "ticket": <ticket_du_jour.json>}` |

`/docs`, `/redoc` et `/openapi.json` sont **désactivés par défaut** (ils décrivent toute l'API). `ACTIVER_DOCS=true` les réactive pour développer : ils ne contiennent aucune donnée, et chaque appel depuis `/docs` exige le jeton (bouton **Authorize**).

Exemple :
```bash
curl -H "X-API-Key: $API_TOKEN" "http://localhost:8000/api/coupons?jour=2026-09-25"
```

**Sécurité :** l'envoi Telegram est désactivé par défaut. Un seul run peut tourner à la fois (sinon 409). Les clés API sont masquées dans les erreurs enregistrées en base.

## Installation

```bash
cd backend
pip install -r requirements-dev.txt
cp .env.example .env            # renseigner API_TOKEN (+ DATABASE_URL pour Supabase)
# les clés du pipeline restent dans ../bet_agent/envi.local
python -m pytest -q             # tests
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Pour explorer l'API dans le navigateur : `ACTIVER_DOCS=true` dans `.env`, puis http://localhost:8000/docs → **Authorize** → ton jeton.

### Supabase
1. Dans Supabase, ouvre **SQL Editor** et exécute `schema.sql` (optionnel : le backend crée aussi les tables au démarrage).
2. Mets la chaîne de connexion PostgreSQL dans `DATABASE_URL` : **Project Settings → Database**, préfixe `postgresql+psycopg://`. Ce n'est pas `SUPABASE_URL`, qui est l'URL de l'API REST.

### Termux (Android)
FastAPI dépend de `pydantic-core`, compilé en Rust : `pkg install rust` avant le `pip install`. Sinon, héberge le backend ailleurs et garde le cron Termux pour le pipeline, en important ses fichiers (voir ci-dessous).

## Utilisation avec cron

**Option A — le backend pilote tout :**
```cron
0 12 * * *       curl -s -X POST localhost:8000/api/runs -H "X-API-Key: $API_TOKEN" -H "Content-Type: application/json" -d '{"envoyer_telegram": true}'
*/30 14-23 * * * curl -s -X POST localhost:8000/api/coupons/verification -H "X-API-Key: $API_TOKEN"
```

**Option B — le pipeline Termux actuel continue, le backend archive :**
```bash
python -m app.importer --collecte ../bet_agent/donnees_collectees.json --ticket ../bet_agent/ticket_du_jour.json
```

## Structure

```
backend/
├── app/
│   ├── main.py                 application FastAPI
│   ├── config.py               DATABASE_URL, API_TOKEN, chemins
│   ├── database.py             moteur SQLAlchemy, sessions
│   ├── models.py               tables
│   ├── schemas.py              formats d'entrée/sortie de l'API
│   ├── securite.py             jeton X-API-Key exigé sur toutes les routes
│   ├── importer.py             import JSON en ligne de commande
│   ├── generer_schema_sql.py   régénère schema.sql
│   ├── routers/                runs, coupons, matchs, santé/statistiques/imports
│   └── services/
│       ├── pipeline.py         pont vers ../bet_agent, remise à zéro des caches, masquage des clés
│       ├── persistance.py      écriture des collectes et coupons en base
│       ├── runs.py             exécution d'un run
│       ├── verification.py     jugement des jambes (logique de verifier_resultats.py)
│       └── statistiques.py     performances
├── tests/
├── schema.sql
├── requirements.txt / requirements-dev.txt
└── .env.example
```
