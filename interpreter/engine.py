from __future__ import annotations

from typing import Any


def interpret(raw_output: Any) -> dict[str, Any]:
    try:
        if raw_output is None or raw_output == "" or raw_output == [] or raw_output == {}:
            return {"summary": "empty output", "type": "empty", "key_info": []}

        if isinstance(raw_output, str):
            summary = raw_output[:300] + ("..." if len(raw_output) > 300 else "")
            summary = summary[:300]
            return {"summary": summary, "type": "text", "key_info": []}

        if isinstance(raw_output, list):
            count = len(raw_output)
            preview = [str(item)[:80] for item in raw_output[:3]]
            summary = f"List of {count} items. Preview: {preview}"
            summary = summary[:300]
            return {"summary": summary, "type": "list", "key_info": preview}

        if isinstance(raw_output, dict):
            keys = [str(key) for key in raw_output.keys()]
            summary = f"Dict with keys: {keys}"
            summary = summary[:300]
            return {"summary": summary, "type": "dict", "key_info": keys}

        summary = str(raw_output)[:300]
        return {"summary": summary, "type": "text", "key_info": []}
    except Exception:
        return {"summary": "interpretation error", "type": "error", "key_info": []}
