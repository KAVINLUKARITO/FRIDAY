from __future__ import annotations

import re


def summarize_results(results: list[str]) -> str:
    if not results:
        return ""

    text = "\n".join(results)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1500]
