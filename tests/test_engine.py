import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, FOODS, POLICIES, SAMPLES
from app.engine import evaluate, PolicyError, UnknownFoodError

client = TestClient(app)


def plan(**m):
    return {k: [{"food_id": f, "servings": s} for f, s in v] for k, v in m.items()}


def test_samples_match_expected_verdicts():
    expected = ["COMPLIANT", "COMPLIANT", "NON_COMPLIANT"]
    for s, exp in zip(SAMPLES, expected):
        r = evaluate(POLICIES[s["policy_id"]], s["plan"], FOODS)
        assert r["verdict"] == exp, (s["name"], [x for x in r["results"] if x["status"] != "pass"])


def test_sodium_limit_fails_and_names_contributors():
    p = plan(lunch=[("canned_soup", 2), ("ham", 1)])
    r = evaluate(POLICIES["low-sodium"], p, FOODS)
    day = next(x for x in r["results"] if x["rule_id"] == "NA-DAY")
    assert day["status"] == "fail" and day["checks"][0]["actual"] == 2630
    assert day["checks"][0]["contributors"][0]["food"] == "Canned soup, regular"
    assert r["verdict"] == "NON_COMPLIANT"


def test_near_limit_is_warning_not_failure():
    # 1,800 mg is 90% of the 2,000 mg limit -> warn
    pol = {"id": "t", "name": "t", "rules": [{"id": "A", "title": "a", "type": "nutrient_max",
           "severity": "critical", "nutrient": "sodium_mg", "limit": 2000}]}
    r = evaluate(pol, plan(lunch=[("ham", 1), ("canned_soup", 1)]), FOODS)  # 1,840
    assert r["results"][0]["status"] == "warn" and r["verdict"] == "COMPLIANT_WITH_WARNINGS"


def test_empty_meal_is_not_applicable_for_meal_rules():
    r = evaluate(POLICIES["diabetic"], plan(breakfast=[("oatmeal", 1), ("banana", 1), ("egg", 1)]), FOODS)
    snack = next(x for x in r["results"] if x["rule_id"] == "CARB-SNACK")
    assert snack["status"] == "na"


def test_forbidden_tag_critical():
    r = evaluate(POLICIES["diabetic"], plan(lunch=[("soda", 1)]), FOODS)
    ssb = next(x for x in r["results"] if x["rule_id"] == "SSB")
    assert ssb["status"] == "fail" and r["verdict"] == "NON_COMPLIANT"


def test_unknown_food_and_bad_policy():
    with pytest.raises(UnknownFoodError):
        evaluate(POLICIES["dga-2020"], plan(lunch=[("nope", 1)]), FOODS)
    with pytest.raises(PolicyError):
        evaluate({"id": "x", "name": "x", "rules": [{"id": "1", "title": "t", "type": "magic", "severity": "minor"}]}, {}, FOODS)


def test_api_validate_and_errors():
    body = {"policy_id": "low-sodium", "plan": plan(lunch=[("chicken", 1)])}
    r = client.post("/api/validate", json=body)
    assert r.status_code == 200 and "verdict" in r.json()
    assert client.post("/api/validate", json={**body, "policy_id": "zzz"}).status_code == 404
    assert client.post("/api/validate", json={"policy_id": "dga-2020", "plan": {"brunch": []}}).status_code == 422
    assert client.post("/api/validate", json={"policy_id": "dga-2020", "plan": plan(lunch=[("nope", 1)])}).status_code == 422
    assert client.post("/api/validate", json={"policy_id": "dga-2020", "plan": {"lunch": [{"food_id": "egg", "servings": -1}]}}).status_code == 422


def test_inline_policy_overrides_id():
    pol = {"id": "custom", "name": "Custom", "rules": [{"id": "K", "title": "kcal", "type": "nutrient_max",
           "severity": "minor", "nutrient": "kcal", "limit": 100}]}
    r = client.post("/api/validate", json={"policy": pol, "plan": plan(lunch=[("chicken", 1)])}).json()
    assert r["policy"]["id"] == "custom" and r["results"][0]["status"] == "fail"
