from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.config import ACTIVER_DOCS
from app.database import init_db
from app.routers import coupons, divers, matchs, runs
from app.securite import exiger_jeton


@asynccontextmanager
async def cycle_de_vie(_app):
    init_db()
    yield


app = FastAPI(
    title="bet_agent API",
    description="Backend du pipeline de coupons football : runs, matchs, cotes 1xBet, coupons, résultats et statistiques.",
    version="1.0.0",
    lifespan=cycle_de_vie,
    # API entièrement privée : le jeton est exigé sur chaque route, lecture comprise.
    dependencies=[Depends(exiger_jeton)],
    docs_url="/docs" if ACTIVER_DOCS else None,
    redoc_url="/redoc" if ACTIVER_DOCS else None,
    openapi_url="/openapi.json" if ACTIVER_DOCS else None,
)
for router in (divers.router, runs.router, coupons.router, matchs.router):
    app.include_router(router)
