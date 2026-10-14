"""Declaration reference data, not tax eligibility or government verification."""

STATES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}
UQC = (
    "BAG",
    "BAL",
    "BDL",
    "BOX",
    "BTL",
    "CAN",
    "CBM",
    "CCM",
    "CMS",
    "CTN",
    "DOZ",
    "DRM",
    "GGK",
    "GMS",
    "GRS",
    "GYD",
    "KGS",
    "KLR",
    "KME",
    "LTR",
    "MLT",
    "MTR",
    "MTS",
    "NOS",
    "PAC",
    "PCS",
    "PRS",
    "QTL",
    "ROL",
    "SET",
    "SQF",
    "SQM",
    "SQY",
    "TBS",
    "TGM",
    "THD",
    "TON",
    "TUB",
    "UGS",
    "UNT",
    "YDS",
    "OTH",
)

ROLE_PERMISSIONS = {
    "ORG_ADMIN": {"organization.read", "organization.edit", "locations.manage", "members.manage"},
    "SELLER_OPERATOR": {
        "organization.read",
        "trade.read",
        "trade.create",
        "trade.edit_draft",
        "trade.offer",
        "trade.withdraw_offer",
        "trade.propose_amendment",
        "evidence.read",
    },
    "BUYER_OPERATOR": {
        "organization.read",
        "trade.read",
        "trade.create",
        "trade.edit_draft",
        "trade.offer",
        "trade.withdraw_offer",
        "trade.propose_amendment",
        "evidence.read",
    },
    "SELLER_APPROVER": {"organization.read", "trade.read", "order.confirm.seller", "evidence.read"},
    "BUYER_APPROVER": {"organization.read", "trade.read", "order.confirm.buyer", "evidence.read"},
}

_READ = {"organization.read", "trade.read", "consignment.read", "evidence.read"}
_DISPUTE = {"dispute.open", "dispute.comment", "dispute.resolve", "attachment.upload"}
ROLE_PERMISSIONS.update(
    {
        "SELLER_OPERATIONS": _READ
        | _DISPUTE
        | {"consignment.plan", "consignment.cancel", "transport.assign"},
        "BUYER_RECEIVER": _READ
        | _DISPUTE
        | {"receipt.record", "receipt.correct", "receipt.close", "receipt.reopen"},
        "BUYER_OPERATIONS": _READ
        | _DISPUTE
        | {
            "receipt.record",
            "receipt.correct",
            "receipt.close",
            "receipt.reopen",
            "transport.assign",
        },
        "BUYER_INSPECTOR": _READ | _DISPUTE | {"goods.accept", "goods.acceptance.reverse"},
        "CARRIER_DISPATCHER": {
            "organization.read",
            "consignment.read",
            "evidence.read",
            "carrier_profile.manage",
            "vehicle.manage",
            "assignment.respond",
            "attachment.upload",
        },
        "DRIVER": {
            "organization.read",
            "consignment.read",
            "shipment.event.record",
            "attachment.upload",
            "evidence.read",
        },
        "BUYER_FINANCE": _READ
        | _DISPUTE
        | {
            "payment_schedule.propose",
            "payment_schedule.approve",
            "payment.report",
            "payment.void.propose",
            "payment.void.approve",
        },
        "SELLER_FINANCE": _READ
        | _DISPUTE
        | {
            "payment_schedule.propose",
            "payment_schedule.approve",
            "payment.acknowledge",
            "payment.allocate",
            "payment.allocation.reverse",
            "payment.void.propose",
            "payment.void.approve",
        },
    }
)

_DOCUMENT_READ = {"document.read", "document.original.download", "document.financial.read"}
_DOCUMENT_OPERATOR = {
    "document.register",
    "document.version.add",
    "document.process",
    "document.review",
    "document.map",
    "document.check",
    "document.verify.request",
    "document.share",
    "document.archive",
    "document.manual_attestation.record",
}
ROLE_PERMISSIONS.update(
    {
        "SELLER_DOCUMENT_OPERATOR": _READ
        | _DOCUMENT_READ
        | _DOCUMENT_OPERATOR
        | {"attachment.upload"},
        "BUYER_DOCUMENT_REVIEWER": _READ
        | _DOCUMENT_READ
        | _DOCUMENT_OPERATOR
        | {
            "document.review.submit",
            "attachment.upload",
        },
        "SELLER_DOCUMENT_REVIEWER": _READ
        | _DOCUMENT_READ
        | _DOCUMENT_OPERATOR
        | {
            "document.review.submit",
            "attachment.upload",
        },
        "INTEGRATION_ADMINISTRATOR": {"organization.read", "document.provider.configure"},
    }
)
for _role in ("SELLER_FINANCE", "BUYER_FINANCE"):
    ROLE_PERMISSIONS[_role] |= (
        _DOCUMENT_READ
        | _DOCUMENT_OPERATOR
        | {
            "document.review.submit",
            "document.payment_evidence.read",
        }
    )

