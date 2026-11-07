import os
import uuid
import calendar
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / '.env')

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]
JWT_SECRET = os.environ['JWT_SECRET']
NO_ID = {"_id": 0}


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def parse_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def make_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"sub": user_id, "exp": exp}, JWT_SECRET, algorithm="HS256")


async def current_user(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Não autenticado")
    try:
        sub = jwt.decode(auth[7:], JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Sessão inválida")
    user = await db.users.find_one({"id": sub}, NO_ID)
    if not user:
        raise HTTPException(401, "Usuário não encontrado")
    return user


async def require_finance(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin" and user.get("finance_access") != "own":
        raise HTTPException(403, "Sem acesso ao financeiro")
    return user


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Apenas administradores")
    return user


def scope(user: dict) -> dict:
    return {} if user["role"] == "admin" else {"technician_id": user["id"]}


def with_status(t: dict) -> dict:
    if t.get("status") == "previsto" and t["date"] < today():
        t["status"] = "atrasado"
    return t


def status_filter(status: str) -> dict:
    if status == "atrasado":
        return {"$or": [{"status": "atrasado"}, {"status": "previsto", "date": {"$lt": today()}}]}
    if status == "previsto":
        return {"status": "previsto", "date": {"$gte": today()}}
    return {"status": status}


def month_day(year: int, month: int, day: int) -> str:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last)).isoformat()


async def generate_recurring() -> int:
    """Lança no mês corrente cada despesa fixa ativa que ainda não foi lançada."""
    t = datetime.now(timezone.utc).date()
    ym = t.strftime("%Y-%m")
    created = 0
    async for r in db.recurring.find({"active": True}, NO_ID):
        exists = await db.transactions.find_one({"recurring_id": r["id"], "date": {"$regex": f"^{ym}"}})
        if exists:
            continue
        await db.transactions.insert_one({
            "id": new_id(), "type": "saida", "date": month_day(t.year, t.month, r["day_of_month"]),
            "amount": r["amount"], "description": r["description"], "category_id": r["category_id"],
            "payment_method": r.get("payment_method", "pix"), "status": "previsto", "os_ids": [],
            "technician_id": None, "part_name": None, "reconciled": False, "source": "recorrente",
            "recurring_id": r["id"], "created_at": now_iso(),
        })
        created += 1
    return created
