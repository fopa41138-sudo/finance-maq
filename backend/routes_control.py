from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import db, new_id, now_iso, today, require_finance, require_admin, generate_recurring, with_status

router = APIRouter(prefix="/api/finance")


class RecurringIn(BaseModel):
    description: str
    amount: float = Field(gt=0)
    category_id: str
    day_of_month: int = Field(ge=1, le=31)
    payment_method: str = "pix"
    active: bool = True


class BudgetIn(BaseModel):
    category_id: str
    monthly_limit: float = Field(gt=0)


class PayoutIn(BaseModel):
    technician_id: str
    amount: float = Field(gt=0)
    period_start: str
    period_end: str
    payment_method: str = "pix"
    note: Optional[str] = None


async def check_expense_category(cat_id: str):
    cat = await db.categories.find_one({"id": cat_id}, {"_id": 0})
    if not cat or cat["type"] != "saida":
        raise HTTPException(400, "Escolha uma categoria de saída")


# ---------- Despesas fixas ----------
@router.get("/recurring")
async def list_recurring(_: dict = Depends(require_admin)):
    await generate_recurring()
    items = await db.recurring.find({}, {"_id": 0}).sort("day_of_month", 1).to_list(500)
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    for r in items:
        t = await db.transactions.find_one({"recurring_id": r["id"], "date": {"$regex": f"^{ym}"}}, {"_id": 0})
        r["current"] = with_status(t) if t else None
    return items


@router.post("/recurring")
async def create_recurring(body: RecurringIn, _: dict = Depends(require_admin)):
    await check_expense_category(body.category_id)
    doc = {"id": new_id(), **body.model_dump(), "created_at": now_iso()}
    await db.recurring.insert_one(doc)
    doc.pop("_id", None)
    await generate_recurring()
    return doc


@router.put("/recurring/{rid}")
async def update_recurring(rid: str, body: RecurringIn, _: dict = Depends(require_admin)):
    await check_expense_category(body.category_id)
    if (await db.recurring.update_one({"id": rid}, {"$set": body.model_dump()})).matched_count == 0:
        raise HTTPException(404, "Despesa fixa não encontrada")
    await generate_recurring()
    return {"ok": True}


@router.delete("/recurring/{rid}")
async def delete_recurring(rid: str, _: dict = Depends(require_admin)):
    if (await db.recurring.delete_one({"id": rid})).deleted_count == 0:
        raise HTTPException(404, "Despesa fixa não encontrada")
    await db.transactions.delete_many({"recurring_id": rid, "status": {"$ne": "pago"}, "date": {"$gte": today()}})
    return {"ok": True}


# ---------- Metas e limites ----------
async def budget_status() -> list:
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    cats = {c["id"]: c async for c in db.categories.find({}, {"_id": 0})}
    out = []
    async for b in db.budgets.find({}, {"_id": 0}):
        spent = 0.0
        async for t in db.transactions.find({"category_id": b["category_id"], "type": "saida", "date": {"$regex": f"^{ym}"}}, {"_id": 0, "amount": 1}):
            spent += t["amount"]
        c = cats.get(b["category_id"], {})
        pct = round(spent / b["monthly_limit"] * 100, 1)
        out.append({**b, "category_name": c.get("name", "?"), "color": c.get("color", "#64748B"), "spent": round(spent, 2),
                    "pct": pct, "level": "estourado" if pct >= 100 else "alerta" if pct >= 80 else "ok", "month": ym})
    return sorted(out, key=lambda x: -x["pct"])


@router.get("/budgets")
async def list_budgets(_: dict = Depends(require_admin)):
    return await budget_status()


@router.post("/budgets")
async def upsert_budget(body: BudgetIn, _: dict = Depends(require_admin)):
    await check_expense_category(body.category_id)
    await db.budgets.update_one({"category_id": body.category_id},
                                {"$set": {"monthly_limit": body.monthly_limit}, "$setOnInsert": {"id": new_id()}}, upsert=True)
    return {"ok": True}


