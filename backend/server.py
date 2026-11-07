import asyncio
import logging
import os
from contextlib import suppress
from typing import Optional

from fastapi import FastAPI, APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import ASCENDING, IndexModel
from starlette.middleware.cors import CORSMiddleware

from core import db, client, current_user, require_admin, make_token, generate_recurring
from routes_finance import router as finance_router
from routes_control import router as control_router
from routes_automation import router as automation_router
from routes_sync import router as sync_router
from seed import seed

INDEXES = {
    "users": [IndexModel([("id", ASCENDING)], name="id", unique=True)],
    "categories": [IndexModel([("id", ASCENDING)], name="id", unique=True)],
    "transactions": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("date", ASCENDING)], name="date"),
        IndexModel([("technician_id", ASCENDING)], name="tech"),
        IndexModel([("os_ids", ASCENDING)], name="os_ids"),
        IndexModel([("recurring_id", ASCENDING)], name="recurring"),
    ],
    "service_orders": [IndexModel([("id", ASCENDING)], name="id", unique=True)],
    "bank_transactions": [IndexModel([("id", ASCENDING)], name="id", unique=True)],
    "webhook_events": [IndexModel([("event_id", ASCENDING)], name="event_id", unique=True)],
    "cron_runs": [IndexModel([("run_id", ASCENDING)], name="run_id", unique=True)],
    "sync_runs": [IndexModel([("finished_at", ASCENDING)], name="finished_at")],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:
                logging.getLogger(__name__).error("ensure_indexes(%s): %s", collection, exc)

app = FastAPI()
api_router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    user_id: str


class UserUpdate(BaseModel):
    commission_pct: Optional[float] = None
    finance_access: Optional[str] = None


@api_router.get("/")
async def root():
    return {"message": "Financeiro API"}


@api_router.get("/auth/demo-users")
async def demo_users():
    return await db.users.find({}, {"_id": 0, "id": 1, "name": 1, "role": 1, "finance_access": 1}).to_list(100)


@api_router.post("/auth/demo-login")
async def demo_login(body: LoginIn):
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    return {"token": make_token(user["id"]), "user": user}


@api_router.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


@api_router.get("/users")
async def list_users(_: dict = Depends(require_admin)):
    return await db.users.find({}, {"_id": 0}).to_list(100)


@api_router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, _: dict = Depends(require_admin)):
    data = body.model_dump(exclude_none=True)
    if "finance_access" in data and data["finance_access"] not in ("own", "none"):
        raise HTTPException(400, "Acesso inválido")
    res = await db.users.update_one({"id": user_id, "role": "tecnico"}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(404, "Técnico não encontrado")
    return await db.users.find_one({"id": user_id}, {"_id": 0})


app.include_router(api_router)
app.include_router(finance_router)
app.include_router(control_router)
app.include_router(automation_router)
app.include_router(sync_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


@app.on_event("startup")
async def startup():
    app.state.index_task = asyncio.create_task(ensure_indexes())
    await seed()
    await generate_recurring()


@app.on_event("shutdown")
async def shutdown_db_client():
    app.state.index_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.index_task
    client.close()
