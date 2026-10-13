from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, create_model, field_validator, model_validator

from app.trades.reference import UQC
from app.trades.schemas import Minor, NonnegativeDecimal, PositiveDecimal, Schema, state, utc

DocumentType = Literal[
    "TAX_INVOICE",
    "BILL_OF_SUPPLY",
    "DELIVERY_CHALLAN",
    "PACKING_LIST",
    "PURCHASE_ORDER",
    "LR_GR",
    "EWAY_BILL_COPY",
    "SIGNED_EINVOICE_JSON",
    "POD",
    "PAYMENT_EVIDENCE",
    "VEHICLE_RC",
    "VEHICLE_INSURANCE",
    "FITNESS_CERTIFICATE",
    "PUC_CERTIFICATE",
    "GOODS_PERMIT",
    "PERMIT_AUTHORISATION",
    "DRIVER_LICENCE",
    "CARGO_INSURANCE",
    "OTHER",
]
CheckType = Literal[
    "GSTIN_FORMAT",
    "GSTIN_AUTHORITY_LOOKUP",
    "IRP_QR_SIGNATURE",
    "IRP_JSON_SIGNATURE",
    "IRN_LIVE_STATUS",
    "EWB_AUTHORITY_LOOKUP",
    "PDF_SIGNATURE",
]
Money = Minor
SignedMoney = Annotated[str, Field(pattern=r"^-?\d{1,18}$")]
Timestamp = Annotated[datetime, AfterValidator(utc)]


def nullable_model(name, fields):
    return create_model(name, __base__=Schema, **{k: (v | None, None) for k, v in fields.items()})


PartialAddress = nullable_model(
    "PartialDocumentAddress",
    {
        **{
            k: str
            for k in (
                "address_line1",
                "address_line2",
                "locality",
                "city",
                "district",
                "state_code",
                "postal_code",
                "country_code",
                "contact_name",
                "timezone",
            )
        },
    },
)


class Party(Schema):
    legal_name: str | None = Field(None, max_length=200)
    trade_name: str | None = Field(None, max_length=200)
    registration_identifier_kind: Literal["GSTIN", "UNREGISTERED_DECLARATION", "UNKNOWN"] | None = (
        None
    )
    gstin: str | None = Field(None, max_length=30)
    registration_identifier_raw: str | None = Field(None, max_length=100)
    address: PartialAddress | None = None
    declared_organization_id: UUID | None = None


Parties = nullable_model(
    "DocumentParties",
    {
        k: Party
        for k in ("supplier", "recipient", "bill_from", "bill_to", "dispatch_from", "ship_to")
    },
)
Header = nullable_model(
    "DocumentHeader",
    {
        **{
            k: Annotated[str, Field(max_length=100)]
            for k in ("document_number", "purchase_order_reference", "acknowledgment_number")
        },
        "issue_date": date,
        "currency": Literal["INR"],
        "movement_reason_declared": Annotated[str, Field(max_length=200)],
        "document_profile": Literal[
            "SIMPLE_DECLARED_TOTALS", "SUPPORTED_STRUCTURED_PROFILE", "UNRESOLVED"
        ],
        "irn": Annotated[str, Field(max_length=64)],
        "acknowledgment_at": Timestamp,
        "place_of_supply_state_code": Annotated[str, AfterValidator(state)],
        "reverse_charge_position": Literal["YES", "NO", "UNKNOWN"],
        "issuance_form": Literal["PAPER_WITH_SIGNATURE", "ELECTRONIC_IT_ACT_DECLARED", "UNKNOWN"],
        "signature_presence": Literal["OBSERVED", "NOT_OBSERVED", "NOT_ASSESSED"],
        "invoice_series_fy": Annotated[int, Field(ge=2017, le=2100)],
        "invoice_profile_code": Annotated[str, Field(max_length=100)],
    },
)


