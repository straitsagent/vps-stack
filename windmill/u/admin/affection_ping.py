# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Affection Ping — hourly sticker + caption sent to a Telegram group.

Every hour from 8AM–10PM SGT, picks a random sticker from the configured
pack(s), generates a one-sentence affectionate caption via Deepseek, sends
the sticker with caption to the configured group, and logs to affection_outbox.

Hard Rule 16 (>=500-word report) is exempt — see /root/shared/override_log.md.
"""

import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

SGT = timezone(timedelta(hours=8))

_CAPTION_PROMPT = (
    "You are writing a short, warm, affectionate message to accompany a cute "
    "sticker sent to someone special. Write exactly ONE sentence (under 25 words) "
    "that is playful, sincere, and varied — never generic. No emoji in the sentence "
    "itself (the sticker carries the visual). Address the recipient as lissybaby "
    "in the sentence — not as a greeting prefix, but woven in naturally. Rotate "
    "naturally between themes: missing you, encouragement, random fondness, "
    "good-morning/good-night when apt. Output the sentence only — no preamble, no quotes."
)

_FALLBACK_CAPTIONS = [
    "Thinking of you right now, lissybaby.",
    "Hope your hour goes well, lissybaby.",
    "Just a little hello from across the screen, lissybaby.",
    "You crossed my mind, lissybaby, so here's a sticker.",
    "Sending something soft your way, lissybaby.",
    "Hope this made you smile a little, lissybaby.",
    "A small ping, just because, lissybaby.",
    "Wishing you a good moment right now, lissybaby.",
]

_CAPTION_MAX_CHARS = 1024  # Telegram sendSticker caption limit

# Only pick stickers whose emoji marker is affectionate/positive.
# This whitelist approach keeps variety high while ensuring every
# sticker expresses warmth, cuteness, or affection.
_AFFECTIONATE_EMOJIS = {
    "🥰", "😍", "🥺", "😇", "😊", "☺️", "🤗", "😘", "😚", "❤️", "❤",
    "😋", "😌", "😄", "😁", "😃", "😆", "😎", "🙂", "😉", "😛",
    "😅", "😂", "🤣", "🥳", "💐", "🐼", "🐻", "🤤", "👀", "🤭",
    "💓", "💖", "💕", "💗", "💘", "💞", "💝", "💌", "💋", "🌹",
    "🌸", "👋", "😴", "💤",
}


def _fetch_stickers(bot_token: str, pack_names: list) -> list:
    """Return flat list of affectionate sticker dicts (whitelist-filtered) from all packs."""
    out = []
    for name in pack_names:
        name = name.strip()
        if not name:
            continue
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{bot_token}/getStickerSet",
                params={"name": name},
                timeout=15,
            )
            body = r.json()
            if body.get("ok"):
                all_stickers = body.get("result", {}).get("stickers", [])
                # Filter to affectionate emojis only
                cute = [s for s in all_stickers
                        if s.get("emoji", "") in _AFFECTIONATE_EMOJIS]
                log.info(f"[Stickers] {name}: {len(all_stickers)} total, "
                         f"{len(cute)} affectionate (emoji-filtered)")
                out.extend(cute)
            else:
                log.warning(f"[Stickers] {name}: {body.get('description', 'not ok')}")
        except Exception as e:
            log.warning(f"[Stickers] {name} fetch failed: {e}")
    return out


def _generate_caption(deepseek_key: str) -> str:
    """One affectionate sentence via Deepseek. Falls back to rotation on failure."""
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": _CAPTION_PROMPT}],
                "temperature": 0.9,
                "max_tokens": 80,
            },
            timeout=20,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip().strip('"').strip()
        if text:
            # Light validation: collapse to a single sentence
            text = re.split(r"(?<=[.!?])\s+", text)[0]
            if len(text) > _CAPTION_MAX_CHARS:
                text = text[: _CAPTION_MAX_CHARS - 3] + "..."
            return text
    except Exception as e:
        log.warning(f"[Caption] Deepseek failed: {e}")
    return random.choice(_FALLBACK_CAPTIONS)


def _send_sticker(bot_token: str, chat_id: str, file_id: str, caption: str) -> tuple:
    """Send caption as sendMessage, then sticker as sendSticker (separate messages).
    sendSticker's caption parameter is silently dropped by Telegram — verified live.
    Returns (delivered: bool, error: str|None). Both must succeed for delivered=True.

    Per Hard Rule 21: verifies the API *response* contains the expected fields,
    not just ok:true. sendMessage response must contain result.text matching the
    caption. sendSticker response must contain result.sticker with an affectionate
    emoji — if the emoji is negative (angry/sad/devil), reports failure rather
    than declaring success.
    """
    # 1. Send caption as a text message — verify result.text is present (Rule 21)
    msg_ok, msg_err = _send_message(bot_token, chat_id, caption)
    if not msg_ok:
        return False, f"caption sendMessage failed: {msg_err}"

    # 2. Send the sticker (no caption — it doesn't work)
    #    Verify result.sticker is present and emoji is affectionate (Rule 21)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendSticker",
            json={"chat_id": chat_id, "sticker": file_id},
            timeout=15,
        )
        body = r.json()
        if not body.get("ok"):
            return False, f"sendSticker failed: {body.get('description', f'HTTP {r.status_code}')}"
        result = body.get("result", {})
        sticker = result.get("sticker")
        if not sticker:
            return False, "sendSticker response missing result.sticker field"
        emoji = sticker.get("emoji", "")
        if emoji and emoji not in _AFFECTIONATE_EMOJIS:
            return False, f"delivered sticker emoji is {emoji} — not in affectionate set (Rule 21)"
        return True, None
    except Exception as e:
        return False, str(e)


def _send_message(bot_token: str, chat_id: str, text: str) -> tuple:
    """Send a plain text message via sendMessage. Returns (delivered: bool, error: str|None).

    Per Hard Rule 21: verifies the API *response* contains result.text matching
    the sent text — not just ok:true. Telegram could theoretically accept the
    message but deliver empty content; checking result.text catches that.
    """
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        body = r.json()
        if not body.get("ok"):
            return False, body.get("description", f"HTTP {r.status_code}")
        result = body.get("result", {})
        delivered_text = result.get("text", "")
        if not delivered_text:
            return False, "sendMessage response missing result.text field"
        if delivered_text != text:
            return False, f"result.text mismatch: sent {text!r}, got {delivered_text!r}"
        return True, None
    except Exception as e:
        return False, str(e)


def _log_affection(db: dict, recipient_id: str, sticker_pack: str,
                   file_id: str, caption: str, llm_model: str,
                   delivered: bool, error) -> None:
    """Insert a row into affection_outbox. Non-fatal on failure."""
    if not db:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(**{k: v for k, v in db.items()
                                   if k in ("host", "port", "dbname", "user", "password")})
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO affection_outbox "
            "(recipient_id, sticker_pack, sticker_file_id, caption, llm_model, delivered, error) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (recipient_id, sticker_pack, file_id, caption, llm_model, delivered, error),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[Log] affection_outbox write failed (non-fatal): {e}")


def main(
    telegram_bot_token: str,
    telegram_owner_id: str,
    affection_group_id: str,
    affection_sticker_packs: str,
    deepseek_key: str,
    portfolio_db: dict = {},
) -> dict:
    """Hourly affection sticker ping. Returns a dict describing the send."""
    now = datetime.now(SGT)
    hour = now.hour
    if hour < 8 or hour > 22:
        log.info(f"[Affection] Skipping — hour {hour} outside 8AM–10PM SGT window")
        return {"skipped": True, "hour": hour, "sent_at": now.isoformat()}

    packs = [p.strip() for p in affection_sticker_packs.split(",") if p.strip()]
    if not packs:
        raise RuntimeError("affection_sticker_packs is empty")

    log.info(f"[Affection] Fetching stickers from {len(packs)} pack(s)...")
    stickers = _fetch_stickers(telegram_bot_token, packs)
    if not stickers:
        raise RuntimeError(f"no stickers resolved from packs: {packs}")

    sticker = random.choice(stickers)
    file_id = sticker.get("file_id", "")
    if not file_id:
        raise RuntimeError("chosen sticker has no file_id")

    # Identify which pack this sticker came from (best effort)
    pack_name = sticker.get("set_name", packs[0])

    log.info(f"[Affection] Chose sticker file_id={file_id[:24]}... (pack={pack_name})")
    caption = _generate_caption(deepseek_key)
    log.info(f"[Affection] Caption ({len(caption)} chars): {caption}")

    delivered, err = _send_sticker(
        telegram_bot_token, affection_group_id, file_id, caption,
    )
    if delivered:
        log.info("[Affection] Sticker delivered to group")
    else:
        log.warning(f"[Affection] Sticker send failed: {err}")

    _log_affection(
        portfolio_db, affection_group_id, pack_name, file_id, caption,
        "deepseek-chat", delivered, err,
    )

    return {
        "sent_at": now.isoformat(),
        "group_id": affection_group_id,
        "sticker_pack": pack_name,
        "file_id": file_id,
        "caption": caption,
        "delivered": delivered,
        "error": err,
    }
