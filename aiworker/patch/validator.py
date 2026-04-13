from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

try:
    from aiworker.safety.validator import *  # type: ignore[F401,F403]
except Exception:
    pass

_validator_path = Path(__file__).resolve().parents[1] / "safety" / "validator.py"
_spec = spec_from_file_location("_aiworker_safety_validator_compat", _validator_path)
if _spec is None or _spec.loader is None:
    raise ImportError("Unable to load aiworker.safety.validator")
_module = module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

PatchValidationResult = _module.PatchValidationResult
validate = _module.validate
_check_diff_format = _module._check_diff_format
_extract_added_lines = _module._extract_added_lines
_check_forbidden_patterns = _module._check_forbidden_patterns
_check_file_deletion = _module._check_file_deletion
_check_path_traversal = _module._check_path_traversal
