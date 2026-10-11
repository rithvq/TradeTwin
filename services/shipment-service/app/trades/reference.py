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
