from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import (db, new_id, now_iso, today, parse_date, current_user, require_finance, require_admin,
                  scope, with_status, status_filter, generate_recurring)

router = APIRouter(prefix="/api")

METHODS = ("cartao", "pix", "dinheiro")
STATUSES = ("previsto", "pago", "atrasado")
GROUPS = {"entrada": ("servico", "peca", "taxa", "outros"), "saida": ("fixa", "variavel", "outra")}


class TxIn(BaseModel):
    type: str
    date: str
    amount: float = Field(gt=0)
    description: str
    category_id: str
    payment_method: str
    status: str
    os_ids: List[str] = []
    technician_id: Optional[str] = None
    part_name: Optional[str] = None


class LinksIn(BaseModel):
    os_ids: List[str]


class ReconcileIn(BaseModel):
    reconciled: bool


class CategoryIn(BaseModel):
    name: str
    type: str
    group: str
    color: str = "#2563EB"


class MoveIn(BaseModel):
    direction: str


class CompleteIn(BaseModel):
    payment_method: str = "pix"
    status: str = "previsto"


class OsIn(BaseModel):
    client: str
    technician_id: str
    service_value: float = 0
    fee_value: float = 0
    parts: List[dict] = []


def os_total(o: dict) -> float:
    return o["service_value"] + o["fee_value"] + sum(p["qty"] * p["unit_price"] for p in o["parts"])


async def complete_os_entries(o: dict, method: str, status: str):
    cats = {c["system_key"]: c["id"] async for c in db.categories.find({"system_key": {"$ne": None}}, {"_id": 0})}
    parts_value = sum(p["qty"] * p["unit_price"] for p in o["parts"])
    rows = [("servico", o["service_value"], f"Serviço OS #{o['number']} - {o['client']}", None),
            ("taxa", o["fee_value"], f"Taxa OS #{o['number']}", None),
            ("peca", parts_value, f"Peças OS #{o['number']}", ", ".join(p["name"] for p in o["parts"]) or None)]
    docs = [{"id": new_id(), "type": "entrada", "date": o["completed_at"], "amount": round(v, 2), "description": desc,
             "category_id": cats.get(key), "payment_method": method, "status": status, "os_ids": [o["id"]],
             "technician_id": o["technician_id"], "part_name": part, "reconciled": False, "source": "os",
             "recurring_id": None, "created_at": now_iso()} for key, v, desc, part in rows if v > 0]
    if docs:
        await db.transactions.insert_many(docs)


async def os_finance(o: dict) -> dict:
    txs = await db.transactions.find({"os_ids": o["id"]}, {"_id": 0}).to_list(500)
    cobrado = recebido = custo_saidas = 0.0
    for t in txs:
        share = t["amount"] / max(len(t["os_ids"]), 1)
        if t["type"] == "entrada":
            cobrado += share
            if t["status"] == "pago":
                recebido += share
        else:
            custo_saidas += share
    custo_pecas = sum(p["qty"] * p.get("unit_cost", 0) for p in o["parts"])
    custo = custo_saidas + custo_pecas
    return {"valor_os": round(os_total(o), 2), "cobrado": round(cobrado, 2), "recebido": round(recebido, 2),
            "a_receber": round(cobrado - recebido, 2), "custo": round(custo, 2), "custo_pecas": round(custo_pecas, 2),
            "custo_saidas": round(custo_saidas, 2), "lucro": round(cobrado - custo, 2),
            "lancamentos": [with_status(t) for t in txs]}


# ---------- Ordens de serviço (MOCK do sistema externo) ----------
def os_scope(user: dict) -> dict:
    return {} if user["role"] == "admin" else {"technician_id": user["id"]}


@router.get("/os")
async def list_os(user: dict = Depends(current_user)):
    orders = await db.service_orders.find(os_scope(user), {"_id": 0}).sort("number", -1).to_list(500)
    for o in orders:
        o["total"] = round(os_total(o), 2)
    return orders


