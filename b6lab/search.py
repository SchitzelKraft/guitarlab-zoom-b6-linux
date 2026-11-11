"""Patch search by number, name or effect name (shared spec: .superpowers/search/spec.md).

Ranks: 1 number (exact first, then a digits-only query as a prefix of the number), 2 name
(starts with first, then contains), 3 effect name ("uses <effect name>"). Within a rank and
sub-order: slot order. Each patch appears once, at its best rank."""
from dataclasses import dataclass

from b6lab import effects, ptcf


@dataclass(frozen=True)
class Hit:
    slot: int
    label: str
    name: str
    rank: int
    reason: str = ""


def slot_label(slot):
    """The B6's patch number: A-001 .. Z-104, AA-105 .. AZ-208, BA-209 .. BH-240."""
    bank = slot // 4
    letters = chr(65 + bank) if bank < 26 else chr(64 + bank // 26) + chr(65 + bank % 26)
    return f"{letters}-{slot + 1:03d}"


def _norm(text):
    return "".join(c for c in text.lower() if c not in " -")


def search(slots, query, lookup=effects.lookup):
    q = _norm(query)
    if not q:
        return []
    digits = q.isdigit()
    if digits:
        q = q.lstrip("0")   # "01" behaves like "1"; "0" / "00" match nothing
        if not q:
            return []
    hits = []
    for slot, data in enumerate(slots):
        label = slot_label(slot)
        try:
            patch = ptcf.parse(data)
            name, fx = patch.name, patch.effects
        except Exception:
            name, fx = "?", []
        key = None
        reason = ""
        if q == _norm(label) or (digits and int(q) == slot + 1):
            key = (1, 0)
        elif digits and str(slot + 1).startswith(q):
            key = (1, 1)
        elif _norm(name.strip()) != "empty":
            n = _norm(name)
            if n.startswith(q):
                key = (2, 0)
            elif q in n:
                key = (2, 1)
            else:
                for e in fx:
                    info = None if e.is_tail else lookup(e.fx_id)
                    if info is not None and q in _norm(info.name):
                        key, reason = (3, 0), f"uses {info.name}"
                        break
        if key is not None:
            hits.append((key, slot, Hit(slot, label, name.strip(), key[0], reason)))
    hits.sort(key=lambda t: (t[0], t[1]))
    return [h for _k, _s, h in hits]
