# Cross-Border Ecommerce Agent-as-Tool Contracts

This project keeps the cross-border workflow as the orchestrator and exposes
important capabilities as stable tools. The goal is not to make one giant agent
handle every ecommerce decision. Each tool owns one bounded decision, returns
structured output, and can later swap its internal runtime without changing the
workflow contract.

## Why Split These Tools

The end-to-end workflow currently runs:

```text
public/mock Amazon data
-> product research
-> listing generation
-> compliance check
-> ads diagnostic
-> customer service
-> action gate
```

The first Agent-as-Tool split focuses on three high-value capabilities:

- `crossborder.product_research`: decide whether a product candidate is worth
  continuing.
- `crossborder.listing_generation`: turn product facts and keyword hints into a
  platform-aware listing draft.
- `crossborder.ads_diagnostic`: diagnose ad metrics and propose gated actions.

Each tool returns a common envelope:

```json
{
  "decision": "pass",
  "human_review_required": false,
  "confidence": 0.86,
  "result": {},
  "errors": [],
  "audit": {
    "tool_name": "crossborder.product_research",
    "workflow_id": "wf_123",
    "seller_id": "seller_123",
    "runtime": "deterministic_rules",
    "version": "product-research-tool-v1",
    "input_hash": "...",
    "created_at": "2026-06-20T12:00:00Z",
    "trace_id": "rsch_..."
  }
}
```

The workflow should consume only stable fields:

```text
decision
human_review_required
confidence
result
errors
audit
```

## Product Research Tool

HTTP endpoint:

```text
POST /tools/crossborder/product-research
```

Python callable:

```python
from crossborder.tools_agent.product_research_tool import run_product_research_tool
```

CLI:

```bash
python -m crossborder.tools_agent.product_research_tool examples/crossborder/tools/product_research_tool.json
```

Input includes:

```text
platform, market, workflow_id, seller_id,
product, competitors, pain_points, cost_model,
logistics, compliance_precheck, target_price,
landed_cost, monthly_search_volume, competitor_count,
avg_rating, metadata
```

Internal runtime:

```text
crossborder.product_research.research_product()
```

Current logic is deterministic and explainable:

```text
final_score =
  demand * 25%
+ profitability * 25%
+ competition * 20%
+ logistics * 15%
+ compliance * 15%
```

Output result includes:

```text
score
opportunity_level
score_breakdown
selected_candidate
candidate_ranking
pain_points
selection_rationale
issues
suggestions
```

Failure mode:

Invalid input returns `decision = failed`, `human_review_required = true`, and
structured `errors`; it does not raise raw validation errors to callers.

## Listing Generation Tool

HTTP endpoint:

```text
POST /tools/crossborder/listing-generate
```

Python callable:

```python
from crossborder.tools_agent.listing_generation_tool import run_listing_generation_tool
```

CLI:

```bash
python -m crossborder.tools_agent.listing_generation_tool examples/crossborder/tools/listing_generation_tool.json
```

Input includes:

```text
platform, market, workflow_id, seller_id,
product, keyword_hints, pain_points,
compliance_constraints, metadata
```

Internal runtime:

```text
crossborder.listing_agent.generate_listing_tool()
```

Current logic is a deterministic template:

```text
title = brand + product title + first 3 features
bullets = product features or claims, capped by platform policy
search_terms = category + keyword_hints + pain point topics + features + materials
```

For Amazon US, platform constraints currently include:

```text
title <= 180 chars
bullet <= 220 chars
bullet_count = 5
search_terms <= 12
description <= 2000 chars
```

Output result includes:

```text
listing
platform_constraints
issues
suggestions
source_fields_used
```

## Ads Diagnostic Tool

HTTP endpoint:

```text
POST /tools/crossborder/ads-diagnostic
```

Python callable:

```python
from crossborder.tools_agent.ads_diagnostic_tool import run_ads_diagnostic_tool
```

CLI:

```bash
python -m crossborder.tools_agent.ads_diagnostic_tool examples/crossborder/tools/ads_diagnostic_tool.json
```

Input includes:

```text
platform, market, workflow_id, seller_id, asin,
campaigns, target_acos, min_clicks_for_conversion_judgment,
listing_context, margin_context, permissions, metadata
```

Internal runtime:

```text
crossborder.ads.diagnostic_agent.diagnose_ads()
```

Current metrics are deterministic:

```text
CTR = clicks / impressions
CVR = orders / clicks
ACOS = spend / sales
ROAS = sales / spend
CPC = spend / clicks
CPA = spend / orders
```

Current diagnostic rules include:

```text
CTR < 0.3% with enough impressions -> low_ctr
enough clicks with no orders -> no_conversion
CVR < 4% with enough clicks -> low_cvr
ACOS > target_acos * 1.3 -> high_acos
spend with no sales -> wasted_spend
```

Output result includes:

```text
metrics
issues
recommendations
suggested_actions
gated_actions
risk_level
```

Suggested actions such as `pause_campaign` or `add_negative_keyword` are routed
through Action Gate. They are not executed directly by this tool.

## Relationship To Workflow

The workflow remains the orchestrator:

```text
Workflow
  -> calls Product Research Tool
  -> calls Listing Generation Tool
  -> calls Compliance Tool
  -> calls Ads Diagnostic Tool
  -> calls Customer Service Tool
  -> routes risky suggested actions through Action Gate
```

The tool should not:

```text
publish listings
change prices
pause campaigns
refund orders
compensate buyers
submit appeals
delete listings
```

Those are external side effects and must go through workflow permissions,
Action Gate, and often human approval.

## Future Runtime Replacement

The contract is stable even if internals change:

```text
deterministic rules -> LLM
deterministic templates -> LLM listing copywriter
local mock data -> Keepa / Amazon SP-API / Helium10 / Jungle Scout
keyword rules -> Keyword Research Agent
static compliance terms -> Compliance RAG / MCP policy service
```

Callers should not depend on internal formulas. They should depend on the
envelope, `decision`, `result`, `errors`, and `audit`.

## Examples

Example payloads:

```text
examples/crossborder/tools/product_research_tool.json
examples/crossborder/tools/listing_generation_tool.json
examples/crossborder/tools/ads_diagnostic_tool.json
```

These examples are intentionally offline and deterministic so that tests and
interview demos can run without live marketplace credentials.
