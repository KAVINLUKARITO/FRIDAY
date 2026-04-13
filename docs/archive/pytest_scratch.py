# ARCHIVED  this file was incorrectly named pytest.py
# at the repo root, shadowing the pytest package.
# Moved here for reference only. Not a source module.

"""Minimal pytest compatibility shim for unittest-based environments.

This repository's requested validation command uses ``python -m unittest``.
Some test modules import a narrow subset of pytest helpers at import time.
This shim provides just enough surface for those imports to succeed without
pulling a network dependency into the active interpreter.
"""

from __future__ import annotations

import re
from typing import Any, Callable, TypeVar


_F = TypeVar("_F", bound=Callable[..., Any])


class RaisesContext:
    def __init__(self, expected_exception: type[BaseException], match: str | None = None) -> None:
        self.expected_exception = expected_exception
        self.match = match
        self.value: BaseException | None = None

    def __enter__(self) -> "RaisesContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del tb
        if exc_type is None:
            raise AssertionError(
                f"Did not raise {self.expected_exception.__name__}"
            )
        if not issubclass(exc_type, self.expected_exception):
            return False
        self.value = exc
        if self.match is not None and not re.search(self.match, str(exc)):
            raise AssertionError(
                f"Exception message {str(exc)!r} does not match {self.match!r}"
            )
        return True


def raises(expected_exception: type[BaseException], match: str | None = None) -> RaisesContext:
    return RaisesContext(expected_exception, match=match)


def fixture(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
    del args, kwargs

    def decorator(func: _F) -> _F:
        return func

    return decorator
