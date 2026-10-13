from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from app.trades.schemas import Minor, PositiveDecimal, Schema, state, utc

Timestamp = Annotated[datetime, AfterValidator(utc)]
State = Annotated[str, AfterValidator(state)]
Code = Annotated[str, Field(min_length=1, max_length=100)]
Note = Annotated[str, Field(min_length=1, max_length=2000)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Action = Literal["PICKUP_CONFIRMED", "DEPARTED"]
Mode = Literal["SIMULATION", "PRODUCTION"]
Decision = Literal["APPROVE_DECLARATION", "RETURN_FOR_CORRECTION"]
Ids = Annotated[list[UUID], Field(max_length=100)]


class Provenance(Schema):
    origin: Literal["USER_DECLARATION", "REVIEWED_DOCUMENT"]
    source_entity_type: str | None = Field(None, max_length=100)
    source_entity_id: UUID | None = None
    source_field_path: str | None = Field(None, max_length=200)
    reason: str | None = Field(None, max_length=1000)


class Facts(Schema):
    schema_version: Literal[1] = 1
    scope_profile_code: Code | None = None
    declared_transit_state_codes: list[State] | None = Field(None, max_length=20)
    corridor_declaration_basis: Literal[
        "CARRIER_DECLARATION", "SUPPORTED_ROUTE_RECORD", "UNKNOWN"
    ] = "UNKNOWN"
    corridor_basis_document_version_ids: Ids = Field(default_factory=list)
    requested_pickup_at: Timestamp | None = None
    requested_departure_at: Timestamp | None = None
    expected_arrival_at: Timestamp | None = None
    seller_taxpayer_category_code: Code | None = None
    recipient_category_code: Code | None = None
    supply_taxability: Literal["TAXABLE", "EXEMPT", "NON_GST", "MIXED", "UNKNOWN"] = "UNKNOWN"
    taxability_basis_document_version_ids: Ids = Field(default_factory=list)
    commodity_scope_codes: list[Code] = Field(default_factory=list, max_length=20)
    classification_basis_document_version_ids: Ids = Field(default_factory=list)
    over_dimensional_cargo_declared: bool | None = None
    special_valuation_profile: Literal["NONE_DECLARED", "IDENTIFIED_SPECIAL_PROFILE", "UNKNOWN"] = (
        "UNKNOWN"
    )
    reverse_charge_position: Literal["YES", "NO", "UNKNOWN"] = "UNKNOWN"
    document_issue_scenario: Literal[
        "ONE_INVOICE_PER_CONSIGNMENT", "ONE_INVOICE_MULTIPLE_DISPATCHES", "OTHER", "UNKNOWN"
    ] = "UNKNOWN"
    seller_turnover_declaration_id: UUID | None = None
    claimed_exception_code: Code | None = None
    claimed_exception_basis_document_version_ids: Ids = Field(default_factory=list)
    declaration_note: str | None = Field(None, max_length=2000)
    field_provenance: dict[str, Provenance] = Field(default_factory=dict)

    @model_validator(mode="after")
    def declarations(self):
        editable = set(type(self).model_fields) - {"schema_version", "field_provenance"}
        if set(self.field_provenance) - editable:
            raise ValueError("Provenance may describe editable fields only")
        return self


class FactPrepare(Schema):
    expected_context_version: int = Field(ge=0)
    facts: Facts
    submit_for_review: bool = False


class DeclarationReview(Schema):
    decision: Decision
    reason: Note


class RecipientInput(Schema):
    expected_context_version: int = Field(ge=0)
    confirmation: Literal["MATCHES_ACCEPTED_SNAPSHOT", "REQUEST_CORRECTION"]
    gstin: str = Field(pattern=r"^[0-9A-Z]{15}$")
    destination_state_code: State
    address_line1: str = Field(min_length=1, max_length=500)
    recipient_category_code: Literal["REGISTERED_REGULAR", "SEZ", "UNKNOWN"]
    note: Note


class IdentityInput(Schema):
    pan: Annotated[str, Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")]
    reason: Note


class TurnoverYear(Schema):
    financial_year_start: int = Field(ge=2017, le=2100)
    existence_status: Literal["IN_EXISTENCE", "NOT_IN_EXISTENCE", "UNKNOWN"]
    pan_aggregate_turnover_minor: Minor | None = None
    source_document_version_ids: Ids = Field(default_factory=list)
    provenance: Literal["SELF_DECLARED", "REVIEWED_RECORD"]
    note: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def basis(self):
        if (
            self.existence_status != "IN_EXISTENCE"
            and self.pan_aggregate_turnover_minor is not None
        ):
            raise ValueError("Unknown/not-in-existence is not a monetary turnover row")
        if self.existence_status == "NOT_IN_EXISTENCE" and not self.source_document_version_ids:
            raise ValueError("NOT_IN_EXISTENCE needs an explicit reviewed source basis")
        return self


class TurnoverInput(Schema):
    schema_version: Literal[1] = 1
    pan_identity_reference: UUID
    declared_business_commencement_date: date | None = None
    assessment_invoice_date: date
    relevant_financial_years: list[TurnoverYear] = Field(max_length=84)
    history_completeness_declared: bool
    supplier_exclusion_code: Code = "UNKNOWN"
    exclusion_basis_document_version_ids: Ids = Field(default_factory=list)
    declaration_note: Note

    @model_validator(mode="after")
    def unique_years(self):
        years = [r.financial_year_start for r in self.relevant_financial_years]
        if len(years) != len(set(years)):
            raise ValueError("Declare each financial year once")
        return self


class ManifestItem(Schema):
    consignment_item_id: UUID
    trade_line_ref: UUID
    loaded_quantity: PositiveDecimal
    uqc: Code


class LoadingManifest(Schema):
    items: list[ManifestItem] = Field(min_length=1, max_length=1000)
    actual_prepared_gross_weight_kg: PositiveDecimal
    actual_prepared_package_count: int = Field(gt=0)
    package_type: Literal[
        "BOX", "CARTON", "BAG", "PALLET", "CRATE", "DRUM", "BUNDLE", "BULK", "OTHER"
    ]
    measurement_basis: Literal["DECLARED", "WEIGHBRIDGE_RECORD", "OTHER_REVIEWED_RECORD"]
    measurement_document_version_ids: Ids = Field(default_factory=list)
    note: str | None = Field(None, max_length=2000)


class ManifestPrepare(Schema):
    expected_context_version: int = Field(ge=0)
    manifest: LoadingManifest


class TransportInput(Schema):
    subject_type: Literal["VEHICLE", "DRIVER", "CARRIER", "CONSIGNMENT"]
    subject_id: UUID
    assignment_id: UUID | None = None
    evidence_type: Literal[
        "VEHICLE_RC",
        "VEHICLE_INSURANCE",
        "FITNESS_CERTIFICATE",
        "PUC_CERTIFICATE",
        "GOODS_PERMIT",
        "PERMIT_AUTHORISATION",
        "DRIVER_LICENCE",
        "CARGO_INSURANCE",
    ]
    document_version_id: UUID | None = None
    reviewed_fact_revision_id: UUID | None = None
    verification_result_id: UUID | None = None
    document_number: str | None = Field(None, max_length=100)
    issuing_authority: str | None = Field(None, max_length=200)
    issued_on: date | None = None
    valid_from: Timestamp | None = None
    valid_until: Timestamp | None = None
    covered_vehicle_number: str | None = Field(None, max_length=30)
    covered_driver_reference: UUID | None = None
    covered_vehicle_classes: list[Code] = Field(default_factory=list, max_length=20)
    covered_states: list[State] = Field(default_factory=list, max_length=40)
    route_restrictions: str | None = Field(None, max_length=2000)
    route_restriction_position: Literal["NONE_DECLARED", "SUPPORTED_RESTRICTIONS", "UNKNOWN"] = (
        "UNKNOWN"
    )
    permit_basis: Literal[
        "NATIONAL", "STATE_WITH_ENDORSEMENTS", "TEMPORARY", "OTHER", "UNKNOWN"
    ] = "UNKNOWN"
    parent_permit_evidence_revision_id: UUID | None = None
    source_mode: Literal[
        "ORIGINAL_DOCUMENT", "ISSUER_DIGITAL_RECORD", "AUTHORISED_LOOKUP", "SELF_DECLARATION"
    ]
    observed_at: Timestamp | None = None
    limitations: list[str] = Field(default_factory=list, max_length=20)
    field_provenance: dict[str, Provenance] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dates(self):
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Evidence validity uses a nonempty half-open interval")
        return self


class DocumentReference(Schema):
    document_id: UUID
    document_version_id: UUID
    reviewed_fact_revision_id: UUID
    mapping_revision_id: UUID | None = None
    canonical_document_id: UUID


class EvidenceBindings(Schema):
    compliance_fact_revision_id: UUID
    loading_manifest_revision_id: UUID | None = None
    seller_turnover_declaration_id: UUID | None = None
    movement_document: DocumentReference
    supporting_documents: list[DocumentReference] = Field(default_factory=list, max_length=40)
    verification_result_ids: Ids = Field(default_factory=list)
    manual_attestation_ids: Ids = Field(default_factory=list)
    transport_evidence_revision_ids: Ids = Field(default_factory=list)
    phase3_assessment_run_ids: Ids = Field(default_factory=list)


class BindingPrepare(Schema):
    expected_context_version: int = Field(ge=0)
    bindings: EvidenceBindings


class EvaluationInput(Schema):
    action: Action
    expected_context_version: int = Field(ge=0)
