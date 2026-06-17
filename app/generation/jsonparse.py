"""Best-effort JSON extraction from model output."""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict | list:
    """Parse JSON from model output, tolerating fences and surrounding prose."""
    text = text.strip()
    # 1) Straight parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2) Inside a ```json fence.
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 3) First balanced { } or [ ] span.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No valid JSON found in model output.")
