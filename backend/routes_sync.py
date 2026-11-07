import asyncio
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core import db, now_iso, require_admin
from routes_automation import import_item, pluggy

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)
_tasks = set()


def spawn(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def sync_all(trigger: str):
    results = []
    async for it in db.bank_items.find({}, {"_id": 0, "id": 1}):
        try:
            r = await import_item(it["id"])
            results.append({"item_id": it["id"], **r})
        except Exception as exc:
            log.error("sync item %s falhou: %s", it["id"], exc)
            results.append({"item_id": it["id"], "error": str(getattr(exc, "detail", exc))})
    await db.sync_runs.insert_one({"trigger": trigger, "finished_at": now_iso(), "results": results})


# ---------- Cron diário ----------
@router.post("/cron/bank-sync")
async def cron_bank_sync(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    secret = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("authorization", "")
    if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
        raise HTTPException(401, "Unauthorized")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid body")
    run_id = request.headers.get("x-webhook-id") or body.get("run_id")
    if run_id:
        res = await db.cron_runs.update_one({"run_id": run_id}, {"$setOnInsert": {"run_id": run_id, "at": now_iso()}}, upsert=True)
        if res.upserted_id is None:
            return {"ok": True, "duplicate": True}
    spawn(sync_all("cron"))
    return {"ok": True}


# ---------- Webhook do Pluggy ----------
async def handle_event(evt: dict):
    event, item_id = evt.get("event", ""), evt.get("itemId")
    if not item_id or not await db.bank_items.find_one({"id": item_id}):
        return
    if event == "item/deleted":
        await db.bank_items.delete_one({"id": item_id})
        await db.bank_accounts.delete_many({"item_id": item_id})
        await db.bank_transactions.delete_many({"item_id": item_id, "handled": None})
    elif event == "transactions/deleted":
        ids = evt.get("transactionIds") or []
        await db.bank_transactions.delete_many({"id": {"$in": ids}, "handled": None})
    elif event in ("item/updated", "transactions/created", "transactions/updated"):
        await import_item(item_id)
    if event.startswith("item/") and event != "item/deleted":
        try:
            item = await pluggy("GET", f"/items/{item_id}")
            await db.bank_items.update_one({"id": item_id}, {"$set": {"status": item.get("status")}})
        except Exception as exc:
            log.warning("item status %s: %s", item_id, exc)


@router.post("/webhooks/pluggy")
async def pluggy_webhook(request: Request, token: str = ""):
    secret = os.environ.get("PLUGGY_WEBHOOK_SECRET", "")
    if not secret or not hmac.compare_digest(token, secret):
        raise HTTPException(401, "Unauthorized")
    try:
        evt = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid body")
    if not isinstance(evt, dict):
        raise HTTPException(400, "Invalid body")
    if evt.get("clientId") and evt["clientId"] != os.environ.get("PLUGGY_ID"):
        return JSONResponse({"ok": True, "ignored": True})
    event_id = evt.get("eventId")
    if event_id:
        res = await db.webhook_events.update_one({"event_id": event_id}, {"$setOnInsert": {
            "event_id": event_id, "event": evt.get("event"), "item_id": evt.get("itemId"), "received_at": now_iso()}}, upsert=True)
        if res.upserted_id is None:
            return {"ok": True, "duplicate": True}
    spawn(handle_event(evt))
    return {"ok": True}


def webhook_url(request: Request) -> str:
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host", "")).split(",")[0].strip()
    return f"https://{host}/api/webhooks/pluggy?token={os.environ['PLUGGY_WEBHOOK_SECRET']}"


@router.get("/banks/webhook")
async def webhook_info(request: Request, _: dict = Depends(require_admin)):
    url = webhook_url(request)
    registered = False
    try:
        hooks = (await pluggy("GET", "/webhooks")).get("results", [])
        registered = any(h.get("url") == url for h in hooks)
    except HTTPException:
        pass
    last_events = await db.webhook_events.find({}, {"_id": 0}).sort("received_at", -1).limit(5).to_list(5)
    last_sync = await db.sync_runs.find_one({}, {"_id": 0}, sort=[("finished_at", -1)])
    return {"url": url, "registered": registered, "last_events": last_events, "last_sync": last_sync}


@router.post("/banks/webhook/register")
async def register_webhook(request: Request, _: dict = Depends(require_admin)):
    url = webhook_url(request)
    hooks = (await pluggy("GET", "/webhooks")).get("results", [])
    if any(h.get("url") == url for h in hooks):
        return {"ok": True, "already": True}
    await pluggy("POST", "/webhooks", json={"event": "all", "url": url})
    return {"ok": True}


@router.post("/banks/sync-all")
async def sync_all_now(_: dict = Depends(require_admin)):
    spawn(sync_all("manual"))
    return {"ok": True}
