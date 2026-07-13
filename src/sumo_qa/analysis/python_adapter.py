# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Python symbol adapter — the reference language path for issue #212.

Uses the standard-library :mod:`ast`, deliberately NOT tree-sitter: within-file
symbol extraction needs no cross-file resolution, so stdlib ``ast`` keeps the
core install lightweight (no mandatory parser dependency — an explicit issue
#212 non-goal). The optional tree-sitter extra (#353) is reserved for the
cross-file ``imports`` graph the impacted-symbol reach consumes, not for this
pass; so this adapter works on every install, extra or not.

``extract_symbols`` returns every function / method / class with its 1-based
inclusive line span (decorators included in the start line); ``innermost_symbol``
and ``symbols_touching_lines`` map changed line numbers to the SMALLEST symbol
containing each — so a one-line edit inside a method attributes to
``Class.method``, not the whole class.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from sumo_qa.analysis.contracts import Symbol, SymbolKind

PYTHON_LANGUAGE = "python"
PYTHON_EXTENSIONS = (".py", ".pyi")


def extract_symbols(src: bytes) -> list[Symbol]:
    """Parse ``src`` and return its functions, methods, and classes.

    Raises :class:`SyntaxError` when ``src`` is not valid Python — the caller
    converts that to a ``parse_error`` fallback rather than crashing the run.
    Symbols are returned in source order (definition line, then qualname).
    """
    tree = ast.parse(src)  # SyntaxError propagates to the caller by contract
    out: list[Symbol] = []
    _walk(tree, prefix=(), inside_class=False, out=out)
    return sorted(out, key=lambda s: (s.start_line, s.qualname))


def _walk(
    node: ast.AST,
    *,
    prefix: tuple[str, ...],
    inside_class: bool,
    out: list[Symbol],
) -> None:
    """Collect defs under ``node``, threading the qualname prefix + class scope.

    A ``def`` directly inside a class body is a ``method``; nested inside a
    function it is a ``function``. Non-def compound statements (a module-level
    ``if TYPE_CHECKING:`` or a class-body ``if``) are descended into WITHOUT
    changing the class scope, so a conditionally-defined method still reads as a
    method and a conditionally-defined free function still reads as a function.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = ".".join((*prefix, child.name))
            kind: SymbolKind = "method" if inside_class else "function"
            out.append(
                Symbol(
                    qualname=qualname,
                    kind=kind,
                    start_line=_start_line(child),
                    end_line=_end_line(child),
                )
            )
            # A function body opens a fresh non-class scope: a def inside is a
            # plain function, never a method.
            _walk(child, prefix=(*prefix, child.name), inside_class=False, out=out)
        elif isinstance(child, ast.ClassDef):
            qualname = ".".join((*prefix, child.name))
            out.append(
                Symbol(
                    qualname=qualname,
                    kind="class",
                    start_line=_start_line(child),
                    end_line=_end_line(child),
                )
            )
            _walk(child, prefix=(*prefix, child.name), inside_class=True, out=out)
        else:
            _walk(child, prefix=prefix, inside_class=inside_class, out=out)


def _start_line(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
    """The first line the symbol occupies — its earliest decorator if any,
    else the ``def``/``class`` keyword line. A change to a decorator counts as a
    change to the symbol, so the span must reach up over the decorators."""
    lines = [node.lineno]
    lines.extend(dec.lineno for dec in node.decorator_list)
    return min(lines)


def _end_line(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
    end = node.end_lineno
    # ast populates end_lineno for every node of a parsed module; the guard
    # narrows the Optional for type-checkers and can never fire on parsed input.
    assert end is not None
    return end


def innermost_symbol(symbols: Iterable[Symbol], line: int) -> Symbol | None:
    """The smallest-span symbol whose range contains ``line``, or ``None``.

    Smallest span wins so a line inside a method attributes to the method, not
    its enclosing class. ``None`` when ``line`` falls outside every symbol (e.g.
    a module-level statement between defs)."""
    best: Symbol | None = None
    for sym in symbols:
        if sym.start_line <= line <= sym.end_line:
            if best is None or (sym.end_line - sym.start_line) < (best.end_line - best.start_line):
                best = sym
    return best


def symbols_touching_lines(symbols: list[Symbol], changed_lines: Iterable[int]) -> list[Symbol]:
    """The distinct innermost symbols touched by ``changed_lines``.

    Each changed line attributes to its innermost containing symbol; the union
    is returned once each, ordered by ``(start_line, qualname)``. Lines outside
    every symbol contribute nothing."""
    chosen: dict[tuple[str, int, int], Symbol] = {}
    for line in changed_lines:
        sym = innermost_symbol(symbols, line)
        if sym is not None:
            chosen[(sym.qualname, sym.start_line, sym.end_line)] = sym
    return sorted(chosen.values(), key=lambda s: (s.start_line, s.qualname))


class PythonSymbolAdapter:
    """The registry-facing adapter for Python (issue #212 reference language).

    Thin object wrapper over the module functions so the registry can dispatch a
    file's language/extension to a uniform ``extract_symbols`` /
    ``symbols_touching_lines`` pair.
    """

    # Explicitly annotated so the class structurally satisfies the
    # ``registry.LanguageAdapter`` Protocol (whose ``extensions`` is
    # ``tuple[str, ...]``, not the inferred fixed-length ``tuple[str, str]``).
    language: str = PYTHON_LANGUAGE
    extensions: tuple[str, ...] = PYTHON_EXTENSIONS

    def extract_symbols(self, src: bytes) -> list[Symbol]:
        return extract_symbols(src)

    def symbols_touching_lines(
        self, symbols: list[Symbol], changed_lines: Iterable[int]
    ) -> list[Symbol]:
        return symbols_touching_lines(symbols, changed_lines)
