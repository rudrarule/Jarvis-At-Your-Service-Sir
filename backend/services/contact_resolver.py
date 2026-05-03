"""
contact_resolver.py - Natural-name WhatsApp contact resolution.

Builds a persistent name/alias index from Baileys contact fields and resolves
queries like "Mom" or "Maa" to WhatsApp JIDs/LIDs.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Any

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

CONNECTOR_URL = os.getenv("WA_CONNECTOR_URL", "http://localhost:3100")
TIMEOUT = 10.0
INDEX_PATH = Path(
    os.getenv(
        "WA_CONTACT_INDEX_PATH",
        Path(__file__).resolve().parents[1] / "data" / "whatsapp_contact_index.json",
    )
)

ALIASES = {
    "mom": ["mom", "maa", "mother", "mummy", "mumma", "mama"],
    "dad": ["dad", "papa", "father", "daddy", "baba"],
}


def normalize_name(value: str | None) -> str:
    """Lowercase, strip extra space, and remove emoji/special characters."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value).lower().strip())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _compact_key(value: str) -> str:
    return normalize_name(value).replace(" ", "")


def _dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for match in matches:
        jid = match.get("chat_id") or match.get("jid")
        if not jid or jid in seen:
            continue
        seen.add(jid)
        deduped.append(match)
    return deduped


def _display_name(contact: dict[str, Any]) -> str:
    return (
        contact.get("chat_name")
        or contact.get("displayName")
        or contact.get("pushName")
        or contact.get("notify")
        or contact.get("name")
        or contact.get("short")
        or contact.get("id")
        or contact.get("jid")
        or "Unknown contact"
    )


def _contact_jid(contact: dict[str, Any]) -> str:
    return contact.get("chat_id") or contact.get("jid") or contact.get("id") or ""


def _candidate_names(contact: dict[str, Any]) -> list[str]:
    names = [
        contact.get("name"),
        contact.get("notify"),
        contact.get("pushName"),
        contact.get("short"),
        contact.get("chat_name"),
        contact.get("displayName"),
    ]
    return [name for name in names if name]


def _match_payload(
    contact: dict[str, Any],
    *,
    matched_on: str,
    match_type: str,
    score: float = 1.0,
) -> dict[str, Any]:
    jid = _contact_jid(contact)
    display_name = _display_name(contact)
    return {
        "chat_id": jid,
        "jid": jid,
        "chat_name": display_name,
        "display_name": display_name,
        "is_group": jid.endswith("@g.us"),
        "matched_on": matched_on,
        "match_type": match_type,
        "score": round(score, 3),
    }


