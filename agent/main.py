"""
Telegram Personal Agent — FastAPI service.
"""
import asyncio
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

import db
import telegram as meta
import classifier as clf
from config import (
    ASYNC_NOTIFY, FAST, FIRE, GATED_WRITE, MULTI_STEP,
    TELEGRAM_OWNER_ID as OWNER_ID, DRAFTS_GROUP_ID,
)
from formatter import (
    confirmation_prompt, draft_notification, outbound_draft_notification,
)
from state import polling_loop
from tools import (
    ASYNC_NOTIFY_EXECUTORS, FAST_EXECUTORS, FIRE_EXECUTORS,
    GATED_WRITE_EXECUTORS, GATED_WRITE_PROMPTS, TOOL_CLASSES,
)

STRUCT_RESEARCH_RE = re.compile(
    r"^(stockresearch|deepresearch|research)(?:\s+(.*))?\s*$",
    re.IGNORECASE | re.DOTALL,
)

STRUCT_CANDIDATE_RE = re.compile(
    r"^candidate\s+(\S+)(.*)?$",
    re.IGNORECASE | re.DOTALL,
)

TELEGRAM_COMMANDS = [
    {"command": "analyze",       "description": "Portfolio deep analysis with macro context and news"},
    {"command": "candidate",     "description": "Evaluate a candidate stock: ADD / WATCH / PASS verdict (~60s)"},
    {"command": "deepresearch",  "description": "In-depth research with agentic gap analysis (~$0.20)"},
    {"command": "earnings",      "description": "Upcoming earnings calendar or stored analysis for a ticker"},
    {"command": "health",        "description": "System health check + 24h API cost"},
    {"command": "macro",         "description": "Macro indicators, news context and portfolio synthesis (~15s)"},
    {"command": "news",          "description": "Latest morning news digest"},
    {"command": "portfolio",     "description": "Live portfolio snapshot"},
    {"command": "prices",        "description": "Trigger portfolio price refresh"},
    {"command": "rationalize",   "description": "Run portfolio rationalization scoring (~10 min)"},
    {"command": "research",      "description": "General research on a topic or stock, standard depth"},
    {"command": "search",        "description": "Search news via Exa neural search"},
    {"command": "stockresearch", "description": "Deep stock research report (cached 90 days)"},
    {"command": "thesis",        "description": "Read or write investment thesis for a position"},
    {"command": "youtube",       "description": "Latest YouTube channel digest"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await meta.set_my_commands(TELEGRAM_COMMANDS)
    task = asyncio.create_task(polling_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook/telegram")
async def handle_telegram_update(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not meta.verify_signature(b"", secret):
        print(f"[telegram] rejected update — bad secret")
        return {"status": "unauthorized"}
    payload = await request.json()
    msg = meta.parse_inbound(payload)
    if not msg or not msg.get("text", "").strip():
        return {"status": "ignored"}
    # Log chat_id on every message so TELEGRAM_OWNER_ID can be discovered if unset
    if not OWNER_ID:
        print(f"[telegram] message from chat_id={msg['phone']} ({msg.get('display_name','')})")
    asyncio.create_task(handle_message(msg))
    return {"status": "ok"}


# ── Core message handler ──────────────────────────────────────────────────────

async def handle_message(msg: dict):
    phone = msg["phone"]
    text = msg["text"].strip()
    t0 = time.monotonic()

    await meta.mark_read(msg["msg_id"], msg.get("phone", ""))

    # ── Expire stale confirmations first
    await db.expire_stale_confirmations(phone)

    # ── Route by sender ────────────────────────────────────────────────────────
    if phone == OWNER_ID:
        await handle_owner(phone, text, t0)
    elif DRAFTS_GROUP_ID and phone == DRAFTS_GROUP_ID:
        await handle_drafts_group(phone, text)
    else:
        await handle_contact(phone, msg.get("display_name", phone), text)


# ── Owner command flow ───────────────────────────────────────────────────────

async def handle_owner(phone: str, text: str, t0: float):
    # Track slash-prefix before stripping so structured commands stay gated
    was_slash = text.startswith("/")
    if was_slash:
        text = text[1:]

    # Check if a confirmation is pending
    pending_conf = await db.get_pending_confirmation(phone)
    if pending_conf:
        await _handle_confirmation_response(phone, text, pending_conf, t0)
        return

    # ── Structured research shortcut (only fires for /stockresearch, /research, /deepresearch)
    if was_slash:
        m = STRUCT_RESEARCH_RE.match(text)
        if m:
            cmd = m.group(1).lower()
            remainder = (m.group(2) or "").strip()
            if cmd == "stockresearch":
                parts = remainder.split(None, 1)
                ticker = parts[0].upper() if parts else ""
                question = parts[1].strip() if len(parts) > 1 else ""
                args = {"research_type": "stock", "depth": "deep",
                        "ticker": ticker, "question": question, "force": True}
            elif cmd == "deepresearch":
                args = {"research_type": "strategy", "depth": "deep", "question": remainder}
            else:  # "research"
                args = {"research_type": "strategy", "depth": "standard", "question": remainder}
            executor = ASYNC_NOTIFY_EXECUTORS.get("research")
            try:
                result = await executor(args, phone)
            except Exception as e:
                await meta.send_message(phone, f"❌ Failed to dispatch research: {e}")
                return
            ack = result["text"]
            job_id = result.get("job_id")
            await meta.send_message(phone, ack)
            await db.append_history(phone, "user", text)
            await db.append_history(phone, "assistant", ack,
                                    tool_called="research", tool_args=args)
            if job_id:
                await db.create_pending_job(job_id, phone, "research", args)
            await db.write_audit(
                phone=phone, inbound_text=text, intent="research", tool="research",
                tool_args=args, latency_ms=int((time.monotonic() - t0) * 1000),
                router_tokens=0, synth_tokens=None, cost_usd=None,
                wm_job_id=job_id, response_text=ack,
                status="dispatched" if job_id else "cached", error=None,
            )
            return

    # ── Structured candidate shortcut (only fires for /candidate TICKER)
    if was_slash:
        mc = STRUCT_CANDIDATE_RE.match(text)
        if mc:
            ticker = mc.group(1).upper()
            thesis_text = (mc.group(2) or "").strip() or None
            args = {"ticker": ticker}
            if thesis_text:
                args["thesis_text"] = thesis_text
            executor = ASYNC_NOTIFY_EXECUTORS.get("candidate_evaluation")
            try:
                result = await executor(args, phone)
            except Exception as e:
                await meta.send_message(phone, f"❌ Failed to dispatch candidate eval: {e}")
                return
            ack = result["text"]
            job_id = result.get("job_id")
            await meta.send_message(phone, ack)
            await db.append_history(phone, "user", text)
            await db.append_history(phone, "assistant", ack,
                                    tool_called="candidate_evaluation", tool_args=args)
            if job_id:
                await db.create_pending_job(job_id, phone, "candidate_evaluation", args)
            await db.write_audit(
                phone=phone, inbound_text=text, intent="candidate_evaluation",
                tool="candidate_evaluation", tool_args=args,
                latency_ms=int((time.monotonic() - t0) * 1000),
                router_tokens=0, synth_tokens=None, cost_usd=None,
                wm_job_id=job_id, response_text=ack,
                status="dispatched" if job_id else "cached", error=None,
            )
            return

    # Classify intent
    history = await db.load_history(phone)
    try:
        cls = await clf.classify(text, history)
    except Exception as e:
        await meta.send_message(phone, f"❌ Classification error: {e}")
        return

    intent = cls.get("intent", "unknown")
    args = cls.get("args", {})
    router_tokens = cls.get("router_tokens", 0)

    await db.append_history(phone, "user", text)

    # ── Unknown ────────────────────────────────────────────────────────────────
    if intent == "unknown":
        reply = "Sorry, I didn't understand that. Try: portfolio, research TSLA, health, refresh prices."
        await meta.send_message(phone, reply)
        await db.append_history(phone, "assistant", reply)
        await db.write_audit(
            phone=phone, inbound_text=text, intent=intent, tool=None,
            tool_args=None, latency_ms=None, router_tokens=router_tokens,
            synth_tokens=None, cost_usd=None, wm_job_id=None,
            response_text=reply, status="unknown", error=None,
        )
        return

    tool_class = TOOL_CLASSES.get(intent, FAST)

    # ── GATED_WRITE ────────────────────────────────────────────────────────────
    if tool_class == GATED_WRITE:
        prompt = GATED_WRITE_PROMPTS.get(intent, "Confirm this write operation.")
        await db.create_confirmation(phone, intent, args)
        reply = confirmation_prompt(intent, prompt)
        await meta.send_message(phone, reply)
        await db.append_history(phone, "assistant", reply, tool_called=intent, tool_args=args)
        await db.write_audit(
            phone=phone, inbound_text=text, intent=intent, tool=intent,
            tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
            router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
            wm_job_id=None, response_text=reply, status="pending_confirmation", error=None,
        )
        return

    # ── ASYNC_NOTIFY ───────────────────────────────────────────────────────────
    if tool_class == ASYNC_NOTIFY:
        executor = ASYNC_NOTIFY_EXECUTORS.get(intent)
        if not executor:
            await meta.send_message(phone, f"❌ No executor for async tool '{intent}'")
            return
        try:
            result = await executor(args, phone)
        except Exception as e:
            await meta.send_message(phone, f"❌ Failed to dispatch {intent}: {e}")
            return
        ack = result["text"]
        job_id = result.get("job_id")
        await meta.send_message(phone, ack)
        await db.append_history(phone, "assistant", ack, tool_called=intent, tool_args=args)
        if job_id:
            await db.create_pending_job(job_id, phone, intent, args)
        await db.write_audit(
            phone=phone, inbound_text=text, intent=intent, tool=intent,
            tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
            router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
            wm_job_id=job_id, response_text=ack, status="dispatched" if job_id else "rejected", error=None,
        )
        return

    # ── FIRE ───────────────────────────────────────────────────────────────────
    if tool_class == FIRE:
        executor = FIRE_EXECUTORS.get(intent)
        if not executor:
            await meta.send_message(phone, f"❌ No executor registered for '{intent}'.")
            await db.write_audit(
                phone=phone, inbound_text=text, intent=intent, tool=intent,
                tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
                router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
                wm_job_id=None, response_text=None, status="unregistered", error=None,
            )
            return
        try:
            result = await executor(args)
        except Exception as e:
            await meta.send_message(phone, f"❌ {intent} failed: {e}")
            await db.write_audit(
                phone=phone, inbound_text=text, intent=intent, tool=intent,
                tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
                router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
                wm_job_id=None, response_text=None, status="failed", error=str(e),
            )
            return
        reply = result["text"]
        await meta.send_message(phone, reply)
        await db.append_history(phone, "assistant", reply, tool_called=intent, tool_args=args)
        await db.write_audit(
            phone=phone, inbound_text=text, intent=intent, tool=intent,
            tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
            router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
            wm_job_id=None, response_text=reply, status="success", error=None,
        )
        return

    # ── MULTI_STEP ─────────────────────────────────────────────────────────────
    if tool_class == MULTI_STEP:
        import planner as pl
        steps = await pl.plan(intent, args, text)
        if not steps:
            fallback = FAST_EXECUTORS.get(intent)
            reply = (await fallback(args))["text"] if fallback else "Couldn't plan a response for that."
        else:
            results = {}
            for step in steps:
                executor = FAST_EXECUTORS.get(step["tool"])
                if executor:
                    try:
                        results[step["tool"]] = (await executor(step.get("args", {})))["text"]
                    except Exception as e:
                        results[step["tool"]] = f"[{step['tool']} error: {e}]"
            reply = await pl.synthesise(text, results)
        await meta.send_message(phone, reply)
        await db.append_history(phone, "assistant", reply, tool_called=intent, tool_args=args)
        await db.write_audit(
            phone=phone, inbound_text=text, intent=intent, tool=intent,
            tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
            router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
            wm_job_id=None, response_text=reply[:500], status="success", error=None,
        )
        return

    # ── FAST ───────────────────────────────────────────────────────────────────
    if tool_class == FAST:
        # Handle special management intents first
        if intent == "add_contact":
            reply = await _handle_add_contact(args)
        elif intent == "set_autoreplyrule":
            reply = await _handle_set_autoreplyrule(args)
        elif intent == "outbound_message":
            reply = await _handle_outbound_message(args, phone)
        elif intent in FAST_EXECUTORS:
            try:
                result = await FAST_EXECUTORS[intent](args)
                reply = result["text"]
            except Exception as e:
                reply = f"❌ {intent} failed: {e}"
        else:
            reply = f"Tool '{intent}' not yet implemented."

        await meta.send_message(phone, reply)
        await db.append_history(phone, "assistant", reply, tool_called=intent, tool_args=args)
        await db.write_audit(
            phone=phone, inbound_text=text, intent=intent, tool=intent,
            tool_args=args, latency_ms=int((time.monotonic()-t0)*1000),
            router_tokens=router_tokens, synth_tokens=None, cost_usd=None,
            wm_job_id=None, response_text=reply[:500], status="success", error=None,
        )


async def _handle_confirmation_response(phone: str, text: str, conf: dict, t0: float):
    lower = text.lower().strip()
    if lower in ("confirm", "yes", "y"):
        await db.resolve_confirmation(conf["id"], "confirmed")
        tool_name = conf["tool_name"]
        tool_args = conf["tool_args"] or {}
        executor = GATED_WRITE_EXECUTORS.get(tool_name)
        if executor:
            try:
                result = await executor(tool_args)
                reply = result["text"]
            except Exception as e:
                reply = f"❌ {tool_name} failed: {e}"
        else:
            reply = f"No executor found for {tool_name}."
        await meta.send_message(phone, reply)
        await db.write_audit(
            phone=phone, inbound_text=text, intent="confirm",
            tool=tool_name, tool_args=tool_args,
            latency_ms=int((time.monotonic()-t0)*1000),
            router_tokens=None, synth_tokens=None, cost_usd=None,
            wm_job_id=None, response_text=reply, status="confirmed", error=None,
        )
    elif lower in ("cancel", "no", "n"):
        await db.resolve_confirmation(conf["id"], "cancelled")
        reply = "Cancelled."
        await meta.send_message(phone, reply)
    else:
        reply = "Pending confirmation — reply *confirm* or *cancel*."
        await meta.send_message(phone, reply)


async def _handle_add_contact(args: dict) -> str:
    phone = args.get("phone", "")
    name = args.get("name", "")
    if not phone or not name:
        return "Please provide phone (+E164) and name."
    await db.upsert_contact(
        phone, name,
        args.get("relationship"), False,
        args.get("rule_prompt"), args.get("notes"),
    )
    return f"✅ Contact saved: {name} ({phone})"


async def _handle_set_autoreplyrule(args: dict) -> str:
    phone = args.get("phone", "")
    rule = args.get("rule_prompt", "")
    if not phone or not rule:
        return "Please provide phone and rule prompt."
    contact = await db.get_contact(phone)
    if not contact:
        return f"Contact {phone} not found. Add them first with 'add contact ...'."
    await db.upsert_contact(
        phone, contact["display_name"], contact.get("relationship"),
        True, rule, contact.get("notes"),
    )
    return f"✅ Auto-reply rule set for {contact['display_name']}."


async def _handle_outbound_message(args: dict, owner_phone: str) -> str:
    target = args.get("contact_name_or_phone", "")
    text = args.get("message", "")
    if not target or not text:
        return "Please specify a contact and message text."
    # Resolve contact from DB if name provided
    contact = None
    if not target.startswith("+"):
        rows = await db.search_contacts_by_name(target)
        if rows:
            contact = rows[0]
            to_phone = contact["wa_phone"]
        else:
            return f"Contact '{target}' not found. Add them first."
    else:
        to_phone = target

    # Create draft and notify via Drafts group (or owner's own chat if no group yet)
    draft_id = await db.create_draft(to_phone, f"[outbound] {text}", text)
    display = contact["display_name"] if contact else to_phone
    notif = outbound_draft_notification(draft_id, display, to_phone, text)
    notify_target = DRAFTS_GROUP_ID if DRAFTS_GROUP_ID else owner_phone
    await meta.send_message(notify_target, notif)
    return f"Draft created for {display} — approve in Drafts group."


# ── Drafts group commands ─────────────────────────────────────────────────────

async def handle_drafts_group(group_id: str, text: str):
    text = text.strip()
    # /send_<id>
    m = re.match(r"^/send_(\d+)$", text, re.IGNORECASE)
    if m:
        draft_id = int(m.group(1))
        await _execute_draft_send(draft_id)
        return
    # /ignore_<id>
    m = re.match(r"^/ignore_(\d+)$", text, re.IGNORECASE)
    if m:
        draft_id = int(m.group(1))
        await db.resolve_draft(draft_id, "ignored")
        await meta.send_message(group_id, f"Draft {draft_id} ignored.")
        return
    # /edit_<id> <new text>
    m = re.match(r"^/edit_(\d+)\s+(.+)$", text, re.IGNORECASE | re.DOTALL)
    if m:
        draft_id = int(m.group(1))
        new_text = m.group(2).strip()
        await _execute_draft_send(draft_id, override_text=new_text)
        return


async def _execute_draft_send(draft_id: int, override_text: str = None):
    draft = await db.get_pending_draft(draft_id)
    notify_target = DRAFTS_GROUP_ID if DRAFTS_GROUP_ID else OWNER_ID
    if not draft:
        await meta.send_message(notify_target, f"Draft {draft_id} not found or already resolved.")
        return
    send_text = override_text if override_text else draft["draft_reply"]
    to_phone = draft["wa_phone"]
    ok = await meta.send_message(to_phone, send_text)
    if ok:
        await db.resolve_draft(draft_id, "sent")
        await meta.send_message(notify_target, f"✅ Sent to {to_phone}: \"{send_text[:60]}\"")
    else:
        await meta.send_message(notify_target, f"❌ Failed to send draft {draft_id}.")


# ── Inbound from third-party contact ─────────────────────────────────────────

async def handle_contact(phone: str, display_name: str, text: str):
    contact = await db.get_contact(phone)

    # Auto-reply if rule configured
    if contact and contact.get("auto_reply") and contact.get("rule_prompt"):
        try:
            reply = await clf.draft_reply(text, contact)
            await meta.send_message(phone, reply)
        except Exception as e:
            print(f"[auto-reply] error for {phone}: {e}")
        return

    # Draft-and-approve: generate draft, notify owner via Drafts group
    name = contact["display_name"] if contact else display_name
    try:
        draft = await clf.draft_reply(text, contact)
    except Exception as e:
        draft = "[Draft generation failed]"

    draft_id = await db.create_draft(phone, text, draft)
    notif = draft_notification(draft_id, name, text, draft)
    notify_target = DRAFTS_GROUP_ID if DRAFTS_GROUP_ID else OWNER_ID
    await meta.send_message(notify_target, notif)


# ── Health endpoint ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