@router.delete("/budgets/{bid}")
async def delete_budget(bid: str, _: dict = Depends(require_admin)):
    if (await db.budgets.delete_one({"id": bid})).deleted_count == 0:
        raise HTTPException(404, "Limite não encontrado")
    return {"ok": True}


# ---------- Técnicos: fechamento ----------
@router.get("/technicians")
async def technicians_closing(start: str, end: str, user: dict = Depends(require_finance)):
    q = {"role": "tecnico"} if user["role"] == "admin" else {"id": user["id"]}
    techs = await db.users.find(q, {"_id": 0}).to_list(200)
    service_cats = [c["id"] async for c in db.categories.find({"type": "entrada", "group": "servico"}, {"_id": 0, "id": 1})]
    out = []
    for tech in techs:
        txs = await db.transactions.find({"technician_id": tech["id"], "type": "entrada",
                                          "date": {"$gte": start, "$lte": end}}, {"_id": 0}).to_list(5000)
        gerado = sum(t["amount"] for t in txs)
        recebido = sum(t["amount"] for t in txs if t["status"] == "pago")
        servico_pago = sum(t["amount"] for t in txs if t["status"] == "pago" and t["category_id"] in service_cats)
        servico_total = sum(t["amount"] for t in txs if t["category_id"] in service_cats)
        commission = servico_pago * tech.get("commission_pct", 0) / 100
        payouts = await db.payouts.find({"technician_id": tech["id"], "period_start": {"$lte": end},
                                         "period_end": {"$gte": start}}, {"_id": 0}).to_list(500)
        repassado = sum(p["amount"] for p in payouts)
        os_ids = {o for t in txs for o in t.get("os_ids", [])}
        out.append({"technician_id": tech["id"], "name": tech["name"], "commission_pct": tech.get("commission_pct", 0),
                    "finance_access": tech.get("finance_access"), "os_count": len(os_ids), "gerado": round(gerado, 2),
                    "recebido": round(recebido, 2), "servico_total": round(servico_total, 2),
                    "servico_pago": round(servico_pago, 2), "comissao": round(commission, 2),
                    "repassado": round(repassado, 2), "a_repassar": round(max(commission - repassado, 0), 2)})
    return sorted(out, key=lambda x: -x["gerado"])


@router.get("/payouts")
async def list_payouts(technician_id: Optional[str] = None, user: dict = Depends(require_finance)):
    q = {}
    if user["role"] != "admin":
        q["technician_id"] = user["id"]
    elif technician_id:
        q["technician_id"] = technician_id
    return await db.payouts.find(q, {"_id": 0}).sort("paid_at", -1).to_list(500)


@router.post("/payouts")
async def create_payout(body: PayoutIn, _: dict = Depends(require_admin)):
    tech = await db.users.find_one({"id": body.technician_id, "role": "tecnico"}, {"_id": 0})
    if not tech:
        raise HTTPException(404, "Técnico não encontrado")
    cat = await db.categories.find_one({"system_key": "comissao"}, {"_id": 0})
    tx_id = new_id()
    await db.transactions.insert_one({
        "id": tx_id, "type": "saida", "date": today(), "amount": body.amount,
        "description": f"Repasse de comissão - {tech['name']} ({body.period_start} a {body.period_end})",
        "category_id": cat["id"] if cat else None, "payment_method": body.payment_method, "status": "pago", "os_ids": [],
        "technician_id": tech["id"], "part_name": None, "reconciled": False, "source": "repasse",
        "recurring_id": None, "created_at": now_iso()})
    doc = {"id": new_id(), **body.model_dump(), "technician_name": tech["name"], "transaction_id": tx_id, "paid_at": today()}
    await db.payouts.insert_one(doc)
    doc.pop("_id", None)
    return doc
