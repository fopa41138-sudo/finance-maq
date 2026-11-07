import os
import time
import logging
from datetime import timedelta
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import db, new_id, now_iso, today, parse_date, require_admin, with_status

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)
PLUGGY_BASE = "https://api.pluggy.ai"
_pluggy_cache = {"key": None, "exp": 0}


# ---------- Pluggy ----------
async def pluggy_key() -> str:
    if _pluggy_cache["key"] and _pluggy_cache["exp"] > time.time():
        return _pluggy_cache["key"]
    cid, secret = os.environ.get("PLUGGY_ID"), os.environ.get("PLUGGY_SECRET")
    if not cid or not secret:
        raise HTTPException(503, "Pluggy não configurado (PLUGGY_ID / PLUGGY_SECRET)")
    async with httpx.AsyncClient(base_url=PLUGGY_BASE, timeout=20) as c:
        r = await c.post("/auth", json={"clientId": cid, "clientSecret": secret})
    if r.is_error:
        raise HTTPException(502, f"Pluggy recusou as credenciais ({r.status_code})")
    _pluggy_cache.update(key=r.json()["apiKey"], exp=time.time() + 100 * 60)
    return _pluggy_cache["key"]


async def pluggy(method: str, path: str, **kw) -> dict:
    key = await pluggy_key()
    async with httpx.AsyncClient(base_url=PLUGGY_BASE, timeout=30) as c:
        r = await c.request(method, path, headers={"X-API-KEY": key}, **kw)
    if r.is_error:
        log.error("Pluggy %s %s -> %s", method, path, r.status_code)
        raise HTTPException(502, f"Erro no Pluggy ({r.status_code})")
    return r.json()


class ItemIn(BaseModel):
    item_id: str


class LinkBankIn(BaseModel):
    transaction_id: str


class CreateFromBankIn(BaseModel):
    category_id: str
    description: Optional[str] = None
    os_ids: List[str] = []
    payment_method: str = "pix"


async def import_item(item_id: str) -> dict:
    accounts = (await pluggy("GET", "/accounts", params={"itemId": item_id})).get("results", [])
    count = 0
    for acc in accounts:
        await db.bank_accounts.update_one({"id": acc["id"]}, {"$set": {
            "id": acc["id"], "item_id": item_id, "name": acc.get("name"), "number": acc.get("number"),
            "type": acc.get("type"), "balance": acc.get("balance"), "currency": acc.get("currencyCode")}}, upsert=True)
        params = {"accountId": acc["id"], "pageSize": 500}
        while True:
            page = await pluggy("GET", "/v2/transactions", params=params)
            for tx in page.get("results", []):
                amount = float(tx.get("amount") or 0)
                kind = "entrada" if (tx.get("type") == "CREDIT" or (tx.get("type") is None and amount > 0)) else "saida"
                await db.bank_transactions.update_one({"id": tx["id"]}, {
                    "$set": {"id": tx["id"], "item_id": item_id, "account_id": acc["id"], "account_name": acc.get("name"),
                             "date": (tx.get("date") or "")[:10], "amount": round(abs(amount), 2), "type": kind,
                             "description": tx.get("description") or ""},
                    "$setOnInsert": {"handled": None, "linked_tx_id": None, "imported_at": now_iso()}}, upsert=True)
                count += 1
            nxt = page.get("next")
            if not nxt or "after=" not in nxt:
                break
            params = {"accountId": acc["id"], "pageSize": 500, "after": nxt.split("after=", 1)[1].split("&")[0]}
    await db.bank_items.update_one({"id": item_id}, {"$set": {"last_sync": now_iso()}})
    return {"accounts": len(accounts), "transactions": count}


@router.get("/banks/status")
async def banks_status(_: dict = Depends(require_admin)):
    return {"configured": bool(os.environ.get("PLUGGY_ID") and os.environ.get("PLUGGY_SECRET"))}


@router.post("/banks/connect-token")
async def connect_token(user: dict = Depends(require_admin)):
    data = await pluggy("POST", "/connect_token", json={"options": {"clientUserId": user["id"], "avoidDuplicates": True}})
    return {"accessToken": data["accessToken"]}