def build_contact_index(contacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build a normalized name -> contact matches index."""
    index: dict[str, list[dict[str, Any]]] = {}
    contacts_by_jid: dict[str, dict[str, Any]] = {}

    for contact in contacts:
        jid = _contact_jid(contact)
        if not jid:
            continue
        contacts_by_jid[jid] = contact
        for raw_name in _candidate_names(contact):
            for key in {normalize_name(raw_name), _compact_key(raw_name)}:
                if not key:
                    continue
                index.setdefault(key, []).append(
                    _match_payload(contact, matched_on=raw_name, match_type="name")
                )

    for canonical, variants in ALIASES.items():
        target_matches = []
        for key in {normalize_name(canonical), _compact_key(canonical)}:
            target_matches.extend(index.get(key, []))

        if not target_matches:
            for variant in variants:
                for key in {normalize_name(variant), _compact_key(variant)}:
                    target_matches.extend(index.get(key, []))

        target_matches = _dedupe_matches(target_matches)
        if not target_matches:
            continue

        for variant in variants:
            for key in {normalize_name(variant), _compact_key(variant)}:
                if not key:
                    continue
                index.setdefault(key, [])
                existing = _dedupe_matches(index[key] + [
                    {**match, "matched_on": variant, "match_type": "alias"}
                    for match in target_matches
                ])
                index[key] = existing

    return {key: _dedupe_matches(matches) for key, matches in index.items()}


def persist_contact_index(
    contacts: list[dict[str, Any]],
    index: dict[str, list[dict[str, Any]]],
) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "aliases": ALIASES,
        "contacts": contacts,
        "index": index,
    }
    INDEX_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_persisted_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"contacts": [], "index": {}}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[CONTACT RESOLVER] Failed to load index: {exc}")
        return {"contacts": [], "index": {}}


async def fetch_baileys_contacts(sync: bool = False) -> list[dict[str, Any]]:
    """Fetch contact records from the Baileys connector."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if sync:
                try:
                    await client.post(f"{CONNECTOR_URL}/sync-contacts")
                except Exception as exc:
                    print(f"[CONTACT RESOLVER] Contact sync trigger failed: {exc}")
            resp = await client.get(f"{CONNECTOR_URL}/contacts")
            resp.raise_for_status()
            data = resp.json()
            return data.get("contacts", [])
    except Exception as exc:
        print(f"[CONTACT RESOLVER] Contact fetch failed: {exc}")
        return []


async def refresh_contact_index(sync: bool = False) -> dict[str, list[dict[str, Any]]]:
    contacts = await fetch_baileys_contacts(sync=sync)
    if not contacts:
        persisted = load_persisted_index()
        return persisted.get("index", {})

    index = build_contact_index(contacts)
    persist_contact_index(contacts, index)
    print(f"[CONTACT RESOLVER] Built index: {len(index)} names from {len(contacts)} contacts")
    return index


async def resolve_contact(query: str) -> dict[str, Any]:
    """
    Resolve a natural-language contact query.

    Returns:
      {"status": "single", "match": {...}, "matches": [...]}
      {"status": "multiple", "matches": [...]}
      {"status": "none", "matches": []}
    """
    normalized = normalize_name(query)
    compact = _compact_key(query)
    if not normalized:
        return {"status": "none", "matches": []}

    index = await refresh_contact_index(sync=False)
    if not index:
        index = await refresh_contact_index(sync=True)

    for key in (normalized, compact):
        exact = _dedupe_matches(index.get(key, []))
        if exact:
            status = "single" if len(exact) == 1 else "multiple"
            return {"status": status, "match": exact[0] if len(exact) == 1 else None, "matches": exact}

    alias_targets = []
    for canonical, variants in ALIASES.items():
        variant_keys = {normalize_name(v) for v in variants} | {_compact_key(v) for v in variants}
        if normalized in variant_keys or compact in variant_keys:
            alias_targets.extend(index.get(normalize_name(canonical), []))
            alias_targets.extend(index.get(_compact_key(canonical), []))

    alias_targets = _dedupe_matches(alias_targets)
    if alias_targets:
        status = "single" if len(alias_targets) == 1 else "multiple"
        return {
            "status": status,
            "match": alias_targets[0] if len(alias_targets) == 1 else None,
            "matches": alias_targets,
        }

    keys = list(index.keys())
    fuzzy_keys = get_close_matches(normalized, keys, n=5, cutoff=0.72)
    if compact != normalized:
        fuzzy_keys.extend(get_close_matches(compact, keys, n=5, cutoff=0.72))

    fuzzy_matches = []
    for key in dict.fromkeys(fuzzy_keys):
        score = max(
            SequenceMatcher(None, normalized, key).ratio(),
            SequenceMatcher(None, compact, key).ratio(),
        )
        for match in index.get(key, []):
            fuzzy_matches.append({**match, "match_type": "fuzzy", "matched_on": key, "score": score})

    fuzzy_matches = _dedupe_matches(sorted(fuzzy_matches, key=lambda item: item["score"], reverse=True))
    if fuzzy_matches:
        status = "single" if len(fuzzy_matches) == 1 else "multiple"
        return {
            "status": status,
            "match": fuzzy_matches[0] if len(fuzzy_matches) == 1 else None,
            "matches": fuzzy_matches[:5],
        }

    return {"status": "none", "matches": []}
