PLANS = {
    "starter": {"label": "Starter", "limit": 500, "price_mxn": 999},
    "business": {"label": "Business", "limit": 2500, "price_mxn": 2499},
    "pro": {"label": "Pro", "limit": 8000, "price_mxn": 4999},
}


def get_plan_limit(plan: str) -> int:
    return PLANS.get(plan, PLANS["business"])["limit"]


def get_plan_label(plan: str) -> str:
    return PLANS.get(plan, PLANS["business"])["label"]
