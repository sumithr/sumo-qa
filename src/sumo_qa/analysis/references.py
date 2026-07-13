# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Shared stdlib-ast name-reference collection for the analysis adapters (#212).

Internal helper: collects the name references in a Python source file ONCE — the
referenced name, whether it is a call, its line, and the enclosing ``def`` — so
the changed-symbol -> likely-test pass (``test_mapping``) and the impacted-symbol
pass (``impact``) share one consistent view of "what this file names" instead of
each re-walking the tree with subtly different rules.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    """One name reference in a source file.

    ``name`` is the referenced identifier (a bare ``Name`` id or the trailing
    ``attr`` of an attribute access); ``called`` is true when the reference is
    the callee of a ``Call``; ``lineno`` is its 1-based line; ``enclosing`` is
    the name of the nearest enclosing ``def`` (``None`` at module level).
    """

    name: str
    called: bool
    lineno: int
    enclosing: str | None


def collect_references(src: bytes) -> list[Reference] | None:
    """The name references in ``src``, or ``None`` if it does not parse.

    ``None`` (not an exception) is the "unparseable" signal so a caller iterating
    many files skips a broken one cleanly instead of aborting the whole pass.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    collector = _Collector()
    collector.visit(tree)
    return collector.refs


def _callee_name(func: ast.expr) -> str | None:
    """The simple name of a call's callee, or ``None`` for a non-name callee.

    ``foo()`` -> ``foo``; ``obj.foo()`` -> ``foo``; ``arr[0]()`` -> ``None``
    (a subscript/other expression carries no plain name to match a symbol on).
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class _Collector(ast.NodeVisitor):
    """Walks a module, recording every name reference with its call flag,
    line, and enclosing ``def``.

    A call's callee is recorded once as ``called=True`` from ``visit_Call``; the
    generic descent then also visits the callee ``Name``/``Attribute`` and
    records it as ``called=False``. Both survive — the consumer treats a name as
    "called" when ANY of its references is a call, so the duplicate never
    downgrades a genuine call.
    """

    def __init__(self) -> None:
        self.refs: list[Reference] = []
        self._func_stack: list[str] = []

    def _enclosing(self) -> str | None:
        return self._func_stack[-1] if self._func_stack else None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = _callee_name(node.func)
        if name is not None:
            self.refs.append(
                Reference(name=name, called=True, lineno=node.lineno, enclosing=self._enclosing())
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.refs.append(
            Reference(name=node.id, called=False, lineno=node.lineno, enclosing=self._enclosing())
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.refs.append(
            Reference(name=node.attr, called=False, lineno=node.lineno, enclosing=self._enclosing())
        )
        self.generic_visit(node)
