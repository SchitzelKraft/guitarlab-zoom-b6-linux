#!/usr/bin/env python3
"""Regenerate docs/zoom/B6-EFFECT-MODELS.md from b6lab/data/effect_models.json."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from b6lab.effect_models import load_models, render_doc  # noqa: E402

out = ROOT / "docs" / "zoom" / "B6-EFFECT-MODELS.md"
out.write_text(render_doc(load_models()), encoding="utf-8")
print(f"wrote {out}")