class GoodsLine(Schema):
    document_line_ref: UUID
    line_number_printed: str | None = Field(None, max_length=30)
    description: str | None = Field(None, max_length=2000)
    hsn_code: Annotated[str, Field(pattern=r"^\d{2,8}$")] | None = None
    quantity: NonnegativeDecimal | None = None
    uqc: str | None = None
    unit_price_minor: NonnegativeDecimal | None = None
    line_discount_minor: Money | None = None
    taxable_value_minor: Money | None = None
    declared_cgst_rate_percent: NonnegativeDecimal | None = None
    declared_sgst_rate_percent: NonnegativeDecimal | None = None
    declared_igst_rate_percent: NonnegativeDecimal | None = None
    cgst_amount_minor: Money | None = None
    sgst_amount_minor: Money | None = None
    igst_amount_minor: Money | None = None
    cess_amount_minor: Money | None = None
    state_cess_amount_minor: Money | None = None
    line_total_minor: Money | None = None
    batch_number: str | None = Field(None, max_length=100)
    serial_numbers: list[str] | None = None
    manufactured_on: date | None = None
    expires_on: date | None = None

    @field_validator("uqc")
    @classmethod
    def unit(cls, value):
        if value is not None and value not in UQC:
            raise ValueError("Use a maintained UQC; no automatic unit conversion")
        return value


Totals = nullable_model(
    "DocumentTotals",
    {
        **{
            k: Money
            for k in (
                "taxable_subtotal_minor",
                "discount_total_minor",
                "cgst_total_minor",
                "sgst_total_minor",
                "igst_total_minor",
                "cess_total_minor",
                "state_cess_total_minor",
                "grand_total_minor",
            )
        },
        "other_charges_minor": SignedMoney,
        "round_off_minor": SignedMoney,
        "discount_treatment": Literal[
            "INCLUDED_IN_TAXABLE_SUBTOTAL", "SUBTRACT_AFTER_SUBTOTAL", "UNRESOLVED"
        ],
    },
)
Packing = nullable_model(
    "DocumentPackingTransport",
    {
        **{k: NonnegativeDecimal for k in ("gross_weight_kg", "net_weight_kg", "volume_m3")},
        "package_count": Annotated[int, Field(ge=0)],
        **{
            k: Annotated[str, Field(max_length=100)]
            for k in (
                "package_type",
                "lr_gr_number",
                "carrier_name",
                "transporter_identifier",
                "vehicle_registration_number",
                "un_number",
            )
        },
        "marks_and_numbers": Annotated[str, Field(max_length=1000)],
        "lr_gr_date": date,
        "transport_mode_declared": Literal["ROAD", "RAIL", "AIR", "SHIP", "UNKNOWN"],
        "temperature_min_c": Decimal,
        "temperature_max_c": Decimal,
        "hazardous_description": Annotated[str, Field(max_length=1000)],
    },
)
Eway = nullable_model(
    "PrintedEwayBill",
    {
        **{
            k: Annotated[str, Field(max_length=100)]
            for k in (
                "eway_bill_number",
                "printed_status",
                "referenced_document_type",
                "referenced_document_number",
                "transporter_identifier",
                "vehicle_registration_number",
            )
        },
        **{k: Timestamp for k in ("generated_at", "valid_from_at", "valid_until_at")},
        "part_information": Literal["FULL_COPY", "PART_A_ONLY", "UNKNOWN"],
        "referenced_document_date": date,
        "declared_invoice_value_minor": Money,
        "declared_distance_km": NonnegativeDecimal,
    },
)
Pod = nullable_model(
    "PrintedPOD",
    {
        **{
            k: Annotated[str, Field(max_length=100)]
            for k in ("delivery_reference", "receiver_name_printed")
        },
        "delivery_at": Timestamp,
        "package_count_received": Annotated[int, Field(ge=0)],
        "condition_notes": Annotated[str, Field(max_length=2000)],
        "signature_present_visual": bool,
    },
)
Payment = nullable_model(
    "PrintedPaymentEvidence",
    {
        "amount_minor": Money,
        "currency": Literal["INR"],
        "transaction_date": date,
        "transaction_at": Timestamp,
        **{
            k: Annotated[str, Field(max_length=100)]
            for k in (
                "transaction_reference",
                "payer_name",
                "payee_name",
                "payment_method_declared",
                "printed_transaction_status",
            )
        },
    },
)


