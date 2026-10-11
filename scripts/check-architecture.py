"""Check service import cycles and keep HTTP composition out of domain modules."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOTS = [ROOT / "apps/api/app", *sorted((ROOT / "services").glob("*/app"))]


def dependencies(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    # Delayed imports can deliberately break initialization cycles; check top-level imports.
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def cycles(graph: dict[str, set[str]]) -> list[str]:
    visited = set()
    active = []
    errors = []

    def visit(module):
        if module in active:
            errors.append(" -> ".join([*active[active.index(module) :], module]))
            return
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
    return errors


def main() -> None:
    errors = []
    count = 0
    for root in SERVICE_ROOTS:
        modules = {
            "app." + ".".join(path.relative_to(root).with_suffix("").parts): path
            for path in root.rglob("*.py")
            if path.name != "__init__.py"
        }
        graph = {}
        for module, path in modules.items():
            imports = dependencies(path)
            graph[module] = imports & modules.keys()
            if module != "app.main" and "app.main" in imports:
                errors.append(f"{path.relative_to(ROOT)} imports the application entry point")
            if module in {"app.evaluator", "app.domestic", "app.consistency", "app.optimizer"}:
                if any(name.startswith("app.routers") for name in imports):
                    errors.append(f"{path.relative_to(ROOT)} imports an HTTP router")
        errors.extend(f"{root.relative_to(ROOT)}: {cycle}" for cycle in cycles(graph))
        count += len(graph)
    if errors:
        raise SystemExit("Architecture check failed:\n" + "\n".join(errors))
    print(f"PASS: {count} backend modules; no import cycles or reversed HTTP dependencies")


if __name__ == "__main__":
    main()
