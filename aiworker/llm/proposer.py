import requests
import os
import uuid

from aiworker.monitor.telemetry import telemetry

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "deepseek-coder:6.7b"


def generate_patch_from_goal(goal: str) -> str:
    prompt = f"""
You are a coding assistant.
Return ONLY a valid unified diff.
Do not explain.
Do not include markdown.
Do not include text before or after the diff.

Goal:
{goal}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
    except Exception as exc:
        telemetry.record_error(f"LLM request failed: {exc}")
        raise

    data = response.json()
    output = data.get("response", "").strip()
    telemetry.record_llm_call(
        prompt_tokens=max(1, len(prompt) // 4),
        completion_tokens=max(1, len(output) // 4),
        model=MODEL,
    )

    if not output.startswith("diff --git"):
        raise ValueError("LLM did not return valid unified diff.")

    os.makedirs("workspace", exist_ok=True)
    patch_id = uuid.uuid4().hex[:8]
    path = f"workspace/llm_{patch_id}.diff"

    with open(path, "w") as f:
        f.write(output)

    return path
