"""Convert knob values between raw pedal integers and display units."""
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, localcontext

from b6lab.effects import ParamInfo


class KnobError(ValueError):
    """A knob value that is not valid for the parameter."""


def _has_scale(param: ParamInfo) -> bool:
    return param.display_min is not None and param.display_step is not None


def display_value(param: ParamInfo, raw: int):
    """Label, display number (int when precision is 0), or {"raw": raw}."""
    labels = param.display_labels
    if labels is not None and 0 <= raw < len(labels):
        return labels[raw]
    if not _has_scale(param) or (param.display_through is not None
                                  and raw > param.display_through):
        return {"raw": raw}
    result = Decimal(param.display_min) + Decimal(param.display_step) * raw
    result = round(result, param.display_precision)
    if param.display_precision == 0:
        return int(result)
    return float(result)


def _valid_description(param: ParamInfo) -> str:
    if param.display_labels is not None:
        return "valid values: " + ", ".join(param.display_labels)
    if _has_scale(param) and param.display_through is not None:
        lo = Decimal(param.display_min)
        hi = lo + Decimal(param.display_step) * param.display_through
        return (f"valid range: {lo:.{param.display_precision}f} to "
                f"{hi:.{param.display_precision}f}, or a tempo-synced note value as "
                f'{{"raw": {param.display_through + 1}..{param.raw_max}}}')
    if _has_scale(param):
        lo = Decimal(param.display_min)
        hi = lo + Decimal(param.display_step) * param.raw_max if param.raw_max is not None else None
        p = param.display_precision
        top = f"{hi:+.{p}f}" if hi is not None else "..."
        return f"valid range: {lo:+.{p}f} .. {top} step {Decimal(param.display_step):.{p}f}"
    if param.raw_max is not None:
        return f'valid: {{"raw": 0..{param.raw_max}}}'
    return 'valid: {"raw": n}'


def _fail(param: ParamInfo, value) -> KnobError:
    return KnobError(f"{param.name}: cannot use {value!r}; {_valid_description(param)}")


def _check_raw(param: ParamInfo, raw: int) -> int:
    if raw < 0 or (param.raw_max is not None and raw > param.raw_max):
        raise _fail(param, raw)
    return raw


def raw_value(param: ParamInfo, value) -> int:
    """Raw pedal integer for a display number, number string, label or {"raw": n}."""
    if isinstance(value, dict):
        n = value.get("raw")
        if not isinstance(n, int) or isinstance(n, bool):
            raise _fail(param, value)
        return _check_raw(param, n)
    if isinstance(value, bool):
        raise _fail(param, value)
    if isinstance(value, str):
        text = value.strip()
        for i, label in enumerate(param.display_labels or []):
            if label.lower() == text.lower():
                return _check_raw(param, i)
        number_text = text
    elif isinstance(value, (int, float)):
        number_text = repr(value)
    else:
        raise _fail(param, value)
    if not _has_scale(param):
        raise _fail(param, value)
    try:
        number = Decimal(number_text)
    except InvalidOperation:
        raise _fail(param, value) from None
    if not number.is_finite():
        raise _fail(param, value)
    lo = Decimal(param.display_min)
    step = Decimal(param.display_step)
    top = param.display_through if param.display_through is not None else param.raw_max
    if number < lo or (top is not None and number > lo + step * top):
        raise _fail(param, value)
    # Exact grid check: any rounding (Inexact) means the value is not on the grid.
    try:
        with localcontext() as ctx:
            ctx.prec = 200
            ctx.traps[Inexact] = True
            steps, rem = divmod(number - lo, step)
    except DecimalException:
        raise _fail(param, value) from None
    if rem != 0:
        raise _fail(param, value)
    return _check_raw(param, int(steps))
