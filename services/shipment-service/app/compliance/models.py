"""Explicit model registry for the Phase 4 additive migration."""

from .models_dispatch import Authorization, AuthorizationEvent, Packet, PacketAck, PacketItem
from .models_evaluation import (
    CaseAction,
    Dependency,
    Evaluation,
    Hold,
    HoldEvent,
    ReleaseReview,
    Requirement,
    ReviewCase,
)
from .models_facts import (
    Binding,
    Fact,
    FactReview,
    Heads,
    Manifest,
    PrivateIdentity,
    Reservation,
    ReservationEvent,
    TradeContext,
    TransportEvidence,
    TransportReview,
    Turnover,
    TurnoverReview,
)
from .models_manual import ManualEvidence, ManualReview
from .models_private_sources import PrivateSource
from .models_projection import MovementProjection
from .models_recipient import RecipientConfirmation
from .models_rules import Pack, Publication, Registry, Rule, Source, SourceConflict, TestRun

TABLES = [
    RecipientConfirmation,
    MovementProjection,
    PrivateSource,
    ManualEvidence,
    ManualReview,
    TradeContext,
    Heads,
    Fact,
    FactReview,
    PrivateIdentity,
    Turnover,
    TurnoverReview,
    Manifest,
    TransportEvidence,
    TransportReview,
    Binding,
    Reservation,
    ReservationEvent,
    Source,
    SourceConflict,
    Pack,
    Rule,
    TestRun,
    Publication,
    Registry,
    Evaluation,
    Dependency,
    Requirement,
    ReviewCase,
    CaseAction,
    ReleaseReview,
    Hold,
    HoldEvent,
    Packet,
    PacketItem,
    PacketAck,
    Authorization,
    AuthorizationEvent,
]
IMMUTABLE_TABLES = [
    model.__tablename__
    for model in TABLES
    if model
    not in {
        TradeContext,
        Heads,
        Reservation,
        SourceConflict,
        Registry,
        Evaluation,
        ReviewCase,
        Hold,
        Authorization,
    }
]
__all__ = [model.__name__ for model in TABLES] + ["IMMUTABLE_TABLES", "TABLES"]
