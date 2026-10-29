"""Rule-based diet policy validation engine.

A policy is a JSON document: metadata + a list of declarative rules.
The engine totals a meal plan's nutrients, evaluates every rule, and returns
a structured, explainable compliance report.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

MEALS = ("breakfast", "lunch", "dinner", "snack")
SEVERITY_WEIGHT = {"critical": 5, "major": 3, "minor": 1}
STATUS_POINTS = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
WARN_RATIO = 0.9  # a max-rule is "near limit" at >= 90% of the limit
KCAL_PER_G = {"added_sugar_g": 4, "sat_fat_g": 9}


class PolicyError(ValueError):
    """The policy document is malformed."""


class UnknownFoodError(ValueError):
    """The plan references a food that is not in the food database."""


# ---------- helpers ----------

def _num(x: float) -> float:
    return round(x, 1)


def _scale(food: dict, nutrient: str, servings: float) -> float:
    return float(food.get(nutrient, 0)) * servings


def _items(plan: dict, foods: dict, meals: list[str] | None = None) -> list[dict]:
    """Flatten plan into items carrying their meal and the food record."""
    out = []
    for meal, entries in plan.items():
        if meals is not None and meal not in meals:
            continue
        for e in entries:
            f = foods.get(e["food_id"])
            if f is None:
                raise UnknownFoodError(f"Unknown food_id '{e['food_id']}' in {meal}")
            out.append({"meal": meal, "servings": e["servings"], "food": f})
    return out


def _total(items: list[dict], nutrient: str) -> float:
    return sum(_scale(i["food"], nutrient, i["servings"]) for i in items)


def _contributors(items: list[dict], nutrient: str, n: int = 3) -> list[dict]:
    agg: dict[str, float] = defaultdict(float)
    for i in items:
        agg[i["food"]["name"]] += _scale(i["food"], nutrient, i["servings"])
    top = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return [{"food": k, "amount": _num(v)} for k, v in top if v > 0]


def _scopes(rule: dict, plan: dict, foods: dict):
    """Yield (label, items) for each target the rule applies to."""
    if rule.get("scope", "day") == "day":
        yield "day", _items(plan, foods)
    else:
        for meal in rule.get("meals", MEALS):
            if plan.get(meal):  # empty meals are not applicable
                yield meal, _items(plan, foods, [meal])


def _check(label, actual, status, limit_text, items=None, nutrient=None, unit=""):
    c = {"target": label, "actual": _num(actual), "status": status,
         "limit": limit_text, "unit": unit}
    if status in ("fail", "warn") and items is not None and nutrient:
        c["contributors"] = _contributors(items, nutrient)
    return c


# ---------- rule evaluators: each returns a list of checks ----------

def r_nutrient_max(rule, plan, foods):
    n, lim, u = rule["nutrient"], rule["limit"], rule.get("unit", "")
    out = []
    for label, items in _scopes(rule, plan, foods):
        a = _total(items, n)
        st = "fail" if a > lim else "warn" if a >= lim * WARN_RATIO else "pass"
        out.append(_check(label, a, st, f"≤ {lim} {u}", items, n, u))
    return out


def r_nutrient_min(rule, plan, foods):
    n, lim, u = rule["nutrient"], rule["limit"], rule.get("unit", "")
    out = []
    for label, items in _scopes(rule, plan, foods):
        a = _total(items, n)
        out.append(_check(label, a, "pass" if a >= lim else "fail", f"≥ {lim} {u}", unit=u))
    return out


def r_nutrient_range(rule, plan, foods):
    n, lo, hi, u = rule["nutrient"], rule["min"], rule["max"], rule.get("unit", "")
    out = []
    for label, items in _scopes(rule, plan, foods):
        a = _total(items, n)
        st = "pass" if lo <= a <= hi else "fail"
        out.append(_check(label, a, st, f"{lo}–{hi} {u}", items if a > hi else None, n, u))
    return out


def r_kcal_percent_max(rule, plan, foods):
    n, lim = rule["nutrient"], rule["limit"]
    out = []
    for label, items in _scopes(rule, plan, foods):
        kcal = _total(items, "kcal")
        pct = (_total(items, n) * KCAL_PER_G[n] / kcal * 100) if kcal else 0
        st = "fail" if pct > lim else "warn" if pct >= lim * WARN_RATIO else "pass"
        out.append(_check(label, pct, st, f"≤ {lim} % of energy", items, n, "% kcal"))
    return out


def _group_servings(rule, plan, foods):
    return sum(i["servings"] for i in _items(plan, foods) if i["food"]["group"] == rule["group"])


def r_group_min(rule, plan, foods):
    a = _group_servings(rule, plan, foods)
    return [_check("day", a, "pass" if a >= rule["limit"] else "fail",
                   f"≥ {rule['limit']} servings", unit="servings")]


def r_group_max(rule, plan, foods):
    a = _group_servings(rule, plan, foods)
    return [_check("day", a, "pass" if a <= rule["limit"] else "fail",
                   f"≤ {rule['limit']} servings", unit="servings")]


def r_forbidden_tag(rule, plan, foods):
    banned = set(rule["tags"])
    hits = [i["food"]["name"] for i in _items(plan, foods) if banned & set(i["food"].get("tags", []))]
    c = {"target": "day", "actual": len(hits), "unit": "items",
         "status": "fail" if hits else "pass",
         "limit": "none tagged: " + ", ".join(sorted(banned))}
    if hits:
        c["contributors"] = [{"food": h, "amount": None} for h in sorted(set(hits))]
    return [c]


def r_required_meals(rule, plan, foods):
    missing = [m for m in rule["meals"] if not plan.get(m)]
    c = {"target": "day", "actual": len(rule["meals"]) - len(missing), "unit": "meals",
         "status": "fail" if missing else "pass",
         "limit": "all of: " + ", ".join(rule["meals"])}
    if missing:
        c["contributors"] = [{"food": f"missing {m}", "amount": None} for m in missing]
    return [c]


EVALUATORS: dict[str, Callable] = {
    "nutrient_max": r_nutrient_max,
    "nutrient_min": r_nutrient_min,
    "nutrient_range": r_nutrient_range,
    "kcal_percent_max": r_kcal_percent_max,
    "group_servings_min": r_group_min,
    "group_servings_max": r_group_max,
    "forbidden_tag": r_forbidden_tag,
    "required_meals": r_required_meals,
}


def validate_policy(policy: dict) -> None:
    for k in ("id", "name", "rules"):
        if k not in policy:
            raise PolicyError(f"Policy is missing '{k}'")
    seen = set()
    for r in policy["rules"]:
        for k in ("id", "title", "type", "severity"):
            if k not in r:
                raise PolicyError(f"Rule is missing '{k}': {r}")
        if r["type"] not in EVALUATORS:
            raise PolicyError(f"Rule {r['id']}: unknown type '{r['type']}'")
        if r["severity"] not in SEVERITY_WEIGHT:
            raise PolicyError(f"Rule {r['id']}: severity must be one of {list(SEVERITY_WEIGHT)}")
        if r["id"] in seen:
            raise PolicyError(f"Duplicate rule id {r['id']}")
        seen.add(r["id"])


# ---------- main entry point ----------

def evaluate(policy: dict, plan: dict, foods: dict) -> dict:
    validate_policy(policy)
    plan = {m: v for m, v in plan.items() if v}
    day_items = _items(plan, foods)
    totals = {n: _num(_total(day_items, n)) for n in
              ("kcal", "sodium_mg", "carbs_g", "fiber_g", "added_sugar_g", "sat_fat_g",
               "protein_g", "potassium_mg")}
    results, earned, possible = [], 0.0, 0.0
    for rule in policy["rules"]:
        checks = EVALUATORS[rule["type"]](rule, plan, foods)
        if not checks:
            status = "na"
        else:
            sts = {c["status"] for c in checks}
            status = "fail" if "fail" in sts else "warn" if "warn" in sts else "pass"
        if status != "na":
            w = SEVERITY_WEIGHT[rule["severity"]]
            possible += w
            earned += w * STATUS_POINTS[status]
        results.append({"rule_id": rule["id"], "title": rule["title"],
                        "severity": rule["severity"], "status": status,
                        "evidence": rule.get("evidence", ""), "checks": checks})
    blocking = [r for r in results if r["status"] == "fail" and r["severity"] in ("critical", "major")]
    soft = [r for r in results if r["status"] in ("fail", "warn")]
    verdict = "NON_COMPLIANT" if blocking else "COMPLIANT_WITH_WARNINGS" if soft else "COMPLIANT"
    return {
        "policy": {"id": policy["id"], "name": policy["name"]},
        "verdict": verdict,
        "score": round(earned / possible * 100) if possible else 100,
        "summary": {s: sum(1 for r in results if r["status"] == s) for s in ("pass", "warn", "fail")},
        "totals": totals,
        "results": results,
    }
