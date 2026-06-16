"""
Simple formatter helpers — nothing fancy, just WhatsApp-safe text.
"""


def draft_notification(draft_id: int, from_name: str, inbound: str, draft: str) -> str:
    return (
        f"📨 *{from_name}*: \"{inbound}\"\n\n"
        f"Draft: \"{draft}\"\n\n"
        f"/send_{draft_id} · /edit_{draft_id} [new text] · /ignore_{draft_id}"
    )


def confirmation_prompt(tool_name: str, description: str) -> str:
    return f"⚠️ {description}\n\nReply *confirm* or *cancel*."


def outbound_draft_notification(draft_id: int, to_name: str, to_phone: str, text: str) -> str:
    return (
        f"📤 To *{to_name}* ({to_phone}):\n\"{text}\"\n\n"
        f"/send_{draft_id} · /edit_{draft_id} [new text] · /ignore_{draft_id}"
    )
