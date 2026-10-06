"""Static checks for optimistic patterns in backtest code.

This reads someone else's script, not data, so everything here is a
heuristic built on variable names. It is tuned to catch the patterns I keep
seeing (stop fills that ignore the open, target-first exit checks, trailing
off the bar's own high) and to stay quiet on the obvious correct versions.
Silence a line with `# noqa: HB001` (or a bare `# noqa`).
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

RULES = {
    "HB001": "exit priced at the stop without checking the bar open; a gap through the stop fills at the open",
    "HB002": "target checked before stop on the same bar; with both inside one bar the stop may have traded first",
    "HB003": "trailing stop moved from this bar's high/low before this bar's stop check",
    "HB004": "P&L computed, but no commission, fee, slippage or cost appears anywhere in the file",
    "HB005": "shift with a negative period reads future rows",
}

STOP = {"stop", "stops", "sl", "stoploss", "stoplevel", "stopprice", "trail", "trailing", "tsl"}
TARGET = {"target", "targets", "tgt", "tp", "takeprofit"}
HIGH_LOW = {"high", "low", "highs", "lows", "hi", "lo"}
OPEN = {"open", "opens"}
EXIT = {"exit", "exits", "fill", "fills", "filled", "sell", "cover"}
PNL = {"pnl", "profit", "profits", "returns", "equity", "pl"}
COST = {
    "commission", "commissions", "fee", "fees", "cost", "costs", "slippage", "slip",
    "brokerage", "stt", "tax", "taxes", "charges", "spread",
}
ENTRY = {"entry", "entries", "buy", "bought"}
INDEXERS = {"iloc", "loc", "at", "iat", "values"}

NOQA = re.compile(r"#\s*noqa(?::\s*(?P<codes>[A-Z0-9,\s]+))?", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    col: int
    rule: str

    @property
    def message(self) -> str:
        return RULES[self.rule]

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.rule} {self.message}"


def _tokens(name: str) -> set[str]:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
    return {t for t in re.split(r"[^a-z0-9]+", snake) if t}


def _ident(node: ast.AST) -> str | None:
    """The name a reader would say for this expression: `bar['high']` -> 'high'."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        if node.attr in INDEXERS:
            return _ident(node.value)
        return node.attr
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
        return _ident(node.value)
    return None


def _is(node: ast.AST, vocab: set[str], singles: Iterable[str] = ()) -> bool:
    name = _ident(node)
    if name is None:
        return False
    return name in singles or bool(_tokens(name) & vocab)


def _is_stop(node):
    return _is(node, STOP)


def _is_target(node):
    name = _ident(node)
    return name is not None and (_is(node, TARGET) or {"take", "profit"} <= _tokens(name))


def _is_high_low(node):
    return _is(node, HIGH_LOW, singles=("h", "l"))


def _refs(node: ast.AST, pred) -> bool:
    return any(pred(n) for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Attribute, ast.Subscript)))


def _compares(test: ast.AST, level_pred) -> bool:
    """True if `test` compares a level (stop or target) against a bar high/low."""
    for node in ast.walk(test):
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if any(_refs(s, level_pred) for s in sides) and any(_refs(s, _is_high_low) for s in sides):
                return True
    return False


def _exits(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Break, ast.Continue, ast.Return)):
                return True
            if isinstance(node, ast.Assign) and any(_is(t, EXIT) for t in node.targets):
                return True
    return False


