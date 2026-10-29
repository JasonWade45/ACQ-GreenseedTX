"""Route table self-check.

Two failure modes are invisible in normal use but break the interface silently:

* A path is registered twice for the same method. Starlette serves the *first*
  match, so the second handler is dead code that looks alive in the source.
* A static path such as ``/api/backups/config`` is declared *after* a
  path-parameter route such as ``/api/backups/{name}``. The parameter route
  matches first and the static one is unreachable.

Both are detected here and asserted by ``backend/tests/test_routes.py`` so a new
route cannot reintroduce them.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

PARAM = re.compile(r"\{([^{}]+)\}")


def _method_set(route) -> set[str]:
    methods = getattr(route, "methods", None) or set()
    return {m.upper() for m in methods if m.upper() not in {"HEAD", "OPTIONS"}}


def _concrete_pattern(path: str) -> re.Pattern[str]:
    """Compile a route path so it can be tested against a literal path."""
    parts = re.split(r"(\{[^{}]+\})", path)
    compiled = ""
    for part in parts:
        if PARAM.fullmatch(part):
            compiled += r"[^/]+"
        else:
            compiled += re.escape(part)
    return re.compile("^" + compiled + "$")


def _is_static(path: str) -> bool:
    return "{" not in path


def duplicate_routes(routes: Iterable) -> list[tuple[str, str]]:
    """Return every (path, method) registered more than once."""
    counter = Counter()
    for route in routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        for method in _method_set(route):
            counter[(path, method)] += 1
    return sorted(key for key, count in counter.items() if count > 1)


def shadowed_routes(routes: Iterable) -> list[dict]:
    """Return static paths that an *earlier* parameter route already matches."""
    ordered = [r for r in routes if getattr(r, "path", None)]
    problems = []
    for index, route in enumerate(ordered):
        path = route.path
        if not _is_static(path):
            continue
        for earlier in ordered[:index]:
            earlier_path = earlier.path
            if _is_static(earlier_path):
                continue
            if not _method_set(earlier) & _method_set(route):
                continue
            if _concrete_pattern(earlier_path).match(path):
                problems.append(
                    {
                        "path": path,
                        "methods": sorted(_method_set(route)),
                        "shadowed_by": earlier_path,
                        "shadowing_methods": sorted(_method_set(earlier)),
                        "handler": getattr(route, "name", ""),
                    }
                )
                break
    return problems


def route_problems(app) -> dict:
    """Summarise both problems for the given FastAPI/Starlette app."""
    routes = list(app.routes)
    info = defaultdict(list)
    for route in routes:
        for method in _method_set(route):
            info[route.path].append(method)
    return {
        "duplicates": duplicate_routes(routes),
        "shadowed": shadowed_routes(routes),
        "route_count": len(routes),
    }


def assert_clean(app) -> None:
    problems = route_problems(app)
    if problems["duplicates"] or problems["shadowed"]:
        raise AssertionError(f"Route table problems: {problems}")
