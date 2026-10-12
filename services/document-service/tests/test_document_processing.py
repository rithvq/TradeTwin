import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.document_processing.adapters import ReadOnlyAdapter  # noqa: E402
from app.document_processing.parser import ParseFailure, isolated_parse, parse  # noqa: E402
from app.document_processing.signatures import verify  # noqa: E402
from app.document_processing.structured import lossless_json  # noqa: E402
from app.document_processing.structured import parse as structured_parse  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "data/fixtures/document-desk"


def options(**extra):
    return {
        "text_artifact_id": str(uuid4()),
        "document_type": "TAX_INVOICE",
        "max_pages": 100,
        "max_text": 1000000,
        "max_image_pixels": 25000000,
        "max_render_pixels": 10000000,
        "ocr_engine": "disabled",
        "execution_mode": "SIMULATION",
        **extra,
    }


def test_native_pdf_actual_values_and_source_bounds():
    content = (FIXTURES / "invoice.pdf").read_bytes()
    output = isolated_parse(content, "application/pdf", str(uuid4()), options())
    assert output["status"] == "SUCCEEDED"
    assert output["canonical_document"]["header"]["document_number"] == "INV-000001"
    assert output["canonical_document"]["lines"][0]["quantity"] == "100"
    assert output["canonical_document"]["totals"]["grand_total_minor"] == "1180000"
    assert output["canonical_document"]["totals"]["taxable_subtotal_minor"] == "1000000"
    assert output["pages"]
    for observation in output["observations"]:
        assert observation["provider_confidence"] is None
        loc = observation["source_locator_json"]
        assert 0 <= loc["bounding_box"]["x0"] <= loc["bounding_box"]["x1"] <= 1
        assert loc["text_end"] <= len(output["text"])
    assert hashlib.sha256(content).hexdigest() == output["metadata"]["server_sha256"]


def test_scanned_image_explicit_ocr_unavailable_and_safe_preview():
    output = parse(
        (FIXTURES / "scanned-invoice.png").read_bytes(), "image/png", str(uuid4()), options()
    )
    assert output["status"] == "PARTIAL" and output["error_code"] == "OCR_UNAVAILABLE"
    assert output["observations"] == [] and output["pages"]


def test_simulation_reading_error_is_not_a_production_engine():
    content = (FIXTURES / "scanned-invoice.png").read_bytes()
    fixture = json.loads((FIXTURES / "simulation-extraction.json").read_text())[
        hashlib.sha256(content).hexdigest()
    ]
    output = parse(
        content,
        "image/png",
        str(uuid4()),
        options(simulation_fixture=fixture),
        "SIMULATION_FIXTURE",
    )
    assert output["engine_kind"] == "SIMULATION_FIXTURE"
    assert "I234" in output["canonical_document"]["parties"]["supplier"]["gstin"]
    production = parse(
        content,
        "image/png",
        str(uuid4()),
        options(simulation_fixture=fixture, execution_mode="PRODUCTION"),
    )
    assert production["error_code"] == "OCR_UNAVAILABLE"


@pytest.mark.parametrize(
    "mime,content",
    [("application/pdf", b"not a PDF"), ("image/png", b"%PDF-fake"), ("image/jpeg", b"not jpeg")],
)
def test_spoofed_files_fail(mime, content):
    with pytest.raises(ParseFailure, match="FILE_SIGNATURE_MISMATCH"):
        parse(content, mime, str(uuid4()), options())


def test_encrypted_pdf_and_page_limit_fail_explicitly():
    writer = PdfWriter()
    writer.append(PdfReader(FIXTURES / "invoice.pdf"))
    writer.encrypt("test-only")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ParseFailure, match="DOCUMENT_ENCRYPTED"):
        parse(output.getvalue(), "application/pdf", str(uuid4()), options())
    with pytest.raises(ParseFailure, match="DOCUMENT_LIMIT_EXCEEDED"):
        parse(
            (FIXTURES / "invoice.pdf").read_bytes(),
            "application/pdf",
            str(uuid4()),
            options(max_pages=0),
        )


def test_image_and_text_limits_are_not_silent_truncation():
    with pytest.raises(ParseFailure, match="DOCUMENT_LIMIT_EXCEEDED"):
        parse(
            (FIXTURES / "invoice.pdf").read_bytes(),
            "application/pdf",
            str(uuid4()),
            options(max_text=30),
        )
    image = Image.new("RGB", (30, 30))
    content = BytesIO()
    image.save(content, format="PNG")
    with pytest.raises(
        (ParseFailure, Image.DecompressionBombError, Image.DecompressionBombWarning)
    ):
        parse(content.getvalue(), "image/png", str(uuid4()), options(max_image_pixels=100))