class _Checker(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.findings: list[Finding] = []
        self._elifs: set[int] = set()

    def add(self, node: ast.AST, rule: str) -> None:
        self.findings.append(Finding(self.path, node.lineno, node.col_offset + 1, rule))

    # HB001

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_assignment(target, node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._check_assignment(node.target, node.value, node)
        self.generic_visit(node)

    def _check_assignment(self, target: ast.AST, value: ast.AST, stmt: ast.stmt) -> None:
        if _is(target, EXIT) and _is_stop(value) and not _is_stop(target):
            self.add(stmt, "HB001")
        elif _is(target, PNL) and self._stop_minus_entry(value) and not _refs(stmt, lambda n: _is(n, OPEN, ("o",))):
            self.add(stmt, "HB001")

    @staticmethod
    def _stop_minus_entry(value: ast.AST) -> bool:
        for node in ast.walk(value):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                pair = (node.left, node.right)
                if any(_is_stop(x) for x in pair) and any(_is(x, ENTRY) for x in pair):
                    return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        exiting = _is(node.func, EXIT | {"close"})
        for kw in node.keywords:
            if kw.arg is None:
                continue
            kw_toks = _tokens(kw.arg)
            if (kw_toks & EXIT or (exiting and kw.arg == "price")) and _is_stop(kw.value) and not kw_toks & STOP:
                self.add(kw.value, "HB001")
        if _ident(node.func) == "shift" and self._negative_shift(node):
            self.add(node, "HB005")
        self.generic_visit(node)

    @staticmethod
    def _negative_shift(node: ast.Call) -> bool:
        args = list(node.args[:1]) + [k.value for k in node.keywords if k.arg == "periods"]
        for a in args:
            if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub) and isinstance(a.operand, ast.Constant):
                return True
            if isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and a.value < 0:
                return True
        return False

    # HB002

    def visit_If(self, node: ast.If) -> None:
        if id(node) not in self._elifs:
            self._check_chain(node)
        self.generic_visit(node)

    def _check_chain(self, node: ast.If) -> None:
        tests = [node.test]
        bodies = [node.body]
        cur = node
        while len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            cur = cur.orelse[0]
            self._elifs.add(id(cur))
            tests.append(cur.test)
            bodies.append(cur.body)
        self._check_order(tests, bodies)

    def _check_order(self, tests, bodies) -> None:
        for i, (test, body) in enumerate(zip(tests, bodies)):
            has_stop, has_target = _compares(test, _is_stop), _compares(test, _is_target)
            if has_stop and has_target:
                if self._takes_target(body):
                    self.add(test, "HB002")
                return
            if has_stop:
                return
            if has_target:
                if any(_compares(t, _is_stop) for t in tests[i + 1 :]):
                    self.add(test, "HB002")
                return

    @staticmethod
    def _takes_target(body: list[ast.stmt]) -> bool:
        # A collision branch that settles for the target.
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Assign) and any(_is(t, EXIT) for t in node.targets):
                    return _is_target(node.value)
        return False

    # Rules that depend on statement order inside one block.

    def check_blocks(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                stmts = getattr(node, field, None)
                if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                    self._sibling_ifs(stmts)
                    self._trail_before_check(stmts)

    def _sibling_ifs(self, stmts: list[ast.stmt]) -> None:
        # if high >= tp: ... break
        # if low <= sl: ... break
        ifs = [s for s in stmts if isinstance(s, ast.If)]
        for i, first in enumerate(ifs):
            if _compares(first.test, _is_target) and not _compares(first.test, _is_stop) and _exits(first.body):
                if any(_compares(later.test, _is_stop) for later in ifs[i + 1 :]):
                    self.add(first.test, "HB002")

    def _trail_before_check(self, stmts: list[ast.stmt]) -> None:
        # Moving the trail from this bar's high after the bar's stop check is
        # fine (it applies from the next bar). Moving it before is the bug.
        for i, stmt in enumerate(stmts):
            if _is_ratchet(stmt) and any(_compares(later, _is_stop) for later in stmts[i + 1 :]):
                self.add(stmt, "HB003")


def _closed_bar(value: ast.AST) -> bool:
    # highs[i - 1] or df.high.shift(1) is a finished bar.
    for node in ast.walk(value):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.BinOp) and isinstance(node.slice.op, ast.Sub):
            return True
        if isinstance(node, ast.Call) and _ident(node.func) in ("shift", "rolling"):
            return True
    return False


def _is_ratchet(stmt: ast.stmt) -> bool:
    """stop = max(stop, high - k) or stop += ..., pulled by the current bar's high/low."""
    if isinstance(stmt, ast.AugAssign):
        return _is_stop(stmt.target) and _refs(stmt.value, _is_high_low) and not _closed_bar(stmt.value)
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1 or not _is_stop(stmt.targets[0]):
        return False
    name = _ident(stmt.targets[0])
    for call in ast.walk(stmt.value):
        if isinstance(call, ast.Call) and _ident(call.func) in ("max", "min"):
            if any(_ident(a) == name for a in call.args):
                others = [a for a in call.args if _ident(a) != name]
                if any(_refs(a, _is_high_low) for a in others) and not _closed_bar(call):
                    return True
    return False


def _check_costs(tree: ast.AST, path: str) -> list[Finding]:
    first_pnl = None
    for node in ast.walk(tree):
        names = []
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
            names.append(_ident(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.append(node.value)
        elif isinstance(node, ast.keyword) and node.arg:
            names.append(node.arg)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        for name in filter(None, names):
            if _tokens(name) & COST:
                return []
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_is(t, PNL) for t in targets):
                if first_pnl is None or node.lineno < first_pnl.lineno:
                    first_pnl = node
    if first_pnl is None:
        return []
    return [Finding(path, first_pnl.lineno, first_pnl.col_offset + 1, "HB004")]


def _suppressed(finding: Finding, lines: list[str]) -> bool:
    if not 0 < finding.line <= len(lines):
        return False
    m = NOQA.search(lines[finding.line - 1])
    if not m:
        return False
    codes = m.group("codes")
    return codes is None or finding.rule in {c.strip().upper() for c in codes.split(",")}


def lint_source(source: str, path: str = "<string>") -> list[Finding]:
    tree = ast.parse(source, filename=path)
    checker = _Checker(path)
    checker.visit(tree)
    checker.check_blocks(tree)
    found = set(checker.findings) | set(_check_costs(tree, path))
    lines = source.splitlines()
    return sorted((f for f in found if not _suppressed(f, lines)), key=lambda f: (f.line, f.col, f.rule))


def iter_python_files(paths: Iterable[str | Path]) -> Iterator[Path]:
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*.py")):
                if not any(part.startswith(".") or part in ("venv", "__pycache__") for part in f.parts):
                    yield f
        else:
            yield p


def main(paths: list[str], out=None) -> int:
    out = out or sys.stdout
    status = 0
    for path in iter_python_files(paths):
        try:
            source = path.read_text(encoding="utf-8")
            findings = lint_source(source, str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"{path}: could not lint: {exc}", file=sys.stderr)
            status = 2
            continue
        for f in findings:
            print(f, file=out)
        if findings and status == 0:
            status = 1
    return status
