"""FastAPI backend: policy catalogue + meal plan compliance validation."""
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import MEALS, PolicyError, UnknownFoodError, evaluate, validate_policy

ROOT = Path(__file__).parent
DATA = ROOT / "data"

FOODS = {f["id"]: f for f in json.loads((DATA / "foods.json").read_text())}
POLICIES = {}
for p in sorted((DATA / "policies").glob("*.json")):
    doc = json.loads(p.read_text())
    validate_policy(doc)  # fail fast at startup on a bad policy file
    POLICIES[doc["id"]] = doc
SAMPLES = json.loads((DATA / "samples.json").read_text())

app = FastAPI(title="Evidence-Based Policy Rule Engine", version="1.0.0")


class PlanItem(BaseModel):
    food_id: str
    servings: float = Field(1, gt=0, le=20)


class ValidateRequest(BaseModel):
    policy_id: Optional[str] = None
    policy: Optional[dict] = Field(None, description="Inline policy; overrides policy_id")
    plan: dict[str, list[PlanItem]]


@app.get("/api/health")
def health():
    return {"status": "ok", "policies": len(POLICIES), "foods": len(FOODS)}


@app.get("/api/foods")
def list_foods():
    return list(FOODS.values())


@app.get("/api/policies")
def list_policies():
    return [{"id": p["id"], "name": p["name"], "description": p.get("description", ""),
             "rule_count": len(p["rules"])} for p in POLICIES.values()]


@app.get("/api/policies/{policy_id}")
def get_policy(policy_id: str):
    if policy_id not in POLICIES:
        raise HTTPException(404, f"Unknown policy '{policy_id}'")
    return POLICIES[policy_id]


@app.get("/api/samples")
def samples():
    return SAMPLES


@app.post("/api/validate")
def validate(req: ValidateRequest):
    bad = [m for m in req.plan if m not in MEALS]
    if bad:
        raise HTTPException(422, f"Unknown meal(s) {bad}; use {list(MEALS)}")
    policy = req.policy
    if policy is None:
        if req.policy_id not in POLICIES:
            raise HTTPException(404, f"Unknown policy '{req.policy_id}'")
        policy = POLICIES[req.policy_id]
    plan = {m: [i.model_dump() for i in items] for m, items in req.plan.items()}
    try:
        return evaluate(policy, plan, FOODS)
    except (PolicyError, UnknownFoodError) as e:
        raise HTTPException(422, str(e))


app.mount("/static", StaticFiles(directory=ROOT.parent / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT.parent / "static" / "index.html")
