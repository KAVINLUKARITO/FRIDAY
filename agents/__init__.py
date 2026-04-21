from pathlib import Path

_here = Path(__file__).resolve().parent
_legacy = _here.parent / "aiworker" / "agents"
__path__ = [str(_here)]
if _legacy.exists():
    __path__.append(str(_legacy))