@router.post("/os")
async def create_os(body: OsIn, _: dict = Depends(require_admin)):
    last = await db.service_orders.find({}, {"_id": 0, "number": 1}).sort("number", -1).limit(1).to_list(1)
    num = str(int(last[0]["number"]) + 1) if last else "1001"
    o = {"id": new_id(), "number": num, **body.model_dump(), "status": "aberta", "created_at": today(), "completed_at": None}
    await db.service_orders.insert_one(o)
    o.pop("_id", None)
    return o


@router.post("/os/{os_id}/complete")
async def complete_os(os_id: str, body: CompleteIn, user: dict = Depends(current_user)):
    o = await db.service_orders.find_one({"id": os_id, **os_scope(user)}, {"_id": 0})
    if not o:
        raise HTTPException(404, "OS não encontrada")
    if o["status"] == "concluida":
        raise HTTPException(409, "OS já concluída")
    o["status"], o["completed_at"] = "concluida", today()
    await db.service_orders.update_one({"id": os_id}, {"$set": {"status": "concluida", "completed_at": o["completed_at"]}})
    await complete_os_entries(o, body.payment_method, body.status)
    return {"ok": True}


@router.get("/os/{os_id}/finance")
async def get_os_finance(os_id: str, user: dict = Depends(require_finance)):
    o = await db.service_orders.find_one({"id": os_id, **os_scope(user)}, {"_id": 0})
    if not o:
        raise HTTPException(404, "OS não encontrada")
    return await os_finance(o)


# ---------- Categorias ----------
@router.get("/finance/categories")
async def list_categories(_: dict = Depends(require_finance)):
    return await db.categories.find({}, {"_id": 0}).sort("order", 1).to_list(500)


def validate_category(body: CategoryIn):
    if body.type not in GROUPS or body.group not in GROUPS[body.type]:
        raise HTTPException(400, "Tipo ou grupo inválido")


@router.post("/finance/categories")
async def create_category(body: CategoryIn, _: dict = Depends(require_admin)):
    validate_category(body)
    count = await db.categories.count_documents({})
    doc = {"id": new_id(), **body.model_dump(), "system_key": None, "order": count}
    await db.categories.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/finance/categories/{cat_id}")
