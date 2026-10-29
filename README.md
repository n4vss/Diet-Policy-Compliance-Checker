# Evidence-Based Policy Rule Engine

A rule-based compliance validator for institutional and national diet policies.
Policies are declarative JSON; the FastAPI backend evaluates a meal plan against them
and returns an explainable report (per-rule status, actual vs limit, main contributing foods, evidence basis).

## Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000   (API docs: /docs)
pytest            # run the test suite
```

## Structure
- `app/engine.py` – rule evaluators, scoring, verdict logic
- `app/main.py` – REST API (`/api/policies`, `/api/foods`, `/api/validate`, `/api/samples`)
- `app/data/policies/*.json` – codified policies: low-sodium (2 g Na), diabetic (consistent carbohydrate), US DGA 2020–2025
- `app/data/foods.json` – food database (approximate per-serving values; replace with USDA FoodData Central for production)
- `static/` – web UI

## Rule types
`nutrient_max`, `nutrient_min`, `nutrient_range` (scope `day` or `meal`), `kcal_percent_max`,
`group_servings_min/max`, `forbidden_tag`, `required_meals`.
Each rule has an `id`, `title`, `severity` (critical/major/minor) and an `evidence` citation.

## Verdicts
- **NON_COMPLIANT** – any critical or major rule fails
- **COMPLIANT_WITH_WARNINGS** – only minor failures, or a max-limit is within 10%
- **COMPLIANT** – all applicable rules pass
Score = severity-weighted share (critical 5, major 3, minor 1; pass 1, near-limit 0.5, fail 0).

## Add a policy
Drop a new JSON file in `app/data/policies/` (or paste JSON into the UI / send it inline to `POST /api/validate`).

## Example
```bash
curl -X POST localhost:8000/api/validate -H 'content-type: application/json' -d \
'{"policy_id":"low-sodium","plan":{"lunch":[{"food_id":"canned_soup","servings":2}]}}'
```
> Educational prototype. Thresholds are simplified from published guidance; confirm against your institution's current diet manual.
