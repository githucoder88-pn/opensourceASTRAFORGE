"""Resolve `python` to the interpreter AstraForge itself is running under.

Rationale (learned the hard way while building the flagship demo): a plan that
says ``python -m pytest`` will, on a machine with a virtualenv, silently invoke
some *other* system interpreter that has no pytest installed. That exits with
code 1 — indistinguishable from "the tests failed" — and turns a verification
step into a false positive.

So both the shell tool and the command verifier rewrite a leading ``python`` /
``python3`` to :data:`sys.executable`. The run then uses the same interpreter,
and the same installed packages, that the engine does.
"""

from __future__ import annotations

import sys

_PYTHON_NAMES = {"python", "python3", "py"}


def resolve_interpreter(argv: list[str]) -> list[str]:
    """Return ``argv`` with a leading generic python name replaced."""
    if argv and argv[0] in _PYTHON_NAMES:
        return [sys.executable, *argv[1:]]
    return argv
