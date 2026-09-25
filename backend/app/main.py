from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import coupons, divers, matchs, runs


@asynccontextmanager
async def cycle_de_vie(_app):
    init_db()
    yield


app = FastAPI(
    title="bet_agent API",
    description="Backend du pipeline de coupons football : runs, matchs, cotes 1xBet, coupons, résultats et statistiques.",
    version="1.0.0",
    lifespan=cycle_de_vie,
)
for router in (divers.router, runs.router, coupons.router, matchs.router):
    app.include_router(router)
