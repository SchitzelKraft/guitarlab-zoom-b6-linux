"""Live effect on/off on the pedal, as Guitar Lab 7.3 does it.

Recorded from Guitar Lab under Wine and verified on a B6 (firmware 1.00), see
analysis/LIVE-EDIT.md: an effect is switched with a virtual footswitch click, not an
absolute value. Per click the app sends, for the effect's position in the chain,

    64 20 00 64 01 <pos:5>    position
    64 20 00 5A 00 <1:5>      press   (toggles the effect)
    64 20 00 64 01 <pos:5>
    64 20 00 5A 00 <0:5>      release (no change)

A knob is set (also recorded from Guitar Lab) with the same position message followed by

    64 20 00 <module> <knob + 2> <value:5>

where position and module are the effect's entry index in the patch (the second half of a
double-width effect counts). Values are the raw numbers stored in the patch.

Sync mode (50, "PC mode" on the display) is not needed. Without it the pedal sends no
report, so the state is confirmed with an edit-buffer read. The direct form
(module = effect, param 0) must never be used: it froze the B6 three times.
"""
from b6lab import ptcf


class LiveError(Exception):
    """The pedal did not switch the effect as asked (its state is in `.state`)."""

    def __init__(self, message, state=None):
        super().__init__(message)
        self.state = state


def effect_position(patch, slot):
    """Position (and module number) of the effect at entry `slot`: the entry index itself.

    The second half of a double-width effect counts, verified on the B6 with factory patch
    "SVT Drive" (tools/knob_map_check.py): its 3rd effect sits at entry 4 and answers to
    position 4 / module 4, while position 2 switches the 2nd effect."""
    if patch.effects[slot].is_tail:
        raise ValueError(f"entry {slot} is the second half of a double-width effect")
    return slot


def _on_flags(patch):
    return {e.slot: e.on for e in patch.effects if not e.is_tail}


def set_effect_on(dev, slot, on, fx_ids=None):
    """Switch effect entry `slot` of the pedal's current patch on or off; returns the new state.

    `fx_ids` (the effect IDs of the patch shown in the editor) guards against switching an
    effect on a different patch than the one on screen. When the pedal toggles another effect
    than asked, that click is undone and LiveError is raised.
    """
    before = ptcf.parse(dev.read_edit())
    if fx_ids is not None and [e.fx_id for e in before.effects] != list(fx_ids):
        raise LiveError("the pedal is on a different patch than the editor")
    flags = _on_flags(before)
    if slot not in flags:
        raise LiveError(f"effect entry {slot} cannot be switched")
    if flags[slot] == bool(on):
        return flags[slot]
    pos = effect_position(before, slot)
    dev.press_effect(pos)
    after = _on_flags(ptcf.parse(dev.read_edit()))
    changed = [s for s in flags if flags[s] != after.get(s)]
    if changed == [slot]:
        return after[slot]
    if changed:
        dev.press_effect(pos)  # undo the unexpected toggle
        raise LiveError(f"the pedal switched effect {changed} instead of {slot}; undone", flags[slot])
    raise LiveError("the pedal did not switch the effect", after.get(slot))


def send_param(dev, patch, slot, index, value):
    """Set knob `index` of effect entry `slot` in the pedal's edit buffer (no read-back)."""
    pos = effect_position(patch, slot)
    if not patch.effects[slot].editable(index):
        raise LiveError(f"knob {index + 1} of effect entry {slot} is not editable")
    dev.set_param(pos, pos, index, int(value))


def compare_effects(dev, patch):
    """Differences between the pedal's edit buffer and `patch` in effect on/off and knob values.

    Returns a list of readable differences (empty when the pedal matches). Raises LiveError
    when the pedal is on a patch with other effects."""
    pedal = ptcf.parse(dev.read_edit())
    if [e.fx_id for e in pedal.effects] != [e.fx_id for e in patch.effects]:
        raise LiveError("the pedal is on a different patch than the editor")
    out = []
    for mine, theirs in zip(patch.effects, pedal.effects):
        if mine.is_tail:
            continue
        if mine.on != theirs.on:
            out.append(f"effect {mine.slot + 1} is {'on' if theirs.on else 'off'} on the pedal")
        for i, (a, b) in enumerate(zip(mine.params, theirs.params)):
            if a != b:
                out.append(f"effect {mine.slot + 1} knob {i + 1}: {b} on the pedal, {a} here")
    return out
