"""Architectural boundaries, checked against source or the installed wheel.

The cycle check covers declared eager imports, not dynamic calls or imports
inside functions. Fresh-process integration tests cover actual initialization.
"""

import ast
from pathlib import Path

import pynakes

ROOT = Path(pynakes.__file__).resolve().parent


def _eager_imports(nodes):
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            if ast.unparse(node.test) not in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}:
                yield from _eager_imports(node.body)
                yield from _eager_imports(node.orelse)
        elif isinstance(node, ast.ClassDef):
            yield from _eager_imports(node.body)
        elif isinstance(node, ast.Try):
            yield from _eager_imports(node.body)
            yield from _eager_imports(node.orelse)
            yield from _eager_imports(node.finalbody)
            for handler in node.handlers:
                yield from _eager_imports(handler.body)


def _graph():
    paths = {
        ".".join(path.relative_to(ROOT.parent).with_suffix("").parts).removesuffix(
            ".__init__"
        ): path
        for path in ROOT.rglob("*.py")
    }
    graph = {name: set() for name in paths}
    for name, path in paths.items():
        for node in _eager_imports(ast.parse(path.read_text(encoding="utf-8")).body):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                # Resolve package-relative imports as well as the project's
                # usual absolute ones, so a spelling change cannot hide an edge.
                module = node.module or ""
                if node.level:
                    package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
                    prefix = package.split(".")[: len(package.split(".")) - node.level + 1]
                    module = ".".join([*prefix, *([module] if module else [])])
                targets = [
                    candidate if (candidate := f"{module}.{alias.name}") in paths else module
                    for alias in node.names
                ]
            graph[name].update(target for target in targets if target in paths and target != name)
    return graph


def test_declared_eager_imports_are_acyclic():
    graph = _graph()
    visited = set()
    active = []

    def visit(name):
        assert name not in active, "Import cycle: " + " -> ".join([*active, name])
        if name in visited:
            return
        active.append(name)
        for dependency in sorted(graph[name]):
            visit(dependency)
        active.pop()
        visited.add(name)

    for name in sorted(graph):
        visit(name)


def test_domain_packages_do_not_depend_on_cli():
    domains = ("engine", "library", "analysis", "lint", "filestore", "fetch")
    for name, dependencies in _graph().items():
        if any(
            name == f"pynakes.{domain}" or name.startswith(f"pynakes.{domain}.")
            for domain in domains
        ):
            assert not any(dep.startswith("pynakes.cli") for dep in dependencies), name


def test_storage_and_backend_contracts_stay_below_orchestration():
    graph = _graph()
    for name, dependencies in graph.items():
        if name == "pynakes.filestore" or name.startswith("pynakes.filestore."):
            assert not any(
                dep.startswith(("pynakes.fetch", "pynakes.providers")) for dep in dependencies
            ), name
    assert not any(
        dep.startswith(("pynakes.engine", "pynakes.library", "pynakes.cli"))
        for dep in graph["pynakes.library.backends.base"]
    )
