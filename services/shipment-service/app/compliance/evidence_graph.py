"""Shared provenance graph: no private declarations, provider payloads or identity files."""

from sqlalchemy import select

from .models import Authorization, Pack, Packet, PacketAck, ReleaseReview, Requirement, Rule


def build(db, evaluation, documents, sources):
    nodes, edges = {}, []

    def node(kind, ident, label, content_hash=None):
        key = kind + ":" + ident
        nodes[key] = {"id": key, "type": kind, "label": label, "content_hash": content_hash}
        return key

    def edge(source, target, relationship):
        edges.append({"source": source, "target": target, "relationship": relationship})

    root = node(
        "Evaluation",
        evaluation.id,
        evaluation.action + " / " + str(evaluation.decision),
        evaluation.evaluation_hash,
    )
    for source in sources:
        node("Source", source["id"], source["title"], source["source_sha256"])
    for reference in documents:
        doc = node(
            "Document",
            reference["document_version_id"],
            "Reviewed document version",
            reference.get("source_manifest_hash"),
        )
        edge(doc, root, "EVIDENCE_FOR")
        fact = node(
            "DocumentFacts",
            reference["reviewed_fact_revision_id"],
            "Exact submitted extracted facts",
            reference.get("fact_hash"),
        )
        edge(doc, fact, "TRANSCRIBED_AS")
        edge(fact, root, "ASSESSED_INPUT")
    snapshot = evaluation.snapshot_json
    for key, kind, label in [
        ("fact", "Declaration", "Reviewed compliance declaration"),
        ("manifest", "LoadingManifest", "Prepared loading manifest"),
    ]:
        record = snapshot.get(key)
        if record:
            reference = node(kind, record["id"], label, record["hash"])
            edge(reference, root, "ASSESSED_INPUT")
    for dimension in evaluation.coverage_json.get("independent_verification_dimensions", []):
        ident = dimension.get("verification_result_id") or dimension.get("attestation_id")
        if not ident:
            continue
        reference = node(
            "Verification",
            ident,
            dimension.get("check_type", "Transport proof")
            + " / "
            + str(dimension.get("lookup_outcome", "REVIEWED")),
        )
        edge(reference, root, "OBSERVED_PROOF")
    for requirement in db.scalars(
        select(Requirement)
        .where(Requirement.evaluation_id == evaluation.id)
        .order_by(Requirement.requirement_code)
    ):
        rule = db.get(Rule, requirement.rule_id)
        pack = db.get(Pack, rule.pack_revision_id)
        version = node(
            "RegulationVersion", rule.pack_revision_id, "Pack " + pack.version, pack.content_hash
        )
        predicate = node(
            "Rule", rule.id, rule.rule_code + " / " + rule.rule_version, rule.content_hash
        )
        decision = node(
            "Requirement",
            requirement.id,
            requirement.requirement_code + " / " + requirement.outcome,
        )
        edge(version, predicate, "DEFINES")
        edge(predicate, decision, "EVALUATES")
        edge(decision, root, "RESULT_OF")
        needed_checks = {
            "AUTHORITY_ASSURANCE": {"GSTIN_AUTHORITY_LOOKUP"},
            "EINVOICE_PROOF": {"IRN_LIVE_STATUS", "IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE"},
            "EWB_IDENTITY": {"EWB_AUTHORITY_LOOKUP"},
            "EWB_VALIDITY": {"EWB_AUTHORITY_LOOKUP"},
        }.get(requirement.requirement_code, set())
        for dimension in evaluation.coverage_json.get("independent_verification_dimensions", []):
            if dimension.get("check_type") in needed_checks and dimension.get(
                "verification_result_id"
            ):
                edge("Verification:" + dimension["verification_result_id"], decision, "PROOF_FOR")
        for reference in documents:
            if reference.get("document_type") == "TAX_INVOICE" or (
                reference.get("document_type") == "EWAY_BILL_COPY"
                and requirement.requirement_code.startswith("EWB")
            ):
                edge(
                    "DocumentFacts:" + reference["reviewed_fact_revision_id"], decision, "INPUT_FOR"
                )
        if snapshot.get("fact"):
            edge("Declaration:" + snapshot["fact"]["id"], decision, "CONTEXT_FOR")
        if snapshot.get("manifest") and requirement.requirement_code == "LOADING_MANIFEST":
            edge("LoadingManifest:" + snapshot["manifest"]["id"], decision, "INPUT_FOR")
        for source_id in requirement.source_ids:
            if "Source:" + source_id in nodes:
                edge("Source:" + source_id, version, "GROUNDS")
    for review in db.scalars(
        select(ReleaseReview).where(ReleaseReview.evaluation_id == evaluation.id)
    ):
        target = node("Review", review.id, review.decision)
        edge(root, target, "INDEPENDENT_REVIEW")
    for packet in db.scalars(select(Packet).where(Packet.evaluation_id == evaluation.id)):
        target = node("Packet", packet.id, "Assignment-bound packet", packet.packet_hash)
        edge("Review:" + packet.approval_id, target, "APPROVES")
        for ack in db.scalars(select(PacketAck).where(PacketAck.packet_id == packet.id)):
            holder = node("Acknowledgment", ack.id, "Assigned driver possession confirmed")
            edge(target, holder, "ACKNOWLEDGED")
    for token in db.scalars(
        select(Authorization).where(Authorization.evaluation_id == evaluation.id)
    ):
        target = node("Authorisation", token.id, token.action + " / " + token.execution_mode)
        edge("Acknowledgment:" + token.acknowledgment_id, target, "ENABLES")
        if token.consumed_event_id:
            event = node("ShipmentEvent", token.consumed_event_id, token.action)
            edge(target, event, "CONSUMED_BY")
    unique = {(e["source"], e["target"], e["relationship"]): e for e in edges}
    return {"nodes": list(nodes.values()), "edges": list(unique.values())}
