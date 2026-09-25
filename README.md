# analyse-football

Analyse automatique des matchs de football et génération de coupons combinés 1xBet.

| Dossier | Contenu |
|---|---|
| [`bet_agent/`](bet_agent/README.md) | le **pipeline** : collecte des matchs et cotes, modèle de Poisson, 3 coupons, rédaction IA, Telegram, vérification des résultats |
| [`backend/`](backend/README.md) | l'**API REST + base de données** (FastAPI, SQLAlchemy, SQLite ou Supabase/PostgreSQL) : historique, résultats, statistiques |
| `analyses/` | analyses manuelles de journées (ex. 22/09/2026) |

Démarrage rapide :

```bash
pip install -r backend/requirements-dev.txt
cp bet_agent/envi.local.example bet_agent/envi.local   # clés API du pipeline
cp backend/.env.example backend/.env                   # API_TOKEN, DATABASE_URL
cd backend && python -m pytest -q && uvicorn app.main:app --port 8000
```

Les secrets (`envi.local`, `.env`) ne sont jamais versionnés.
