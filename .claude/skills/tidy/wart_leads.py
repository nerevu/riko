"""
Find candidate API warts: redundant channels, dead knobs, mode flags, repeated lookups.

Inputs: riko/ source tree (cwd = repo root). Outputs: lead sections on stdout.
Origin: 2026-11-09 audit for "warts like the unneeded describe modes"; promoted to a
tidy helper 2026-11-11. Leads need manual pruning: it misses values passed through
partial, repeat(...), and **kwargs forwarding. Section G folded in 2026-11-11 from the
closure-lookup audit draft.
"""

import ast
import re
from collections import Counter
from pathlib import Path

ROOT = Path("riko")
SKIP = {"_configs.py", "_names.py", "_module_ids.py", "_user_agents.py"}
files = [p for p in ROOT.rglob("*.py") if p.name not in SKIP]
src = {p: p.read_text() for p in files}
trees = {p: ast.parse(s) for p, s in src.items()}
tests_text = "\n".join(p.read_text() for p in Path("tests").rglob("*.py"))
all_text = "\n".join(src.values())


def words(text: str, name: str) -> int:
    return len(re.findall(rf"\b{re.escape(name)}\b", text))


def section(title: str) -> None:
    print(f"\n## {title}")


# A. keyword knobs (bool / None default / enum default) never passed by name in riko/
section("A. keyword knobs never passed by keyword inside riko/ (excl. own def)")
kwpass = Counter()
for t in trees.values():
    for node in ast.walk(t):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg:
                    kwpass[kw.arg] += 1
knobs = []
for p, t in trees.items():
    for node in ast.walk(t):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_") and not node.name.startswith("__init"):
            continue
        a = node.args
        positional = a.posonlyargs + a.args
        defaulted = positional[len(positional) - len(a.defaults) :]
        pos_defaults = list(zip(defaulted, a.defaults, strict=True))
        kw_pairs = zip(a.kwonlyargs, a.kw_defaults, strict=True)
        kw_defaults = [(k, d) for k, d in kw_pairs if d]
        for arg, d in pos_defaults + kw_defaults:
            if arg.arg in {"self", "cls"}:
                continue
            is_flag = isinstance(d, ast.Constant) and isinstance(d.value, bool)
            is_enum = isinstance(d, ast.Attribute) and d.attr.isupper()
            if (is_flag or is_enum) and kwpass[arg.arg] == 0:
                tests_n = len(re.findall(rf"\b{arg.arg}\s*=", tests_text))
                knobs.append(
                    f"{p}:{node.lineno} {node.name}({arg.arg}=...) tests_kw={tests_n}"
                )
print("\n".join(sorted(knobs)) or "(none)")

# B. overloads keyed on Literal flags (return type switched by an argument)
section("B. @overload families keyed on Literal[...] arguments")
for p, t in trees.items():
    seen = set()
    for node in ast.walk(t):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            ast.unparse(d).endswith("overload") for d in node.decorator_list
        ):
            sig = ast.unparse(node.args)
            if "Literal[" in sig and node.name not in seen:
                seen.add(node.name)
                lits = sorted(set(re.findall(r"(\w+): Literal\[([^\]]+)\]", sig)))
                print(f"{p}:{node.lineno} {node.name} {lits}")

# C. trivial delegates: a public def/property whose body returns one attr or call
section("C. one-line public delegates (return <name>.<attr> / return f(<args>))")
for p, t in trees.items():
    for node in ast.walk(t):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        body = [
            b
            for b in node.body
            if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))
        ]
        if (
            len(body) == 1
            and isinstance(body[0], ast.Return)
            and body[0].value is not None
        ):
            v = body[0].value
            text = ast.unparse(v)
            if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Attribute):
                print(f"{p}:{node.lineno} {node.name} -> {text}")
            elif isinstance(v, ast.Call) and isinstance(
                v.func, (ast.Name, ast.Attribute)
            ):
                params = {a.arg for a in node.args.args + node.args.kwonlyargs} - {
                    "self",
                    "cls",
                }
                argn = {ast.unparse(a) for a in v.args} | {
                    ast.unparse(k.value) for k in v.keywords
                }
                if params and params <= argn and len(text) < 90:
                    print(f"{p}:{node.lineno} {node.name} -> {text}")