@router.post("/banks/items")
async def save_item(body: ItemIn, _: dict = Depends(require_admin)):
    item = await pluggy("GET", f"/items/{body.item_id}")
    await db.bank_items.update_one({"id": body.item_id}, {"$set": {
        "id": body.item_id, "connector": (item.get("connector") or {}).get("name", "Banco"),
        "status": item.get("status"), "connected_at": now_iso()}}, upsert=True)
    return await import_item(body.item_id)


@router.post("/banks/items/{item_id}/sync")
async def sync_item(item_id: str, _: dict = Depends(require_admin)):
    if not await db.bank_items.find_one({"id": item_id}):
        raise HTTPException(404, "Conexão não encontrada")
    return await import_item(item_id)


@router.delete("/banks/items/{item_id}")
async def remove_item(item_id: str, _: dict = Depends(require_admin)):
    await db.bank_items.delete_one({"id": item_id})
    await db.bank_accounts.delete_many({"item_id": item_id})
    await db.bank_transactions.delete_many({"item_id": item_id, "handled": None})
    return {"ok": True}


@router.get("/banks/items")
async def list_items(_: dict = Depends(require_admin)):
    items = await db.bank_items.find({}, {"_id": 0}).to_list(50)
    for it in items:
        it["accounts"] = await db.bank_accounts.find({"item_id": it["id"]}, {"_id": 0}).to_list(50)
    return items


def near(d1: str, d2: Optional[str], days: int = 5) -> bool:
    return bool(d2) and abs((parse_date(d1) - parse_date(d2)).days) <= days


async def suggestions(bt: dict) -> list:
    lo, hi = bt["amount"] - 0.01, bt["amount"] + 0.01
    d = parse_date(bt["date"])
    rng = {"$gte": (d - timedelta(days=5)).isoformat(), "$lte": (d + timedelta(days=5)).isoformat()}
    out = []
    async for t in db.transactions.find({"type": bt["type"], "amount": {"$gte": lo, "$lte": hi}, "date": rng,
                                         "bank_tx_id": {"$in": [None]}}, {"_id": 0}).limit(3):
        out.append({"kind": "lancamento", "transaction_id": t["id"], "label": t["description"], "date": t["date"],
                    "amount": t["amount"], "os_ids": t.get("os_ids", [])})
    if bt["type"] == "entrada":
        async for o in db.service_orders.find({"status": "concluida", "completed_at": rng}, {"_id": 0}):
            total = o["service_value"] + o["fee_value"] + sum(p["qty"] * p["unit_price"] for p in o["parts"])
            if abs(total - bt["amount"]) <= 0.01:
                out.append({"kind": "os", "os_id": o["id"], "label": f"OS #{o['number']} - {o['client']}",
                            "date": o["completed_at"], "amount": round(total, 2)})
    return out


@router.get("/banks/transactions")
async def bank_transactions(pending_only: bool = False, _: dict = Depends(require_admin)):
    q = {"handled": None} if pending_only else {}
    txs = await db.bank_transactions.find(q, {"_id": 0}).sort("date", -1).to_list(1000)
    for t in txs:
        t["suggestions"] = await suggestions(t) if not t.get("handled") else []
    return txs


async def get_bank_tx(bid: str) -> dict:
    bt = await db.bank_transactions.find_one({"id": bid}, {"_id": 0})
    if not bt:
        raise HTTPException(404, "Movimento não encontrado")
    if bt.get("handled"):
        raise HTTPException(409, "Movimento já tratado")
    return bt


@router.post("/banks/transactions/{bid}/link")
async def link_bank(bid: str, body: LinkBankIn, _: dict = Depends(require_admin)):
    await get_bank_tx(bid)
    res = await db.transactions.update_one({"id": body.transaction_id},
                                           {"$set": {"bank_tx_id": bid, "reconciled": True, "status": "pago"}})
    if res.matched_count == 0:
        raise HTTPException(404, "Lançamento não encontrado")
    await db.bank_transactions.update_one({"id": bid}, {"$set": {"handled": "vinculado", "linked_tx_id": body.transaction_id}})
    return {"ok": True}


