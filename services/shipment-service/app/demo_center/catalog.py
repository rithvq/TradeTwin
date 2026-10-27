VERSION = "INTEGRATED_INDIA_FREIGHT_V1"
STAGES = {"DEMO_SETUP", "DEMO_STEP"}
STEPS = [
    {
        "code": "CORRIDOR_CHANGE",
        "label": "Review a road restriction and compare alternatives",
        "actor": "Simulation source author and independent reviewer",
    },
    {
        "code": "ACCEPT_FREIGHT",
        "label": "Approve the freight offer and assign its route",
        "actor": "Simulation payer approver and carrier dispatcher",
    },
    {
        "code": "PICKUP_RELEASE",
        "label": "Review evidence and authorise pickup",
        "actor": "Simulation preparer, independent reviewer and assigned driver",
    },
    {
        "code": "PICKUP",
        "label": "Record pickup and consume its authorisation",
        "actor": "Simulation assigned driver",
    },
    {
        "code": "DEPARTURE_RELEASE",
        "label": "Evaluate and authorise departure separately",
        "actor": "Simulation preparer, independent reviewer and assigned driver",
    },
    {
        "code": "DEPART",
        "label": "Record departure and consume its authorisation",
        "actor": "Simulation assigned driver",
    },
    {
        "code": "RECEIVE",
        "label": "Record arrival, receipt and goods inspection",
        "actor": "Simulation assigned driver, buyer receiver and inspector",
    },
    {
        "code": "PAYMENT",
        "label": "Record and allocate a declared payment",
        "actor": "Simulation buyer and seller finance; no bank verification",
    },
]