# D. enum members referenced only in their definition (+tests/docs)
section("D. enum members with no reference in riko/ outside the enum body")
for p, t in trees.items():
    for node in ast.walk(t):
        if isinstance(node, ast.ClassDef) and any(
            ast.unparse(b).endswith(("Enum", "StrEnum")) for b in node.bases
        ):
            for st in node.body:
                if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
                    m = st.targets[0].id
                    uses = len(re.findall(rf"\b{node.name}\.{m}\b", all_text))
                    if uses == 0:
                        tn = len(re.findall(rf"\b{node.name}\.{m}\b", tests_text))
                        print(f"{p}:{st.lineno} {node.name}.{m} tests={tn}")

# E. attrs/NamedTuple/TypedDict fields never read as .field in riko/ outside their class
section("E. record fields with no attribute read in riko/ (word '.field')")
for p, t in trees.items():
    for node in ast.walk(t):
        if not isinstance(node, ast.ClassDef):
            continue
        decos = " ".join(ast.unparse(d) for d in node.decorator_list)
        bases = " ".join(ast.unparse(b) for b in node.bases)
        if not ("define" in decos or "frozen" in decos or "NamedTuple" in bases):
            continue
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                f = st.target.id
                if f.startswith("_") or "ClassVar" in ast.unparse(st.annotation):
                    continue
                reads = len(re.findall(rf"\.{f}\b", all_text))
                if reads == 0:
                    tn = len(re.findall(rf"\.{f}\b", tests_text))
                    print(f"{p}:{st.lineno} {node.name}.{f} tests={tn}")

# F. 'not yet' / inert / reserved / no-op markers in docstrings
section("F. docstring markers of inert behavior")
pat = re.compile(
    r"(no run acts|not (yet )?(used|honou?red|acted)|ignored|has no effect"
    r"|reserved for|inert|placeholder|accepted but)",
    re.IGNORECASE,
)
for p, s in src.items():
    for i, line in enumerate(s.splitlines(), 1):
        if pat.search(line):
            print(f"{p}:{i} {line.strip()[:110]}")

# G. closures/comprehensions re-reading an attribute of an outer parameter or local
section("G. per-call lookups of an outer name's attribute inside a closure (hoist?)")
COMPS = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, *COMPS)


def scope_parts(fn: ast.AST) -> list[ast.AST]:
    if isinstance(fn, COMPS):
        elts = [fn.key, fn.value] if isinstance(fn, ast.DictComp) else [fn.elt]
        gens = fn.generators
        return elts + [x for i, g in enumerate(gens) for x in [*g.ifs, *[g.iter][:i]]]
    return fn.body if isinstance(fn.body, list) else [fn.body]


def bound_names(fn: ast.AST) -> set[str]:
    names = set()
    if isinstance(fn, COMPS):
        targets = [g.target for g in fn.generators]
        names |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    else:
        a = fn.args
        extra = [x for x in (a.vararg, a.kwarg) if x]
        names |= {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, *extra]}
    for part in scope_parts(fn):
        for n in ast.walk(part):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names.add(n.id)
    return names


def root_chain(node: ast.expr) -> tuple[str, str] | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    is_name = isinstance(node, ast.Name)
    return (node.id, ".".join(reversed(parts))) if is_name else None


for p, t in trees.items():
    for outer in ast.walk(t):
        if not isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        outer_names = bound_names(outer)
        for inner in ast.walk(outer):
            if inner is outer or not isinstance(inner, SCOPES):
                continue
            own = bound_names(inner)
            seen: dict[str, int] = {}
            for part in scope_parts(inner):
                for n in ast.walk(part):
                    if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
                        chain = root_chain(n)
                        if chain and chain[0] in outer_names - own:
                            seen.setdefault(f"{chain[0]}.{chain[1]}", n.lineno)
            for key, line in seen.items():
                if not any(o.startswith(f"{key}.") for o in seen):
                    kind = getattr(inner, "name", type(inner).__name__)
                    print(f"{p}:{line} {outer.name} -> {kind}: {key}")
