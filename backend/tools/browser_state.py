"""
browser_state.py — Production-Grade Browser State Infrastructure

Provides:
  - ElementRegistry: Stable ID generation, multi-strategy selector resolution,
    stale detection, and auto-scroll for off-screen elements.
  - Accessibility Tree extraction via Playwright snapshots.
  - State delta computation for before/after action verification.
  - Unified page observation combining AXTree + registry + screenshots.
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page, Locator


def _debug_dir() -> Optional[str]:
    path = os.getenv("JARVIS_E2E_DEBUG_DIR")
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    return path


def _safe_debug_label(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("_")[:80] or "debug"


async def _write_page_debug_artifacts(page: Page, label: str, extra: Optional[dict[str, Any]] = None) -> None:
    path = _debug_dir()
    if not path:
        return
    stamp = f"{int(time.time() * 1000)}_{_safe_debug_label(label)}"
    meta: dict[str, Any] = {"label": label, "extra": extra or {}}
    try:
        meta["url"] = page.url
        meta["title"] = await page.title()
        meta["visible_text"] = (await page.evaluate("() => document.body ? document.body.innerText : ''") or "")[:8000]
    except Exception as exc:
        meta["metadata_error"] = str(exc)
    try:
        await page.screenshot(path=os.path.join(path, f"{stamp}.png"), full_page=True)
        meta["screenshot"] = f"{stamp}.png"
    except Exception as exc:
        meta["screenshot_error"] = str(exc)
    try:
        html = await page.content()
        with open(os.path.join(path, f"{stamp}.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        meta["html"] = f"{stamp}.html"
    except Exception as exc:
        meta["html_error"] = str(exc)
    with open(os.path.join(path, f"{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, default=str)


# ═══════════════════════════════════════════════════════════
# ELEMENT REGISTRY ENTRY
# ═══════════════════════════════════════════════════════════

@dataclass
class ElementRegistryEntry:
    """A single interactive element in the virtual registry."""
    id: str                             # Stable hash-based ID (e.g., "el_a3f1c0e2")
    index: int                          # Sequential numeric index for LLM-friendly references
    role: str                           # ARIA / semantic role (button, link, textbox, etc.)
    name: str                           # Accessible name / aria-label / visible text
    tag: str                            # HTML tag (a, button, input, select, textarea)
    selector: str                       # Primary Playwright selector
    fallback_selectors: List[str] = field(default_factory=list)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (x, y, width, height) viewport-relative
    visible: bool = True
    enabled: bool = True
    input_type: str = ""                # For inputs: text, password, email, checkbox, etc.
    value: str = ""                     # Current value (for inputs/textareas)
    placeholder: str = ""
    context: str = ""                   # Parent context text for disambiguation
    is_in_viewport: bool = True         # Whether element is currently in viewport
    ref: str = ""                       # Per-observation ref, e.g. "obs_ab12#e7"
    dom_path: str = ""                  # Structural DOM path for exact re-resolution
    dom_index: int = 0                  # Document-order index within this scan

    def to_llm_dict(self) -> dict:
        """Compact representation sent to the LLM (strips empty fields to save tokens)."""
        d = {
            "id": self.index,
            "ref": self.index,
            "role": self.role,
            "name": self.name,
        }
        if self.tag and self.tag != self.role:
            d["tag"] = self.tag
        if self.input_type:
            d["type"] = self.input_type
        if self.value:
            d["value"] = self.value[:80]
        if self.placeholder:
            d["placeholder"] = self.placeholder[:60]
        if self.context:
            d["context"] = self.context[:120]
        if not self.enabled:
            d["enabled"] = False
        if not self.is_in_viewport:
            d["offscreen"] = True
        return d


# ═══════════════════════════════════════════════════════════
# ELEMENT REGISTRY
# ═══════════════════════════════════════════════════════════

class ElementRegistry:
    """
    Virtual element registry that maps stable IDs to Playwright locators.

    Instead of injecting temporary integer IDs into the DOM (which break on
    React/Vue re-renders), this registry maintains a mapping from semantic
    identifiers to multi-strategy selector chains.

    Elements are referenced by a sequential integer `index` (for LLM ease)
    which maps internally to a stable hash `id`.
    """

    def __init__(self, page: Page):
        self.page = page
        self._entries: Dict[str, ElementRegistryEntry] = {}  # stable_id -> entry
        self._index_map: Dict[int, str] = {}                 # numeric index -> stable_id
        self._ref_map: Dict[str, str] = {}                   # per-obs ref -> stable_id
        self._observation_id: str = ""                       # id of the current observation
        self._next_index: int = 1
        self._timestamp: float = 0.0                          # When registry was last built

    @property
    def entries(self) -> Dict[str, ElementRegistryEntry]:
        return self._entries

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def age_seconds(self) -> float:
        return time.time() - self._timestamp if self._timestamp else float("inf")

    def clear(self):
        """Wipe registry for a fresh observation cycle."""
        self._entries.clear()
        self._index_map.clear()
        self._ref_map.clear()
        self._next_index = 1
        self._timestamp = time.time()

    def get_by_ref(self, ref: str) -> Optional["ElementRegistryEntry"]:
        """Look up an element by its per-observation ref (e.g. 'obs_ab12#e7')."""
        sid = self._ref_map.get(ref)
        return self._entries.get(sid) if sid else None

    # ── Stable ID Generation ──────────────────────────────

    @staticmethod
    def _generate_stable_id(role: str, name: str, tag: str, selector: str,
                            dom_path: str = "", bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)) -> str:
        """
        Deterministic, COLLISION-RESISTANT ID.

        The old version hashed only role:name:tag:selector, so duplicate elements
        (e.g. ten identical "Add to cart" buttons) collapsed to one registry entry
        and indices silently pointed at the wrong DOM node. We now mix in:
          - dom_path: distinguishes duplicate siblings structurally
          - a coarse bbox bucket (20px grid): tolerates minor reflow while keeping
            visually-distinct elements distinct
        """
        bx, by = (round((bbox[0] or 0) / 20), round((bbox[1] or 0) / 20))
        raw = f"{role}|{name}|{tag}|{selector}|{dom_path}|{bx},{by}"
        return f"el_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"

    # ── Registration ──────────────────────────────────────

    async def scan_and_register(self, max_elements: int = 80) -> List[ElementRegistryEntry]:
        """
        Scans the current page DOM for interactive elements, builds
        semantic selectors, and populates the registry.

        Returns the list of registered entries (sorted by Y position).
        """
        self.clear()
        # Stamp this observation so every element ref/binding can be traced to it.
        self._observation_id = "obs_" + hashlib.sha256(
            f"{self.page.url}:{time.time()}".encode("utf-8")
        ).hexdigest()[:8]

        # JavaScript that extracts interactive element attributes WITHOUT
        # injecting anything into the DOM (no data-jarvis-id, no markers).
        scan_script = r"""() => {
            const results = [];
            const interactablesList = [];
            document.querySelectorAll(
                'a, button, input:not([type="hidden"]), select, textarea, ' +
                '[role="button"], [role="link"], [role="checkbox"], [role="radio"], ' +
                '[role="tab"], [role="menuitem"], [role="option"], [role="switch"], ' +
                '[contenteditable="true"]'
            ).forEach(el => interactablesList.push(el));

            // Custom search field wrappers and labels (div/span/p/label)
            const customRegex = /^(from|to|departure|return|travellers|guests|check-in|check-out|checkin|checkout|passengers|origin|destination|date|dates|calendar|one way|round trip|one-way|multi-city)(\s|:|$)/i;
            const dateRegex = /^(mon|tue|wed|thu|fri|sat|sun)\b.*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i;
            const passengerRegex = /^\d+\s+(traveller|passenger|guest|adult|child|infant|room)/i;

            function isInsideDropdown(el) {
                let parent = el.parentElement;
                while (parent) {
                    const pClass = (parent.className || '').toString().toLowerCase();
                    const pId = (parent.id || '').toString().toLowerCase();
                    const pRole = (parent.getAttribute('role') || '').toString().toLowerCase();
                    if (
                        pClass.includes('autocomplete') || pClass.includes('dropdown') || 
                        pClass.includes('popover') || pClass.includes('popup') ||
                        pClass.includes('listbox') || pClass.includes('results') ||
                        pClass.includes('menu') || pClass.includes('calendar') ||
                        pClass.includes('datepicker') || pClass.includes('picker') ||
                        pClass.includes('month') ||
                        pId.includes('autocomplete') || pId.includes('dropdown') || 
                        pId.includes('listbox') || pId.includes('results') ||
                        pId.includes('calendar') || pId.includes('datepicker') ||
                        pRole === 'listbox' || pRole === 'menu' || pRole === 'dialog' || pRole === 'grid'
                    ) {
                        return true;
                    }
                    parent = parent.parentElement;
                }
                return false;
            }

            function matchesSelectorRule(el) {
                const tag = el.tagName.toLowerCase();
                if (tag === 'a' || tag === 'button' || tag === 'input' || tag === 'select' || tag === 'textarea') return false;
                if (el.getAttribute('role') === 'button' || el.getAttribute('role') === 'link') return false;

                const text = (el.innerText || '').trim();
                // Rule 1: travel search wrappers (from, to, etc.)
                if (text.length > 0 && text.length < 50) {
                    if (customRegex.test(text) || dateRegex.test(text) || passengerRegex.test(text)) {
                        return true;
                    }
                }

                // Rule 2: custom autocomplete dropdown suggestions
                if (isInsideDropdown(el) && text.length > 0 && text.length < 150) {
                    const className = (el.className || '').toString().toLowerCase();
                    const isSuggestionRow = className && (
                        className.includes('list') || 
                        className.includes('item') || 
                        className.includes('row') || 
                        className.includes('option') ||
                        className.includes('suggestion') ||
                        className.includes('clickable')
                    );
                    if (isSuggestionRow) return true;
                }

                // Rule 3: Calendar days (1-31) inside picker/calendar containers
                if (isInsideDropdown(el) && /^\d{1,2}$/.test(text)) {
                    const num = parseInt(text, 10);
                    if (num >= 1 && num <= 31) {
                        return true;
                    }
                }

                return false;
            }

            document.querySelectorAll('div, span, p, label, li, td').forEach(el => {
                if (matchesSelectorRule(el)) {
                    // Check if any descendant also matches to only keep the leaf element
                    const hasMatchingDescendant = Array.from(el.querySelectorAll('*')).some(matchesSelectorRule);
                    if (!hasMatchingDescendant) {
                        if (!interactablesList.includes(el)) {
                            interactablesList.push(el);
                        }
                    }
                }
            });

            const interactables = interactablesList;

            function esc(v) {
                return window.CSS && CSS.escape ? CSS.escape(v) : String(v).replace(/"/g, '\\"');
            }

            // Structural path (e.g. "div:nth(2)>button:nth(4)") so the backend can
            // re-resolve the EXACT element later instead of guessing by fuzzy text.
            function domPath(el) {
                const parts = [];
                let node = el;
                while (node && node.nodeType === 1 && parts.length < 25) {
                    let seg = node.tagName.toLowerCase();
                    const parent = node.parentElement;
                    if (parent) {
                        const sames = Array.from(parent.children).filter(c => c.tagName === node.tagName);
                        if (sames.length > 1) seg += ':nth(' + sames.indexOf(node) + ')';
                    }
                    parts.unshift(seg);
                    node = node.parentElement;
                }
                return parts.join('>');
            }

            interactables.forEach(el => {
                const rect = el.getBoundingClientRect();
                // Include elements even if off-screen (height/width > 0 means rendered)
                if (rect.width === 0 && rect.height === 0) return;

                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || '';
                const ariaLabel = el.getAttribute('aria-label') || '';
                const name = el.getAttribute('name') || '';
                const placeholder = el.placeholder || '';
                const inputType = el.type || '';
                const id = el.id || '';
                const value = (el.value || '').substring(0, 100);

                // Compute accessible name: priority order
                let text = ariaLabel
                    || el.getAttribute('title')
                    || (el.innerText || '').trim().substring(0, 80)
                    || placeholder
                    || name
                    || '';
                text = text.replace(/\s+/g, ' ').trim();

                // Build a stable CSS selector
                let cssSelector = tag;
                if (id) {
                    cssSelector = '#' + esc(id);
                } else {
                    if (ariaLabel) {
                        cssSelector = tag + '[aria-label="' + esc(ariaLabel) + '"]';
                    } else if (name) {
                        cssSelector = tag + '[name="' + esc(name) + '"]';
                    } else if (placeholder) {
                        cssSelector = tag + '[placeholder="' + esc(placeholder) + '"]';
                    } else if (el.className) {
                        const firstClass = el.className.trim().split(/\s+/)[0];
                        if (firstClass && !firstClass.includes(':') && !firstClass.includes(' ')) {
                            cssSelector = tag + '.' + esc(firstClass);
                        }
                    }
                }

                // Parent context for disambiguation
                let context = '';
                let node = el.parentElement;
                for (let i = 0; i < 6 && node; i++) {
                    const t = (node.innerText || '').replace(/\u20b9/g, 'Rs').replace(/\s+/g, ' ').trim();
                    if (t.length > 30) {
                        context = t.substring(0, 150);
                        break;
                    }
                    node = node.parentElement;
                }

                const inViewport = (
                    rect.top >= 0 && rect.left >= 0 &&
                    rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                    rect.right <= (window.innerWidth || document.documentElement.clientWidth)
                );

                const disabled = Boolean(
                    el.disabled ||
                    el.getAttribute('aria-disabled') === 'true' ||
                    el.hasAttribute('disabled')
                );

                results.push({
                    tag,
                    role,
                    text,
                    ariaLabel,
                    name,
                    placeholder,
                    inputType,
                    cssSelector,
                    elementId: id,
                    value,
                    context: context || '',
                    disabled,
                    inViewport,
                    domPath: domPath(el),
                    domIndex: results.length,
                    bbox: {
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    },
                    sortY: rect.top + window.scrollY
                });
            });

            // Sort by vertical position (top-of-page first)
            results.sort((a, b) => a.sortY - b.sortY);
            return results;
        }"""

        raw_elements = await self.page.evaluate(scan_script)

        registered: List[ElementRegistryEntry] = []
        for raw in raw_elements[:max_elements]:
            tag = raw["tag"]
            role = raw["role"] or _infer_role(tag, raw.get("inputType", ""))
            name = raw["text"] or raw["ariaLabel"] or raw["placeholder"] or raw["name"] or ""
            css_selector = raw["cssSelector"]
            bbox_raw = raw["bbox"]
            bbox = (bbox_raw["x"], bbox_raw["y"], bbox_raw["width"], bbox_raw["height"])
            dom_path = raw.get("domPath", "")
            dom_index = raw.get("domIndex", len(registered))

            stable_id = self._generate_stable_id(role, name, tag, css_selector, dom_path, bbox)
            # Collision-proof: even two truly identical nodes get distinct ids.
            if stable_id in self._entries:
                stable_id = f"{stable_id}_{dom_index}"

            # Build fallback selector chain
            fallbacks = []
            if raw["ariaLabel"]:
                fallbacks.append(f'{tag}[aria-label="{raw["ariaLabel"]}"]')
            if raw["name"]:
                fallbacks.append(f'{tag}[name="{raw["name"]}"]')
            if raw["elementId"]:
                fallbacks.append(f'#{raw["elementId"]}')
            if raw["placeholder"]:
                fallbacks.append(f'{tag}[placeholder="{raw["placeholder"]}"]')

            idx = self._next_index
            self._next_index += 1
            ref = f"{self._observation_id}#e{idx}"

            entry = ElementRegistryEntry(
                id=stable_id,
                ref=ref,
                index=idx,
                role=role,
                name=name,
                tag=tag,
                selector=css_selector,
                fallback_selectors=fallbacks,
                bbox=bbox,
                visible=True,
                enabled=not raw["disabled"],
                input_type=raw.get("inputType", ""),
                value=raw.get("value", ""),
                placeholder=raw.get("placeholder", ""),
                context=raw.get("context", ""),
                is_in_viewport=raw.get("inViewport", True),
                dom_path=dom_path,
                dom_index=dom_index,
            )

            self._entries[stable_id] = entry
            self._index_map[idx] = stable_id
            self._ref_map[ref] = stable_id
            registered.append(entry)

        self._timestamp = time.time()
        print(f"[Registry] Registered {len(registered)} elements "
              f"({sum(1 for e in registered if e.is_in_viewport)} in viewport, "
              f"{sum(1 for e in registered if not e.is_in_viewport)} off-screen)")
        return registered

    # ── Lookup ────────────────────────────────────────────

    def get_by_index(self, index: int) -> Optional[ElementRegistryEntry]:
        """Look up an element by its sequential numeric index."""
        stable_id = self._index_map.get(index)
        return self._entries.get(stable_id) if stable_id else None

    def get_by_id(self, stable_id: str) -> Optional[ElementRegistryEntry]:
        """Look up an element by its stable hash ID."""
        return self._entries.get(stable_id)

    def get_all_indices(self) -> List[int]:
        """Return all currently valid numeric indices."""
        return list(self._index_map.keys())

    # ── Multi-Strategy Locator Resolution ─────────────────

    async def resolve_locator(self, index) -> Optional[Locator]:
        """Resolve a registered element to a live Locator, IDENTITY-FIRST.

        Order: exact captured CSS selector -> structural dom_path -> captured
        fallback selectors -> semantic role+name -> label/placeholder -> fuzzy text.
        The old order tried fuzzy role+name first and then picked a blind `.first`,
        which on repeated labels ("Add to cart") landed on the wrong sibling. Now we
        resolve by the element we actually scanned, and when a strategy matches
        multiple nodes we choose the one whose bounding box is closest to the scanned
        bbox (see _disambiguate). Accepts a numeric index OR a per-observation ref.
        """
        entry = self.get_by_ref(index) if isinstance(index, str) else self.get_by_index(index)
        if not entry:
            print(f"[Registry] Ref/index {index} not found in registry")
            return None

        strategies = []

        # 1. EXACT captured CSS selector (the element we actually scanned)
        if entry.selector:
            strategies.append(("css_exact", lambda: self.page.locator(entry.selector)))

        # 2. Structural DOM path (survives text/attribute changes)
        if entry.dom_path:
            css = self._dom_path_to_css(entry.dom_path)
            if css:
                strategies.append(("dom_path", lambda c=css: self.page.locator(c)))

        # 3. Captured fallback selectors (aria-label / name / id / placeholder)
        for i, fb_sel in enumerate(entry.fallback_selectors):
            strategies.append((f"css_fallback_{i}", lambda s=fb_sel: self.page.locator(s)))

        # 4. Semantic role + name (now a FALLBACK, not the default)
        if entry.role and entry.name:
            strategies.append(("aria_role_exact", lambda: self.page.get_by_role(entry.role, name=entry.name, exact=True)))
            strategies.append(("aria_role", lambda: self.page.get_by_role(entry.role, name=entry.name, exact=False)))

        # 5. Label / placeholder (form inputs)
        if entry.name and entry.tag in ("input", "textarea", "select"):
            strategies.append(("label", lambda: self.page.get_by_label(entry.name, exact=False)))
        if entry.placeholder:
            strategies.append(("placeholder", lambda: self.page.get_by_placeholder(entry.placeholder, exact=False)))

        # 6. Fuzzy text (last resort before bbox coordinate click)
        if entry.name:
            strategies.append(("text", lambda: self.page.get_by_text(entry.name, exact=False)))
            strategies.append(("tag_text", lambda: self.page.locator(entry.tag).filter(has_text=entry.name)))

        for strategy_name, locator_fn in strategies:
            try:
                base_locator = locator_fn()
                count = await base_locator.count()
                if count <= 0:
                    continue
                if count == 1:
                    print(f"[Registry] Resolved {entry.ref or index} ('{entry.name[:40]}') via {strategy_name}")
                    return base_locator.first
                # Multiple matches -> bbox-proximity disambiguation (never blind .first)
                chosen = await self._disambiguate(base_locator, count, entry)
                if chosen is not None:
                    print(f"[Registry] Resolved {entry.ref or index} ('{entry.name[:40]}') "
                          f"via {strategy_name} +bbox (disambiguated {count})")
                    return chosen
            except Exception:
                continue

        # Last resort: coordinate click via entry.bbox is handled by the caller.
        print(f"[Registry] All strategies failed for {entry.ref or index} "
              f"('{entry.name[:40]}'). Coordinate fallback at bbox={entry.bbox}")
        return None

    @staticmethod
    def _dom_path_to_css(dom_path: str) -> str:
        """Convert 'div:nth(2)>button:nth(4)' -> 'div:nth-child(3)>button:nth-child(5)'."""
        out = []
        for seg in dom_path.split(">"):
            m = re.match(r"([a-z0-9]+):nth\((\d+)\)", seg)
            out.append(f"{m.group(1)}:nth-child({int(m.group(2)) + 1})" if m else seg)
        return ">".join(out)

    async def _disambiguate(self, locator, count: int, entry: "ElementRegistryEntry") -> Optional[Locator]:
        """Among multiple matches, pick the one whose bbox is closest to the scanned bbox."""
        ex, ey, ew, eh = entry.bbox
        target_cx, target_cy = ex + ew / 2, ey + eh / 2
        best, best_d = None, float("inf")
        for i in range(min(count, 15)):
            nth = locator.nth(i)
            try:
                if not await nth.is_visible():
                    continue
                box = await nth.bounding_box()
                if not box:
                    continue
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                d = (cx - target_cx) ** 2 + (cy - target_cy) ** 2
                if d < best_d:
                    best, best_d = nth, d
            except Exception:
                continue
        if best is None:
            # No measurable bbox anywhere -> fall back to first visible match.
            for i in range(min(count, 15)):
                try:
                    if await locator.nth(i).is_visible():
                        return locator.nth(i)
                except Exception:
                    continue
        return best

    # ── Interaction with Auto-Scroll ──────────────────────

    async def interact(
        self,
        index: int,
        action: str,
        text: str = "",
        press_enter: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute an interaction on a registered element with:
          - Multi-strategy locator resolution
          - Auto-scroll into viewport
          - Visual highlight feedback
          - Before/after state capture for delta verification
        """
        entry = self.get_by_index(index)
        capture_each = os.getenv("JARVIS_E2E_CAPTURE_EACH_ACTION", "").lower() in {"1", "true", "yes", "on"}
        if not entry:
            if capture_each:
                await _write_page_debug_artifacts(self.page, "registry_missing_index", {"index": index, "action": action})
            return {
                "success": False,
                "error": f"Element index {index} not found in registry. "
                         f"Valid indices: {sorted(self._index_map.keys())[:20]}. "
                         f"Re-observe the page to refresh the registry.",
                "action": action,
            }

        if not entry.enabled:
            if capture_each:
                await _write_page_debug_artifacts(
                    self.page,
                    "registry_disabled_element",
                    {"index": index, "action": action, "element": asdict(entry)},
                )
            return {
                "success": False,
                "error": f"Element '{entry.name}' (index {index}) is disabled and cannot be interacted with.",
                "action": action,
            }

        # Capture before-state
        before_url = self.page.url
        before_title = await self.page.title()

        # Resolve the locator
        locator = await self.resolve_locator(index)

        if locator is None:
            # Last resort: coordinate click
            x, y, w, h = entry.bbox
            center_x = x + (w / 2)
            center_y = y + (h / 2)
            if action == "click" and w > 0 and h > 0:
                print(f"[Registry] Coordinate fallback click at ({center_x}, {center_y})")
                if capture_each:
                    await _write_page_debug_artifacts(
                        self.page,
                        "before_registry_coordinate_click",
                        {"index": index, "action": action, "element": asdict(entry)},
                    )
                await self.page.mouse.click(center_x, center_y)
                await self.page.wait_for_timeout(2000)
                after_url = self.page.url
                after_title = await self.page.title()
                if capture_each:
                    await _write_page_debug_artifacts(
                        self.page,
                        "after_registry_coordinate_click",
                        {"index": index, "action": action, "element": asdict(entry), "before_url": before_url, "after_url": after_url},
                    )
                return {
                    "success": True,
                    "action": action,
                    "element_index": index,
                    "element_name": entry.name,
                    "element_role": entry.role,
                    "resolution_strategy": "coordinate_fallback",
                    "before_url": before_url,
                    "after_url": after_url,
                    "url_changed": before_url != after_url,
                    "title_changed": before_title != after_title,
                }
            if capture_each:
                await _write_page_debug_artifacts(
                    self.page,
                    "registry_resolve_failed",
                    {"index": index, "action": action, "element": asdict(entry)},
                )
            return {
                "success": False,
                "error": f"Could not resolve element '{entry.name}' (index {index}) "
                         f"via any strategy. The page may have changed. Re-observe to refresh.",
                "action": action,
            }

        try:
            # Auto-scroll the element into the viewport
            await locator.scroll_into_view_if_needed(timeout=5000)
            await self.page.wait_for_timeout(300)

            # Visual highlight (green flash for user feedback)
            try:
                await locator.evaluate("""(el) => {
                    el.style.outline = '3px solid #00ff00';
                    el.style.outlineOffset = '2px';
                    setTimeout(() => { el.style.outline = ''; el.style.outlineOffset = ''; }, 2000);
                }""")
            except Exception:
                pass  # Non-critical: highlight failure doesn't block interaction

            # Execute the action
            el_label = entry.name[:60] or entry.role
            print(f"[Registry] {action.upper()} element #{index}: '{el_label}'")
            if capture_each:
                await _write_page_debug_artifacts(
                    self.page,
                    "before_registry_interact",
                    {"index": index, "action": action, "text": text, "element": asdict(entry)},
                )

            if action == "click":
                await locator.click(timeout=5000)
            elif action == "type":
                try:
                    await locator.click(timeout=3000)
                    await locator.focus(timeout=3000)
                    await locator.fill("", timeout=2000)
                    await locator.press_sequentially(text, delay=100, timeout=8000)
                except Exception as exc:
                    print(f"[Registry] Standard type failed on index {index} ({exc}). Falling back to keyboard typing on active element.")
                    try:
                        await locator.click(timeout=2000)
                        await locator.focus(timeout=2000)
                    except Exception:
                        pass
                    # Select all and clear
                    await self.page.keyboard.press("Control+A")
                    await self.page.keyboard.press("Backspace")
                    await self.page.wait_for_timeout(100)
                    await self.page.keyboard.type(text, delay=100)

                if press_enter:
                    await self.page.keyboard.press("Enter")
                    # Auto-scroll after search submission
                    await self.page.wait_for_timeout(2000)
                    await self.page.mouse.wheel(0, 400)
                    await self.page.wait_for_timeout(500)
                    print(f"[Registry] Auto-scrolled 400px after type+enter")
            else:
                return {
                    "success": False,
                    "error": f"Unknown action '{action}'. Valid actions: 'click', 'type'.",
                    "action": action,
                }

            # Wait for page to settle
            await self.page.wait_for_timeout(2500)

            # Capture after-state
            after_url = self.page.url
            after_title = await self.page.title()
            if capture_each:
                await _write_page_debug_artifacts(
                    self.page,
                    "after_registry_interact",
                    {"index": index, "action": action, "text": text, "element": asdict(entry), "before_url": before_url, "after_url": after_url},
                )

            return {
                "success": True,
                "action": action,
                "element_index": index,
                "element_name": entry.name,
                "element_role": entry.role,
                "resolution_strategy": "locator",
                "before_url": before_url,
                "after_url": after_url,
                "before_title": before_title,
                "after_title": after_title,
                "url_changed": before_url != after_url,
                "title_changed": before_title != after_title,
            }

        except Exception as e:
            if capture_each:
                await _write_page_debug_artifacts(
                    self.page,
                    "registry_interact_failed",
                    {"index": index, "action": action, "text": text, "element": asdict(entry), "error": str(e)},
                )
            return {
                "success": False,
                "error": f"Interaction failed on '{entry.name}' (index {index}): {e}",
                "action": action,
                "element_index": index,
            }

    # ── Serialization ─────────────────────────────────────

    def to_llm_list(self, max_items: int = 50) -> List[dict]:
        """Compact list of elements for LLM consumption, sorted by index."""
        sorted_entries = sorted(self._entries.values(), key=lambda e: e.index)
        return [e.to_llm_dict() for e in sorted_entries[:max_items]]


# ═══════════════════════════════════════════════════════════
# ACCESSIBILITY TREE EXTRACTION
# ═══════════════════════════════════════════════════════════

_IGNORED_AX_ROLES = frozenset({
    "generic", "presentation", "none", "None", "",
    "InlineTextBox", "StaticText",
})

_INTERACTIVE_AX_ROLES = frozenset({
    "button", "link", "textbox", "checkbox", "radio",
    "combobox", "listbox", "option", "menuitem", "tab",
    "switch", "searchbox", "spinbutton", "slider",
})


async def get_accessibility_tree(page: Page, max_depth: int = 8) -> Dict[str, Any]:
    """
    Extracts a pruned accessibility tree from the browser via Playwright.

    The tree is aggressively filtered to remove layout-only nodes (generic,
    presentation) while preserving all semantic and interactive nodes.
    This typically reduces the tree by 80-90% compared to raw DOM.
    """
    try:
        raw_tree = await page.accessibility.snapshot()
    except Exception as e:
        print(f"[AXTree] Snapshot failed: {e}")
        return {"role": "document", "name": "Snapshot unavailable", "error": str(e)}

    if not raw_tree:
        return {"role": "document", "name": "Empty page"}

    def _prune(node: dict, depth: int = 0) -> Optional[dict]:
        if not node or depth > max_depth:
            return None

        role = node.get("role", "")
        name = (node.get("name") or "").strip()
        value = (node.get("value") or "").strip()

        # Recursively process children
        children_raw = node.get("children", [])
        children = []
        for child in children_raw:
            pruned = _prune(child, depth + 1)
            if pruned:
                children.append(pruned)

        # Decide whether to keep this node
        role_lower = role.lower() if role else ""
        is_interactive = role_lower in _INTERACTIVE_AX_ROLES
        is_semantic = role_lower not in _IGNORED_AX_ROLES and role_lower != ""
        has_content = bool(name) or bool(value)
        has_children = len(children) > 0

        if not (is_semantic or has_content or has_children):
            return None

        # Build compact node
        result: Dict[str, Any] = {}
        if role and role_lower not in _IGNORED_AX_ROLES:
            result["role"] = role
        if name:
            result["name"] = name[:120]
        if value:
            result["value"] = value[:80]
        if is_interactive:
            result["interactive"] = True

        # Flatten single-child generic nodes (reduce nesting noise)
        if len(children) == 1 and not is_interactive and not has_content:
            return children[0]

        if children:
            result["children"] = children

        return result if result else None

    pruned = _prune(raw_tree)
    return pruned or {"role": "document", "name": "Pruned tree empty"}


async def get_accessibility_tree_text(page: Page, max_lines: int = 150) -> str:
    """
    Returns a flat text representation of the accessibility tree,
    suitable for direct injection into LLM prompts.
    """
    # Use aria_snapshot if page.accessibility is missing (modern Playwright)
    if not hasattr(page, "accessibility"):
        try:
            snapshot = await page.locator("body").aria_snapshot()
            if snapshot:
                lines = [line for line in snapshot.split("\n") if line.strip()]
                return "\n".join(lines[:max_lines])
        except Exception as e:
            print(f"[AXTree] aria_snapshot fallback failed: {e}")

    tree = await get_accessibility_tree(page)
    if not tree or "error" in tree:
        try:
            snapshot = await page.locator("body").aria_snapshot()
            if snapshot:
                lines = [line for line in snapshot.split("\n") if line.strip()]
                return "\n".join(lines[:max_lines])
        except Exception as e:
            print(f"[AXTree] aria_snapshot fallback failed: {e}")

    lines: List[str] = []

    def _flatten(node: dict, indent: int = 0):
        if len(lines) >= max_lines:
            return
        role = node.get("role", "")
        name = node.get("name", "")
        value = node.get("value", "")

        prefix = "  " * indent
        parts = []
        if role:
            parts.append(f"[{role}]")
        if name:
            parts.append(f'"{name}"')
        if value:
            parts.append(f'value="{value}"')
        if node.get("interactive"):
            parts.append("⚡")

        if parts:
            lines.append(f"{prefix}{' '.join(parts)}")

        for child in node.get("children", []):
            _flatten(child, indent + 1)

    _flatten(tree)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# STATE DELTA COMPUTATION
# ═══════════════════════════════════════════════════════════

@dataclass
class StateDelta:
    """Captures what changed between two observation snapshots."""
    url_changed: bool = False
    title_changed: bool = False
    before_url: str = ""
    after_url: str = ""
    before_title: str = ""
    after_title: str = ""
    elements_added: int = 0
    elements_removed: int = 0
    registry_size_before: int = 0
    registry_size_after: int = 0
    significant_change: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        parts = []
        if self.url_changed:
            parts.append(f"URL: {self.before_url} → {self.after_url}")
        if self.title_changed:
            parts.append(f"Title: {self.before_title} → {self.after_title}")
        if self.elements_added:
            parts.append(f"+{self.elements_added} new elements")
        if self.elements_removed:
            parts.append(f"-{self.elements_removed} removed elements")
        if not parts:
            return "No significant page change detected."
        return " | ".join(parts)


def compute_state_delta(
    before_url: str,
    before_title: str,
    before_ids: set,
    after_url: str,
    after_title: str,
    after_ids: set,
) -> StateDelta:
    """Computes structural differences between two observation states."""
    added = after_ids - before_ids
    removed = before_ids - after_ids
    url_changed = before_url != after_url
    title_changed = before_title != after_title

    return StateDelta(
        url_changed=url_changed,
        title_changed=title_changed,
        before_url=before_url,
        after_url=after_url,
        before_title=before_title,
        after_title=after_title,
        elements_added=len(added),
        elements_removed=len(removed),
        registry_size_before=len(before_ids),
        registry_size_after=len(after_ids),
        significant_change=url_changed or title_changed or len(added) > 5 or len(removed) > 5,
    )


# ═══════════════════════════════════════════════════════════
# UNIFIED PAGE OBSERVATION
# ═══════════════════════════════════════════════════════════

# Singleton registry — shared across tool calls within a browser session
_active_registry: Optional[ElementRegistry] = None
_last_observation_state: Dict[str, Any] = {}


def get_active_registry(page: Page) -> ElementRegistry:
    """Returns the active registry, creating one if needed."""
    global _active_registry
    if _active_registry is None or _active_registry.page != page:
        _active_registry = ElementRegistry(page)
    return _active_registry


async def observe_page_state(
    page: Page,
    include_screenshot: bool = False,
    include_ax_tree_text: bool = True,
    max_elements: int = 120,
) -> Dict[str, Any]:
    """
    Unified observation function that combines:
      1. Page metadata (URL, title)
      2. Accessibility tree (pruned)
      3. Interactive element registry (with fallback selectors)
      4. Optional screenshot
      5. State delta from last observation

    This replaces the old inject_element_markers() approach entirely.
    """
    global _last_observation_state

    # Wait for page stability
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass

    # 1. Page metadata
    url = page.url
    title = await page.title()

    # 2. Accessibility tree
    ax_tree_text = ""
    if include_ax_tree_text:
        ax_tree_text = await get_accessibility_tree_text(page, max_lines=100)

    # 3. Visible text (compressed)
    try:
        visible_text = await page.evaluate("() => document.body.innerText")
        visible_text = (visible_text or "")[:400]
    except Exception:
        visible_text = ""

    # 4. Registry scan
    registry = get_active_registry(page)
    before_ids = set(registry.entries.keys())
    before_url = _last_observation_state.get("url", "")
    before_title = _last_observation_state.get("title", "")

    entries = await registry.scan_and_register(max_elements=max_elements)

    after_ids = set(registry.entries.keys())

    # 5. State delta
    delta = compute_state_delta(
        before_url=before_url,
        before_title=before_title,
        before_ids=before_ids,
        after_url=url,
        after_title=title,
        after_ids=after_ids,
    )

    # 6. Optional screenshot
    screenshot_b64 = None
    if include_screenshot:
        try:
            screenshot_bytes = await page.screenshot(type="png")
            # Compress for token efficiency
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(screenshot_bytes))
                img = img.resize((640, 400), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                screenshot_bytes = buf.getvalue()
            except ImportError:
                pass
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            print(f"[Observe] Screenshot failed: {e}")

    # 7. Build fingerprint
    fingerprint_basis = f"{url}:{title}:{registry.size}:{','.join(sorted(after_ids)[:20])}"
    page_fingerprint = hashlib.sha256(fingerprint_basis.encode("utf-8")).hexdigest()[:16]
    observation_id = hashlib.sha256(
        f"{page_fingerprint}:{time.time()}".encode("utf-8")
    ).hexdigest()[:12]

    # Categorize elements for summary
    elements_by_role = {}
    for e in entries:
        role = e.role
        elements_by_role[role] = elements_by_role.get(role, 0) + 1

    # Save current state for next delta comparison
    _last_observation_state = {
        "url": url,
        "title": title,
        "registry_ids": after_ids,
        "fingerprint": page_fingerprint,
    }

    # Build the observation payload
    observation = {
        "observation_id": observation_id,
        "page_fingerprint": page_fingerprint,
        "url": url,
        "title": title,
        "summary": visible_text,
        "element_counts": elements_by_role,
        "total_elements": registry.size,
        "interactive_elements": registry.to_llm_list(max_items=50),
        "state_delta": delta.summary() if delta.significant_change else None,
    }

    if ax_tree_text:
        observation["accessibility_tree"] = ax_tree_text

    if screenshot_b64:
        observation["screenshot_base64"] = screenshot_b64

    debug_path = _debug_dir()
    if debug_path:
        observation_for_disk = dict(observation)
        observation_for_disk.pop("screenshot_base64", None)
        with open(os.path.join(debug_path, "observations.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(observation_for_disk, ensure_ascii=False, default=str) + "\n")

    return observation


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _infer_role(tag: str, input_type: str = "") -> str:
    """Infer semantic role from HTML tag and input type."""
    role_map = {
        "a": "link",
        "button": "button",
        "select": "combobox",
        "textarea": "textbox",
        "input": {
            "text": "textbox",
            "search": "searchbox",
            "email": "textbox",
            "password": "textbox",
            "tel": "textbox",
            "url": "textbox",
            "number": "spinbutton",
            "checkbox": "checkbox",
            "radio": "radio",
            "submit": "button",
            "button": "button",
            "file": "button",
            "range": "slider",
        },
    }

    if tag == "input":
        type_map = role_map.get("input", {})
        return type_map.get(input_type, "textbox") if isinstance(type_map, dict) else "textbox"

    return role_map.get(tag, tag)


async def reset_browser_state():
    """Reset the singleton registry and observation state (e.g., on browser close)."""
    global _active_registry, _last_observation_state
    _active_registry = None
    _last_observation_state = {}
