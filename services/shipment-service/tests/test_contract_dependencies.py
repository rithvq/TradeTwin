"""Keep independently built services on the same schema-generating dependency."""

from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = next(
    (
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "pyproject.toml").is_file()
    ),
    None,
)
if ROOT is None:
    pytest.skip(
        "Cross-service manifest checks require a repository checkout", allow_module_level=True
    )
REQUIREMENTS = [
    "apps/api/requirements.txt",
    "services/shipment-service/requirements.txt",
    "services/compliance-service/requirements.txt",
    "services/document-service/requirements.txt",
    "services/intelligence-service/requirements.txt",
]


def requirements(relative_path):
    return [
        Requirement(line)
        for raw in (ROOT / relative_path).read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith(("#", "-"))
    ]


@pytest.mark.parametrize("relative_path", REQUIREMENTS)
def test_services_pin_the_installed_schema_generator(relative_path):
    pins = [
        dependency
        for dependency in requirements(relative_path)
        if dependency.name.casefold() == "pydantic"
    ]
    assert len(pins) == 1, f"{relative_path} must pin the schema generator explicitly"
    assert str(pins[0].specifier) == f"=={version('pydantic')}", (
        f"{relative_path} must use the exact installed Pydantic version; "
        "dependency upgrades require regeneration of the committed contracts"
    )


def test_shipment_declares_the_installed_demo_pdf_generator():
    pins = [
        dependency
        for dependency in requirements("services/shipment-service/requirements.txt")
        if dependency.name.casefold() == "reportlab"
    ]
    assert len(pins) == 1, "Shipment Service must declare the PDF generator used by its demo"
    assert str(pins[0].specifier) == f"=={version('reportlab')}"
