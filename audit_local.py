from aiworker.llm.ollama_backend import OllamaBackend
import sys
from pathlib import Path

model = OllamaBackend("llama3:8b")


def audit_file(file_path: str):
    path = Path(file_path)

    if not path.exists():
        print("❌ File not found")
        return

    code = path.read_text()

    # ⚠️ LIMIT SIZE (critical for your VPS)
    code = code[:4000]

    prompt = f"""
You are a strict code auditor.

Return ONLY structured output:

[ISSUES]
- ...

[SECURITY]
- ...

[IMPROVEMENTS]
- ...

Code:
{code}
"""

    print("⏳ Running audit...\n")

    try:
        result = model.generate(prompt)

        print("DEBUG → raw result:")
        print(repr(result))  # shows empty or not

        print("\n=== AUDIT RESULT ===\n")

        if not result.strip():
            print("⚠️ Model returned empty output")
        else:
            print(result)

    except Exception as e:
        print(f"❌ ERROR: {e}")


if __name__ == "_main_":
    if len(sys.argv) < 2:
        print("Usage: python audit_local.py <file>")
    else:
        audit_file(sys.argv[1])