def test_hostile_instruction_text_is_only_document_data():
    output = parse(
        (FIXTURES / "hostile-content.pdf").read_bytes(), "application/pdf", str(uuid4()), options()
    )
    assert "Ignore instructions" in output["text"]
    assert "verified" not in output["canonical_document"]
    assert output["canonical_document"]["header"]["document_number"] == "INV-000001"


def test_lossless_json_identifiers_decimals_and_duplicate_keys():
    original = (
        b'{"DocDtls":{"No":"0000123","Dt":"2026-10-12"},'
        b'"ItemList":[{"SlNo":"01","PrdDesc":"Motor","HsnCd":"001234",'
        b'"Qty":100.000001,"Unit":"NOS","UnitPrice":100.01}],'
        b'"ValDtls":{"TotInvVal":11800.01}}'
    )
    canonical, observations, _ = structured_parse(original, str(uuid4()))
    assert canonical["header"]["document_number"] == "0000123"
    assert canonical["lines"][0]["quantity"] == "100.000001"
    assert canonical["lines"][0]["hsn_code"] == "001234"
    assert canonical["totals"]["grand_total_minor"] == "1180001"
    assert all(o["source_locator_json"]["json_pointer"].startswith("/") for o in observations)
    with pytest.raises(ValueError):
        lossless_json(b'{"verified":true,"verified":false}')
    with pytest.raises(ValueError):
        lossless_json(b'{"amount":NaN}')


def trusted_key(environment="SIMULATION"):
    pem = (FIXTURES / "simulation-public.pem").read_text()
    return {
        "id": str(uuid4()),
        "key_identifier": "PH3_SIMULATION_ONLY",
        "algorithm": "RS256",
        "key_purpose": "IRP_SIGNATURE",
        "status": "ACTIVE",
        "provider_environment": environment,
        "key_fingerprint": hashlib.sha256(pem.encode()).hexdigest(),
        "public_key_reference": pem,
    }


def test_signature_exact_bytes_key_environment_and_missing_key():
    token = json.loads((FIXTURES / "signed-payload.json").read_text())["SignedInvoice"]
    key = trusted_key()
    good = verify(token, [key], "SIMULATION", str(uuid4()))
    assert (
        good["signature_integrity"] == "VALID" and good["issuer_trust"] == "TRUSTED_FOR_THIS_CHECK"
    )
    assert "header.document_number" in good["covered_field_paths"]
    assert verify(token, [], "SIMULATION", str(uuid4()))["signature_integrity"] == "KEY_UNAVAILABLE"
    assert verify(token, [key], "LIVE", str(uuid4()))["signature_integrity"] == "KEY_UNAVAILABLE"
    header, payload, signature = token.split(".")
    altered = ("a" if payload[0] != "a" else "b") + payload[1:]
    assert (
        verify(f"{header}.{altered}.{signature}", [key], "SIMULATION", str(uuid4()))[
            "signature_integrity"
        ]
        == "INVALID"
    )


def test_qr_decode_does_not_follow_urls_or_claim_signature():
    output = parse(
        (FIXTURES / "mismatched-invoice.pdf").read_bytes(),
        "application/pdf",
        str(uuid4()),
        options(),
    )
    assert output["qr_payloads"]
    assert output["canonical_document"]["header"]["document_number"] == "INV-CHANGED"
    assert "signature_integrity" not in output


@pytest.mark.parametrize(
    "kind", ["GSTIN_AUTHORITY_LOOKUP", "IRN_LIVE_STATUS", "EWB_AUTHORITY_LOOKUP"]
)
def test_authority_absence_and_denial_are_not_invalid_documents(kind):
    adapter = ReadOnlyAdapter()
    assert adapter.check(kind, "0001", None, "PRODUCTION")[0] == "NOT_CONFIGURED"
    connection = {
        "provider_environment": "SIMULATION",
        "status": "CONFIGURED",
        "allowed_check_types_json": [kind],
        "secret_reference": "ABSENT",
    }
    assert adapter.check(kind, "0001", connection, "PRODUCTION")[0] == "NOT_AUTHORISED"


def test_unknown_structured_model_fields_are_rejected():
    with pytest.raises(ValueError):
        structured_parse(b'{"schema_version":"PH3_CANONICAL_V1","verified":true}', str(uuid4()))