class CanonicalDocument(Schema):
    schema_version: Literal["PH3_CANONICAL_V1", "PH4_CANONICAL_V2"] = "PH3_CANONICAL_V1"
    header: Header = Field(default_factory=Header)
    parties: Parties = Field(default_factory=Parties)
    lines: list[GoodsLine] = Field(default_factory=list, max_length=1000)
    totals: Totals = Field(default_factory=Totals)
    packing_transport: Packing = Field(default_factory=Packing)
    eway_bill: Eway = Field(default_factory=Eway)
    pod: Pod = Field(default_factory=Pod)
    payment_evidence: Payment = Field(default_factory=Payment)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.document_line_ref for line in self.lines}) != len(self.lines):
            raise ValueError("Document line identities must be unique")
        return self


class BoundingBox(Schema):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError("Bounding box bounds are reversed")
        return self


class SourceLocator(Schema):
    source_attachment_id: UUID
    page_number: int | None = Field(None, ge=1)
    coordinate_space: Literal["RENDERED_PAGE_TOP_LEFT"] | None = None
    bounding_box: BoundingBox | None = None
    text_artifact_id: UUID | None = None
    text_start: int | None = Field(None, ge=0)
    text_end: int | None = Field(None, ge=0)
    json_pointer: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def bounds(self):
        if self.bounding_box and (not self.page_number or not self.coordinate_space):
            raise ValueError("Page coordinates require a rendered page and coordinate space")
        if (self.text_start is None) != (self.text_end is None):
            raise ValueError("Supply both text span bounds")
        if self.text_start is not None and self.text_end < self.text_start:
            raise ValueError("Text span is reversed")
        return self


class AssetInput(Schema):
    attachment_id: UUID
    role: Literal["SIGNED_PAYLOAD", "SUPPORTING_RENDERING"]


class Registration(Schema):
    document_type: DocumentType
    label: str = Field(min_length=1, max_length=150)
    trade_id: UUID
    initial_consignment_id: UUID | None = None
    declared_document_number: str | None = Field(None, max_length=100)
    declared_issue_date: date | None = None
    declared_issuer_organization_id: UUID | None = None
    notes: str | None = Field(None, max_length=2000)
    primary_attachment_id: UUID
    supporting_assets: list[AssetInput] = Field(default_factory=list, max_length=20)
    visibility: Literal["OWNER_ONLY", "TRADE_PARTIES"] = "OWNER_ONLY"


class SourceVersion(Schema):
    reason: Literal["INITIAL", "CLEARER_COPY", "ADDITIONAL_PAGES", "UPDATED_RECORD_COPY", "OTHER"]
    reason_text: str = Field(min_length=1, max_length=1000)
    primary_attachment_id: UUID
    supporting_assets: list[AssetInput] = Field(default_factory=list, max_length=20)


class Reason(Schema):
    reason: str = Field(min_length=1, max_length=2000)


class Processing(Schema):
    stage: Literal["PREPROCESS", "EXTRACT"] = "EXTRACT"
    strategy: Literal["AUTO", "NATIVE_TEXT", "OCR", "STRUCTURED_JSON", "SIMULATION_FIXTURE"] = (
        "AUTO"
    )
    reprocess: bool = False


class FieldDecision(Schema):
    field_path: str = Field(max_length=500)
    document_line_ref: UUID | None = None
    observation_id: UUID | None = None
    decision: Literal["CONFIRMED", "CORRECTED", "UNRESOLVED", "NOT_APPLICABLE"]
    effective_value: object = None
    provenance: Literal["EXTRACTION_REVIEW", "HUMAN_TRANSCRIPTION"]
    reason: str | None = Field(None, max_length=2000)
    source_locator: SourceLocator | None = None

    @model_validator(mode="after")
    def explained(self):
        if self.field_path.endswith("_at") and self.effective_value is not None:
            timestamp = utc(datetime.fromisoformat(str(self.effective_value)))
            self.effective_value = timestamp.isoformat().replace("+00:00", "Z")
        if (
            self.decision != "CONFIRMED" or self.provenance == "HUMAN_TRANSCRIPTION"
        ) and not self.reason:
            raise ValueError("A correction, unresolved field, or transcription needs a reason")
        return self