ROLE_PERMISSIONS.update(
    {
        "SELLER_COMPLIANCE_PREPARER": _READ
        | _DOCUMENT_READ
        | _DOCUMENT_OPERATOR
        | {
            "document.review.submit",
            "attachment.upload",
            "compliance.read",
            "compliance.facts.prepare",
            "transport.evidence.prepare",
            "compliance.evaluate",
            "compliance.evidence.link",
            "compliance.case.comment",
            "shipment.loading_manifest.prepare",
            "dispatch.packet.prepare",
            "dispatch.packet.read",
            "dispatch.authorisation.request",
            "turnover.prepare",
            "turnover.read",
        },
        "SELLER_COMPLIANCE_REVIEWER": _READ
        | _DOCUMENT_READ
        | {
            "document.manual_observation.review",
            "compliance.read",
            "compliance.facts.review",
            "compliance.case.resolve",
            "dispatch.release.approve",
            "compliance.case.comment",
            "compliance.hold.create",
            "compliance.hold.release.request",
            "compliance.hold.release.approve",
            "compliance.hold.review",
            "compliance.hold.raise",
            "dispatch.authorisation.revoke",
            "transport.evidence.review",
            "turnover.read",
            "turnover.review",
            "dispatch.packet.read",
        },
        "BUYER_COMPLIANCE_REVIEWER": _READ
        | {"compliance.read", "compliance.case.comment", "compliance.recipient.confirm"},
        "CARRIER_EVIDENCE_REVIEWER": {
            "document.read",
            "document.original.download",
            "organization.read",
            "consignment.read",
            "compliance.read",
            "transport.evidence.review",
        },
        "RULE_AUTHOR": {
            "organization.read",
            "regulation.read",
            "regulation.source.register",
            "regulation.pack.prepare",
            "regulation.pack.test",
        },
        "RULE_PUBLISHER": {
            "organization.read",
            "regulation.read",
            "regulation.pack.review",
            "regulation.pack.publish",
            "regulation.pack.suspend",
        },
    }
)
ROLE_PERMISSIONS["CARRIER_DISPATCHER"] |= {
    "compliance.read",
    "transport.evidence.prepare",
    "dispatch.packet.prepare",
    "dispatch.packet.read",
    "dispatch.authorisation.request",
    "document.review",
    "document.review.submit",
}
ROLE_PERMISSIONS["DRIVER"] |= {
    "compliance.read",
    "dispatch.packet.read",
    "dispatch.packet.acknowledge",
}
ROLE_PERMISSIONS["CARRIER_DISPATCHER"] |= {
    "document.read",
    "document.register",
    "document.version.add",
    "document.process",
    "document.review",
    "document.original.download",
}
ROLE_PERMISSIONS["DRIVER"] |= {"document.read"}

ROLE_PERMISSIONS.update(
    {
        "TRADE_PLANNER": _READ
        | {
            "tradetwin.read",
            "tradetwin.plan.prepare",
            "freight.rfq.prepare",
            "freight.rfq.publish",
            "tradetwin.run",
            "tradetwin.selection.prepare",
        },
        "TRANSPORT_PLAN_APPROVER": _READ | {"tradetwin.read", "tradetwin.plan.apply"},
        "FREIGHT_COST_PREPARER": _READ
        | {"tradetwin.read", "freight.price.read", "tradetwin.cost_assumptions.prepare"},
        "FREIGHT_PROCUREMENT_APPROVER": _READ
        | {
            "tradetwin.read",
            "freight.price.read",
            "tradetwin.cost_assumptions.review",
            "freight.commit.approve",
        },
        "ROUTING_DATA_PREPARER": {
            "organization.read",
            "routing.dataset.prepare",
            "routing.dataset.read",
        },
        "ROUTING_DATA_STEWARD": {
            "organization.read",
            "routing.dataset.read",
            "routing.dataset.review",
            "routing.dataset.publish",
        },
    }
)
ROLE_PERMISSIONS["CARRIER_DISPATCHER"] |= {
    "freight.rfq.invited.read",
    "freight.quote.prepare",
    "freight.quote.submit",
    "freight.offer.accept",
}
ROLE_PERMISSIONS["INTEGRATION_ADMINISTRATOR"] |= {"routing.provider.read"}

ROLE_PERMISSIONS.update(
    {
        "EVIDENCE_ANALYST": {
            "organization.read",
            "evidence.replay.request",
            "evidence.bundle.request",
        },
        "READINESS_OPERATOR": {
            "organization.read",
            "readiness.read",
            "readiness.run",
            "readiness.manual.prepare",
        },
        "QUALIFICATION_REVIEWER": {
            "organization.read",
            "readiness.read",
            "readiness.review",
            "pilot.scope.review",
        },
        "DEPLOYMENT_OPERATOR": {
            "organization.read",
            "readiness.read",
            "deployment.activate",
            "deployment.pause",
            "deployment.restore.rehearse",
            "pilot.scope.prepare",
        },
        "DEMO_PRESENTER": {
            "organization.read",
            "demo.read",
            "demo.workspace.create",
            "demo.run",
            "demo.clock.advance",
        },
    }
)
