from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_verifier_path = Path(__file__).resolve().parents[1] / "safety" / "sandbox_verifier.py"
_spec = spec_from_file_location("_aiworker_safety_sandbox_verifier_compat", _verifier_path)
if _spec is None or _spec.loader is None:
    raise ImportError("Unable to load aiworker.safety.sandbox_verifier")
_module = module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

VerificationResult = _module.VerificationResult
verify = _module.verify