@router.post("/banks/transactions/{bid}/create")
async def create_from_bank(bid: str, body: CreateFromBankIn, _: dict = Depends(require_admin)):
    bt = await get_bank_tx(bid)
    cat = await db.categories.find_one({"id": body.category_id}, {"_id": 0})
    if not cat or cat["type"] != bt["type"]:
        raise HTTPException(400, "Categoria inválida para este movimento")
    tech = None
    if body.os_ids:
        o = await db.service_orders.find_one({"id": body.os_ids[0]}, {"_id": 0})
        if not o:
            raise HTTPException(400, "OS inválida")
        tech = o["technician_id"]
    tx_id = new_id()
    await db.transactions.insert_one({
        "id": tx_id, "type": bt["type"], "date": bt["date"], "amount": bt["amount"],
        "description": body.description or bt["description"], "category_id": body.category_id,
        "payment_method": body.payment_method, "status": "pago", "os_ids": body.os_ids, "technician_id": tech,
        "part_name": None, "reconciled": True, "source": "banco", "recurring_id": None, "bank_tx_id": bid,
        "created_at": now_iso()})
    await db.bank_transactions.update_one({"id": bid}, {"$set": {"handled": "criado", "linked_tx_id": tx_id}})
    return {"ok": True, "transaction_id": tx_id}


@router.post("/banks/transactions/{bid}/ignore")
async def ignore_bank(bid: str, _: dict = Depends(require_admin)):
    await get_bank_tx(bid)
    await db.bank_transactions.update_one({"id": bid}, {"$set": {"handled": "ignorado"}})
    return {"ok": True}


# ---------- Assistentes de IA ----------
FUNCTIONS = {"resumo_semanal": "Resumo semanal"}


class AssistantIn(BaseModel):
    name: str
    function: str = "resumo_semanal"
    instructions: Optional[str] = ""
    active: bool = True


async def week_context() -> str:
    end = parse_date(today())
    start = end - timedelta(days=6)
    pstart, pend = start - timedelta(days=7), start - timedelta(days=1)
    cats = {c["id"]: c["name"] async for c in db.categories.find({}, {"_id": 0})}
    users = {u["id"]: u["name"] async for u in db.users.find({}, {"_id": 0})}

    async def load(a, b):
        return [with_status(t) for t in await db.transactions.find(
            {"date": {"$gte": a.isoformat(), "$lte": b.isoformat()}}, {"_id": 0}).to_list(10000)]
    cur, prev = await load(start, end), await load(pstart, pend)

    def tot(txs, typ, paid=None):
        return round(sum(t["amount"] for t in txs if t["type"] == typ and (paid is None or (t["status"] == "pago") == paid)), 2)
    lines = [f"Período: {start} a {end}. Semana anterior: {pstart} a {pend}.",
             f"Entradas recebidas: R$ {tot(cur, 'entrada', True)} (anterior R$ {tot(prev, 'entrada', True)})",
             f"Entradas a receber: R$ {tot(cur, 'entrada', False)}",
             f"Saídas pagas: R$ {tot(cur, 'saida', True)} (anterior R$ {tot(prev, 'saida', True)})",
             f"Saídas previstas/em atraso: R$ {tot(cur, 'saida', False)}", "Por categoria:"]
    bycat = {}
    for t in cur:
        k = (t["type"], cats.get(t["category_id"], "Sem categoria"))
        bycat[k] = bycat.get(k, 0) + t["amount"]
    lines += [f"- {k[0]} / {k[1]}: R$ {round(v, 2)}" for k, v in sorted(bycat.items(), key=lambda x: -x[1])]
    tech = {}
    for t in cur:
        if t["type"] == "entrada" and t.get("technician_id"):
            tech[t["technician_id"]] = tech.get(t["technician_id"], 0) + t["amount"]
    lines.append("Técnicos (valor gerado): " + ", ".join(f"{users.get(k, '?')} R$ {round(v, 2)}" for k, v in tech.items()))
    late = [t for t in await db.transactions.find({"status": {"$ne": "pago"}, "date": {"$lt": today()}}, {"_id": 0}).to_list(200)]
    lines.append(f"Lançamentos em atraso (total geral): {len(late)}, somando R$ {round(sum(t['amount'] for t in late), 2)}")
    lines += [f"- {t['type']} {t['date']} {t['description']} R$ {t['amount']}" for t in late[:10]]
    return "\n".join(lines)


