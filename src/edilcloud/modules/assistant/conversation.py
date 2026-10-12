from __future__ import annotations

import re
from typing import Any


REFERENCE_RE = re.compile(
    r"\b(?:quell[oaie]|quest[oaie]|precedent[ei]|sopra|stess[oaie]|loro|lo|li|ne)\b"
    r"|\b(?:primo|secondo|terzo|quarto|quinto|ultima?|first|second|third|last)\s+(?:punto|riga|voce|elemento|point|row|item)\b"
    r"|^(?:e |invece\b|poi\b|approfondisci\b|continua\b|riassumi\b|riscrivi\b|metti\b|trasforma\b)"
    r"|\b(?:that|those|these|their|previous|above)\b|^(?:and |what about\b|expand\b|continue\b|rewrite\b)",
    re.IGNORECASE,
)
FORMAT_RE = re.compile(r"\b(?:tabella|checklist|elenco|sintetiz|piu breve|pi\u00f9 breve|riformula|traduci)\b", re.IGNORECASE)
STOP_WORDS = set("come cosa quale quali quando dove per con che del della delle degli dei sono una uno nel nella progetto cantiere puoi fai fammi questo quello questa quella gli loro delle tutto nella".split())


def is_contextual_follow_up(question: str) -> bool:
    text = (question or "").strip()
    return bool(REFERENCE_RE.search(text) or re.match(r"^(?:in tabella|piu breve|pi\u00f9 breve|riformula|traduci)\b", text, re.IGNORECASE))


def select_conversation_memory(
    *, question: str, recent: list[Any], archived: list[Any], anchors: list[Any],
    max_chars: int = 36000, archive_chars: int = 8000,
) -> list[Any]:
    """Keep recent turns plus query-relevant older turns from this authorized thread."""
    selected: dict[int, Any] = {}
    reserved = min(archive_chars, max_chars // 4) if archived or anchors else 0
    remaining = max_chars - reserved
    for message in reversed(recent):
        if message.role not in {"user", "assistant"} or not (message.content or "").strip():
            continue
        size = min(len(message.content), 12000)
        if size <= remaining:
            selected[message.id] = message
            remaining -= size
    tokens = set(re.findall(r"\w{3,}", question.lower())) - STOP_WORDS
    scored = sorted(
        archived, key=lambda message: (len(tokens & set(re.findall(r"\w{3,}", message.content.lower()))), message.id),
        reverse=True,
    )
    archive_remaining = min(archive_chars, remaining + reserved)
    # Opening turns retain user-provided names/preferences even in an elliptical follow-up.
    for message in [*anchors, *scored[:12]]:
        if message.id in selected or message.role not in {"user", "assistant"}:
            continue
        if message not in anchors and not tokens.intersection(re.findall(r"\w{3,}", message.content.lower())):
            continue
        size = min(len(message.content), 12000)
        if size <= archive_remaining:
            selected[message.id] = message
            archive_remaining -= size
    return sorted(selected.values(), key=lambda message: (message.created_at, message.id))


def conversation_input(messages: list[Any], citations: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    current_sources = {item["source_key"]: item["index"] for item in (citations or [])}
    history = []
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        text = (message.content or "").strip()[:12000]
        if not text:
            continue
        if message.role == "assistant":
            prior_sources = {str(item.get("index")): item for item in (getattr(message, "citations", None) or [])}

            def rebind(match):
                source = prior_sources.get(match.group(1), {})
                index = current_sources.get(source.get("source_key"))
                return f"[{index}]" if index else ""

            text = re.sub(r"\[(\d+)\]", rebind, text)
        history.append({"role": message.role, "content": text})
    return history


def contextual_retrieval_query(question: str, messages: list[Any]) -> str:
    if not messages or not is_contextual_follow_up(question):
        return question.strip()
    previous_user = next((item for item in reversed(messages) if item.role == "user"), None)
    previous_answer = next((item for item in reversed(messages) if item.role == "assistant"), None)
    parts = [question.strip()]
    if previous_user:
        # Resolve formatting-only follow-ups against the last substantive question.
        substantive = next((item for item in reversed(messages) if item.role == "user" and not FORMAT_RE.search(item.content)), previous_user)
        parts.append(f"Domanda precedente: {substantive.content[:1200]}")
    if previous_answer:
        labels = [str(item.get("label") or "") for item in (getattr(previous_answer, "citations", None) or [])]
        parts.append(f"Risposta precedente: {previous_answer.content[:2400]}")
        if any(labels):
            parts.append(f"Fonti precedenti: {'; '.join(labels)[:1200]}")
    return "\n".join(parts)
