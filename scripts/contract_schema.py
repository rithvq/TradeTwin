"""Keep generated phase contracts scoped and transitively complete, without schema duplication."""

from copy import deepcopy


def prune(document):
    result = deepcopy(document)
    components = result.get("components", {}).get("schemas", {})
    required = set()

    def visit(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                name = reference.rsplit("/", 1)[-1]
                if name not in required:
                    required.add(name)
                    visit(components[name])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(result["paths"])
    result["components"]["schemas"] = {
        name: value for name, value in components.items() if name in required
    }
    return result


def scoped(document, phase_tags):
    result = deepcopy(document)
    paths = {}
    for path, methods in result["paths"].items():
        operations = {}
        for method, operation in methods.items():
            tags = set(operation.get("tags", []))
            # Parent-router commercial tags are inherited by every subsequent phase.
            commercial = "Commercial agreements" in phase_tags and tags == {"Commercial agreements"}
            own_phase = bool(tags & (set(phase_tags) - {"Commercial agreements"}))
            if commercial or own_phase:
                operations[method] = operation
        if operations:
            paths[path] = operations
    result["paths"] = paths
    return prune(result)