async def update_category(cat_id: str, body: CategoryIn, _: dict = Depends(require_admin)):
    validate_category(body)
    cat = await db.categories.find_one({"id": cat_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "Categoria não encontrada")
    if cat.get("system_key") and body.type != cat["type"]:
        raise HTTPException(400, "Categoria do sistema não pode mudar de tipo")
    await db.categories.update_one({"id": cat_id}, {"$set": body.model_dump()})
    return await db.categories.find_one({"id": cat_id}, {"_id": 0})


@router.post("/finance/categories/{cat_id}/move")
async def move_category(cat_id: str, body: MoveIn, _: dict = Depends(require_admin)):
    cats = await db.categories.find({}, {"_id": 0}).sort("order", 1).to_list(500)
    idx = next((i for i, c in enumerate(cats) if c["id"] == cat_id), None)
    if idx is None:
        raise HTTPException(404, "Categoria não encontrada")
    j = idx - 1 if body.direction == "up" else idx + 1
    if 0 <= j < len(cats):
        cats[idx], cats[j] = cats[j], cats[idx]
        for i, c in enumerate(cats):
            await db.categories.update_one({"id": c["id"]}, {"$set": {"order": i}})
    return {"ok": True}


@router.delete("/finance/categories/{cat_id}")
async def delete_category(cat_id: str, _: dict = Depends(require_admin)):
    cat = await db.categories.find_one({"id": cat_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "Categoria não encontrada")
    if cat.get("system_key"):
        raise HTTPException(400, "Categoria usada pelo sistema não pode ser excluída")
    if await db.transactions.count_documents({"category_id": cat_id}) or await db.recurring.count_documents({"category_id": cat_id}):
        raise HTTPException(409, "Categoria em uso por lançamentos")
    await db.categories.delete_one({"id": cat_id})
    await db.budgets.delete_many({"category_id": cat_id})
    return {"ok": True}


# ---------- Lançamentos ----------
async def validate_tx(body: TxIn):
    if body.type not in GROUPS or body.payment_method not in METHODS or body.status not in STATUSES:
        raise HTTPException(400, "Tipo, forma de pagamento ou status inválido")
    cat = await db.categories.find_one({"id": body.category_id}, {"_id": 0})
    if not cat or cat["type"] != body.type:
        raise HTTPException(400, "Categoria inválida para este tipo")
    if body.os_ids and await db.service_orders.count_documents({"id": {"$in": body.os_ids}}) != len(set(body.os_ids)):
        raise HTTPException(400, "OS inválida")


@router.get("/finance/transactions")
async def list_transactions(
    user: dict = Depends(require_finance),
    type: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
    category_id: Optional[str] = None, technician_id: Optional[str] = None, status: Optional[str] = None,
    payment_method: Optional[str] = None, os_id: Optional[str] = None, limit: int = Query(2000, le=5000),
):
    await generate_recurring()
    q = {**scope(user)}
    if type:
        q["type"] = type
    if start or end:
        q["date"] = {**({"$gte": start} if start else {}), **({"$lte": end} if end else {})}
    if category_id:
        q["category_id"] = category_id
    if technician_id and user["role"] == "admin":
        q["technician_id"] = None if technician_id == "none" else technician_id
    if payment_method:
        q["payment_method"] = payment_method
    if os_id:
        q["os_ids"] = os_id
    if status:
        q = {"$and": [q, status_filter(status)]}
    txs = await db.transactions.find(q, {"_id": 0}).sort("date", -1).to_list(limit)
    return [with_status(t) for t in txs]


@router.post("/finance/transactions")
async def create_transaction(body: TxIn, _: dict = Depends(require_admin)):
    await validate_tx(body)
    doc = {"id": new_id(), **body.model_dump(), "reconciled": False, "source": "manual", "recurring_id": None,
           "created_at": now_iso()}
    await db.transactions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/finance/transactions/{tx_id}")
async def update_transaction(tx_id: str, body: TxIn, _: dict = Depends(require_admin)):
    await validate_tx(body)
    res = await db.transactions.update_one({"id": tx_id}, {"$set": body.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(404, "Lançamento não encontrado")
    return with_status(await db.transactions.find_one({"id": tx_id}, {"_id": 0}))


@router.delete("/finance/transactions/{tx_id}")
async def delete_transaction(tx_id: str, _: dict = Depends(require_admin)):
    if (await db.transactions.delete_one({"id": tx_id})).deleted_count == 0:
        raise HTTPException(404, "Lançamento não encontrado")
    await db.bank_transactions.update_many({"linked_tx_id": tx_id}, {"$set": {"handled": None, "linked_tx_id": None}})
    return {"ok": True}


@router.put("/finance/transactions/{tx_id}/links")
async def set_links(tx_id: str, body: LinksIn, _: dict = Depends(require_admin)):
    ids = list(dict.fromkeys(body.os_ids))
    if ids and await db.service_orders.count_documents({"id": {"$in": ids}}) != len(ids):
        raise HTTPException(400, "OS inválida")
    res = await db.transactions.update_one({"id": tx_id}, {"$set": {"os_ids": ids}})
    if res.matched_count == 0:
        raise HTTPException(404, "Lançamento não encontrado")
    return {"ok": True, "os_ids": ids}


@router.patch("/finance/transactions/{tx_id}/reconcile")
async def reconcile(tx_id: str, body: ReconcileIn, _: dict = Depends(require_admin)):
    res = await db.transactions.update_one({"id": tx_id}, {"$set": {"reconciled": body.reconciled}})
    if res.matched_count == 0:
        raise HTTPException(404, "Lançamento não encontrado")
    return {"ok": True}


# ---------- Visão geral ----------
def summarize(txs: list) -> dict:
    s = {"entradas_pagas": 0.0, "saidas_pagas": 0.0, "entradas_total": 0.0, "saidas_total": 0.0,
         "a_receber": 0.0, "a_pagar": 0.0, "atrasado_receber": 0.0}
    for t in txs:
        e = t["type"] == "entrada"
        s["entradas_total" if e else "saidas_total"] += t["amount"]
        if t["status"] == "pago":
            s["entradas_pagas" if e else "saidas_pagas"] += t["amount"]
        else:
            s["a_receber" if e else "a_pagar"] += t["amount"]
            if e and t["status"] == "atrasado":
                s["atrasado_receber"] += t["amount"]
    s["saldo"] = s["entradas_pagas"] - s["saidas_pagas"]
    s["saldo_previsto"] = s["entradas_total"] - s["saidas_total"]
    return {k: round(v, 2) for k, v in s.items()}


@router.get("/finance/overview")
async def overview(start: str, end: str, technician_id: Optional[str] = None, user: dict = Depends(require_finance)):
    await generate_recurring()
    q = {**scope(user)}
    if technician_id and user["role"] == "admin":
        q["technician_id"] = technician_id
    s, e = parse_date(start), parse_date(end)
    days = (e - s).days + 1
    ps, pe = (s - timedelta(days=days)).isoformat(), (s - timedelta(days=1)).isoformat()
    cur = [with_status(t) for t in await db.transactions.find({**q, "date": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(20000)]
    prev = [with_status(t) for t in await db.transactions.find({**q, "date": {"$gte": ps, "$lte": pe}}, {"_id": 0}).to_list(20000)]
    cats = {c["id"]: c async for c in db.categories.find({}, {"_id": 0})}
    users = {u["id"]: u async for u in db.users.find({}, {"_id": 0})}

    by_cat, ranking, series = {}, {}, {}
    for t in cur:
        c = cats.get(t["category_id"], {"name": "Sem categoria", "color": "#94A3B8"})
        key = (t["type"], t["category_id"])
        by_cat.setdefault(key, {"type": t["type"], "category_id": t["category_id"], "name": c["name"], "color": c["color"], "total": 0})
        by_cat[key]["total"] += t["amount"]
        if t["type"] == "entrada" and t.get("technician_id"):
            r = ranking.setdefault(t["technician_id"], {"technician_id": t["technician_id"],
                                                        "name": users.get(t["technician_id"], {}).get("name", "?"), "total": 0, "recebido": 0, "os": set()})
            r["total"] += t["amount"]
            if t["status"] == "pago":
                r["recebido"] += t["amount"]
            r["os"].update(t.get("os_ids", []))
        day = series.setdefault(t["date"], {"date": t["date"], "entradas": 0, "saidas": 0})
        day["entradas" if t["type"] == "entrada" else "saidas"] += t["amount"]
    rank = sorted(({**r, "os": len(r["os"]), "total": round(r["total"], 2), "recebido": round(r["recebido"], 2)}
                   for r in ranking.values()), key=lambda r: -r["total"])
    if user["role"] != "admin":
        rank = [r for r in rank if r["technician_id"] == user["id"]]

    alerts, due = [], []
    if user["role"] == "admin":
        from routes_control import budget_status
        alerts = [b for b in await budget_status() if b["pct"] >= 80]
        limit_day = (parse_date(today()) + timedelta(days=7)).isoformat()
        due = [with_status(t) for t in await db.transactions.find(
            {"type": "saida", "status": {"$ne": "pago"}, "date": {"$lte": limit_day}}, {"_id": 0}).sort("date", 1).to_list(50)]
    return {"current": summarize(cur), "previous": summarize(prev), "previous_range": {"start": ps, "end": pe},
            "by_category": sorted(by_cat.values(), key=lambda x: -x["total"]), "ranking": rank,
            "series": sorted(series.values(), key=lambda x: x["date"]), "budget_alerts": alerts, "due_soon": due}
