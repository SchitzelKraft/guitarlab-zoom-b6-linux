"""Offline patch search (MCP v3): the pedal (newest full backup plus the server's own writes),
older backups and downloaded .zptc files, matched by slot, name, description, effect and the
real gear an effect is modelled on. No pedal access."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from b6lab import ptcf
from b6lab.device import used_bytes
from b6lab.search import slot_label

SOURCES = ("pedal", "backups", "downloads")
RANKS = ("slot", "name", "description", "effect", "gear")
SKIP_DIRS = {"overwritten", "created"}


@dataclass(frozen=True)
class Entry:
    source: str        # "pedal" | "backups" | "downloads"
    ref: int | str     # slot 1-240, or a .zptc path
    data: bytes


def _parses(data: bytes) -> bool:
    try:
        ptcf.parse(data)
    except Exception:  # noqa: BLE001 - unparseable files are skipped
        return False
    return True


def collect(pedal: list[tuple[int, bytes]], backup_root: Path, downloads: Path,
            sources: set[str]) -> list[Entry]:
    out: list[Entry] = []
    seen: set[bytes] = set()
    if "pedal" in sources:
        for slot, data in pedal:
            out.append(Entry("pedal", slot, data))
    for slot, data in pedal:   # backups only add what is not on the pedal
        seen.add(used_bytes(data))
    if "backups" in sources and Path(backup_root).is_dir():
        for f in sorted(Path(backup_root).glob("*/*.zptc"), reverse=True):  # newest first
            if f.parent.name in SKIP_DIRS:
                continue
            data = f.read_bytes()
            key = used_bytes(data)
            if key in seen or not _parses(data):
                continue
            seen.add(key)
            out.append(Entry("backups", str(f), data))
    if "downloads" in sources and Path(downloads).is_dir():
        for f in sorted(Path(downloads).rglob("*.zptc")):
            if SKIP_DIRS & set(f.relative_to(downloads).parts[:-1]):
                continue
            data = f.read_bytes()
            if _parses(data):
                out.append(Entry("downloads", str(f), data))
    return out


def _rank(entry: Entry, q: str, d: dict, models: dict) -> str | None:
    if isinstance(entry.ref, int):
        digits = q.lstrip("0")
        if q == slot_label(entry.ref - 1).lower() or (q.isdigit() and digits
                                                      and int(digits) == entry.ref):
            return "slot"
    name = (d.get("name") or "").strip().lower()
    if name == "empty" and not any(e.get("effect") for e in d.get("effects", [])):
        return None
    if q in name:
        return "name"
    if q in (d.get("description") or "").lower():
        return "description"
    names = [e["effect"] for e in d.get("effects", []) if e.get("effect")]
    if any(q in n.lower() for n in names):
        return "effect"
    if any(q in str(models.get(n, {}).get("gear", "")).lower() for n in names):
        return "gear"
    return None


def search(entries: list[Entry], query: str, describe: Callable[[bytes], dict],
           models: dict) -> list[dict]:
    q = " ".join(query.lower().split())
    if not q:
        return []
    hits = []
    for i, e in enumerate(entries):
        try:
            d = describe(e.data)
        except Exception:  # noqa: BLE001 - a patch that cannot be described is skipped
            continue
        match = _rank(e, q, d, models)
        if match is None:
            continue
        hits.append(((RANKS.index(match), SOURCES.index(e.source), i),
                     {"source": e.source, "ref": e.ref, "name": d["name"].strip(),
                      "description": d.get("description", ""),
                      "effects": [x["effect"] for x in d["effects"] if x.get("effect")],
                      "match": match}))
    return [h for _, h in sorted(hits, key=lambda x: x[0])]