SYSTEM = ("Você é um assistente financeiro de uma empresa de assistência técnica. Escreva em português do Brasil, "
          "em markdown simples, com: um parágrafo de resumo, 3 a 5 destaques em tópicos, alertas que exigem ação "
          "e uma recomendação para a próxima semana. Use apenas os números fornecidos, nunca invente dados.")


async def generate_text(prompt: str, instructions: str) -> tuple:
    system = SYSTEM + (f"\nInstruções do administrador: {instructions}" if instructions else "")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=new_id(), system_message=system) \
            .with_model("openai", "gpt-6-luna")
        text = await chat.send_message(UserMessage(text=prompt))
        if text and str(text).strip():
            return str(text), "gpt-6-luna"
    except Exception as exc:
        log.warning("GPT-6 Luna falhou, usando Ollama: %s", exc)
    key, base = os.environ.get("OLLAMA_API_KEY"), os.environ.get("OLLAMA_BASE_URL")
    if not key or not base:
        raise HTTPException(502, "GPT-6 Luna indisponível e Ollama não configurado")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{base.rstrip('/')}/api/chat", headers={"Authorization": f"Bearer {key}"}, json={
            "model": os.environ.get("OLLAMA_MODEL", "gpt-oss:120b"), "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    if r.is_error:
        raise HTTPException(502, f"Ollama falhou ({r.status_code})")
    return r.json()["message"]["content"], "ollama/" + os.environ.get("OLLAMA_MODEL", "gpt-oss:120b")


@router.get("/assistants")
async def list_assistants(_: dict = Depends(require_admin)):
    items = await db.assistants.find({}, {"_id": 0}).sort("created_at", 1).to_list(100)
    for a in items:
        a["last_run"] = await db.assistant_runs.find_one({"assistant_id": a["id"]}, {"_id": 0}, sort=[("created_at", -1)])
    return {"assistants": items, "functions": FUNCTIONS}


@router.post("/assistants")
async def create_assistant(body: AssistantIn, _: dict = Depends(require_admin)):
    if body.function not in FUNCTIONS:
        raise HTTPException(400, "Função não disponível")
    doc = {"id": new_id(), **body.model_dump(), "created_at": now_iso()}
    await db.assistants.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/assistants/{aid}")
async def update_assistant(aid: str, body: AssistantIn, _: dict = Depends(require_admin)):
    if body.function not in FUNCTIONS:
        raise HTTPException(400, "Função não disponível")
    if (await db.assistants.update_one({"id": aid}, {"$set": body.model_dump()})).matched_count == 0:
        raise HTTPException(404, "Assistente não encontrado")
    return {"ok": True}


@router.delete("/assistants/{aid}")
async def delete_assistant(aid: str, _: dict = Depends(require_admin)):
    if (await db.assistants.delete_one({"id": aid})).deleted_count == 0:
        raise HTTPException(404, "Assistente não encontrado")
    await db.assistant_runs.delete_many({"assistant_id": aid})
    return {"ok": True}


@router.post("/assistants/{aid}/run")
async def run_assistant(aid: str, _: dict = Depends(require_admin)):
    a = await db.assistants.find_one({"id": aid}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Assistente não encontrado")
    context = await week_context()
    text, model = await generate_text(f"Dados da semana:\n{context}\n\nEscreva o resumo semanal.", a.get("instructions", ""))
    run = {"id": new_id(), "assistant_id": aid, "content": text, "model": model, "created_at": now_iso()}
    await db.assistant_runs.insert_one(run)
    run.pop("_id", None)
    return run


@router.get("/assistants/{aid}/runs")
async def list_runs(aid: str, _: dict = Depends(require_admin)):
    return await db.assistant_runs.find({"assistant_id": aid}, {"_id": 0}).sort("created_at", -1).to_list(50)