class Alignment(Schema):
    candidate_row_key: str
    document_line_ref: UUID


class FactRevisionInput(Schema):
    base_fact_revision_id: UUID | None = None
    extraction_run_id: UUID | None = None
    canonical_document: CanonicalDocument
    field_decisions: list[FieldDecision] = Field(max_length=10000)
    line_alignments: list[Alignment] = Field(default_factory=list)
    review_note: str | None = Field(None, max_length=2000)


class Submission(Schema):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_note: str | None = Field(None, max_length=2000)


class LineMapping(Schema):
    document_line_ref: UUID
    trade_line_ref: UUID
    target_kind: Literal["ORDER_LINE", "CONSIGNMENT_ITEM"]
    consignment_item_id: UUID | None = None
    mapped_quantity: PositiveDecimal
    uqc: str

    @model_validator(mode="after")
    def target(self):
        if (self.target_kind == "CONSIGNMENT_ITEM") != bool(self.consignment_item_id):
            raise ValueError("Only a consignment-item mapping needs a consignment item")
        return self


class MappingInput(Schema):
    fact_revision_id: UUID
    accepted_trade_revision_id: UUID
    base_mapping_revision_id: UUID | None = None
    mappings: list[LineMapping] = Field(max_length=10000)


class AssessmentInput(Schema):
    fact_revision_id: UUID
    mapping_revision_id: UUID | None = None
    scope: Literal["TRADE", "CONSIGNMENT"] = "TRADE"
    consignment_ids: list[UUID] = Field(default_factory=list)
    related_document_version_ids: list[UUID] = Field(default_factory=list)


class VerificationInput(Schema):
    check_type: CheckType
    fact_revision_id: UUID | None = None
    target_field_path: str | None = None
    signed_payload_artifact_id: UUID | None = None
    connection_id: UUID | None = None
    reason: str | None = Field(None, max_length=1000)


class RelationshipInput(Reason):
    to_document_id: UUID
    relationship_type: Literal[
        "DUPLICATE_PRESENTATION_OF", "SUPERSEDES_BUSINESS_DOCUMENT", "SUPPORTS"
    ]


class SubjectInput(Schema):
    subject_type: Literal["TRADE", "CONSIGNMENT", "RECEIPT", "PAYMENT", "DISPUTE"]
    subject_id: UUID


class ShareInput(Schema):
    grantee_organization_id: UUID
    access_type: Literal["READ_REVIEWED", "DOWNLOAD_ORIGINAL", "OPERATIONAL_PROJECTION"]
    assignment_id: UUID | None = None
    allowed_field_paths: list[str] = Field(default_factory=list)


class AnnotationInput(Schema):
    action: Literal[
        "ACKNOWLEDGE",
        "REQUEST_EXTRACTION_CORRECTION",
        "REQUEST_SOURCE_REPLACEMENT",
        "NOTE_COMMERCIAL_VARIANCE",
    ]
    note: str = Field(min_length=1, max_length=2000)
    related_new_assessment_id: UUID | None = None


class ManualAttestation(Schema):
    check_type: CheckType
    target_identifier: str = Field(min_length=1, max_length=100)
    portal_source_url: str = Field(max_length=500)
    observed_at: datetime
    observed_status: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    evidence_attachment_ids: list[UUID] = Field(default_factory=list)
    observed_fields: dict[str, Annotated[str, Field(max_length=500)]] = Field(
        default_factory=dict, max_length=40
    )
    _utc = field_validator("observed_at")(utc)


class ConnectionInput(Schema):
    adapter_name: Literal["AUTHORISED_READ_ONLY_V1"]
    provider_environment: Literal["SIMULATION", "SANDBOX", "LIVE"]
    requester_identifier: str | None = Field(None, max_length=100)
    authorised_secret_binding: str = Field(min_length=1, max_length=100)
    allowed_check_types: list[CheckType]
