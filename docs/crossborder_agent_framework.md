# 跨境电商多 Agent 框架记录

本文记录当前项目的 Agent 架构共识，用于指导后续开发选型和模块拆分。

## 1. 总体架构

本项目不采用“一个大模型从头做到尾”的模式，而采用：

```text
CrossBorder Orchestrator
        |
        +-- Agent-as-Tool 层
        |     +-- Product Research Agent
        |     +-- Listing Agent
        |     +-- Compliance Agent
        |     +-- Ads Diagnostic Agent
        |     +-- Customer Service Agent
        |
        +-- Deterministic Tool 层
        |     +-- Cost Calculator
        |     +-- Inventory Checker
        |     +-- Order Query
        |     +-- Ads Metrics Query
        |     +-- Asset Downloader
        |     +-- Platform Rule Engine
        |
        +-- Workflow / Gate 层
              +-- Human Review
              +-- Permission Control
              +-- Publish Gate
              +-- Audit Log
```

核心原则：

```text
规则管流程，工具管事实，Agent 管判断，Workflow 管执行。
```

## 2. 模块边界

| 模块 | 类型 | 推荐形态 | 说明 |
|---|---|---|---|
| CrossBorder Orchestrator | Workflow / 主编排 | Python workflow + HTTP/MCP 对外入口 | 决定阶段、调用工具、路由状态，不直接做所有判断 |
| Product Research Agent | Agent-as-Tool | Agent + 数据工具 + 打分规则 | 选品机会评估、趋势、竞品、评论痛点、风险综合判断 |
| Listing Agent | Agent-as-Tool | Agent + 平台模板 + 合规 Tool | 标题、卖点、描述、关键词、本地化表达 |
| Compliance Agent | Agent-as-Tool | 规则库 + RAG + 多专家 + 审计 | 广告法、平台政策、图片文字、证照核验、资质判断 |
| Ads Diagnostic Agent | 部分 Agent-as-Tool | SQL/workflow 算指标，Agent 做诊断建议 | ACOS/CTR/CVR 等确定性计算不用 Agent |
| Customer Service Agent | 受控 Agent-as-Tool | 分类、总结、拟回复；高风险动作人审 | 退款、赔偿、承诺交期不能默认自动执行 |
| Cost / Inventory / Orders / Reports | Deterministic Tools | SQL / API / 规则引擎 | 成本、库存、履约、基础报表优先确定性系统 |

## 3. 统一 Tool Contract

每个 Agent-as-Tool 都应提供稳定输入输出，便于 Orchestrator 编排。

输入建议：

```json
{
  "task_type": "listing_generation",
  "input": {},
  "context": {
    "platform": "amazon",
    "market": "US",
    "seller_id": "seller_001",
    "workflow_id": "wf_123"
  },
  "caller": {
    "agent": "CrossBorderOrchestrator"
  }
}
```

输出建议：

```json
{
  "decision": "pass | requires_revision | requires_human_review | blocked",
  "confidence": 0.85,
  "issues": [],
  "suggestions": [],
  "artifacts": {},
  "human_review_required": false,
  "audit": {
    "tool": "listing.generate",
    "check_id": "chk_123",
    "workflow_id": "wf_123",
    "model": "model-name",
    "created_at": "2026-06-20T00:00:00Z"
  }
}
```

Orchestrator 默认只消费这些字段：

```text
decision
issues
suggestions
artifacts
human_review_required
audit
```

## 4. 接入方式

同一能力可以通过三种方式暴露：

```text
内部开发 / 单体 workflow     -> Python function
普通业务系统 / 后端服务       -> HTTP API
外部 Agent 平台 / IDE / 编排器 -> MCP Tool
```

当前项目已具备：

```text
Compliance Agent-as-Tool
  - HTTP API
  - MCP Server
  - image_urls / file_url 下载
  - SQLite 审计
  - Web 看板

CrossBorder MVP
  - Amazon-first Listing workflow
  - End-to-end demo pipeline
  - Product Research MVP
  - Listing Generation Tool
  - Platform policy preflight
  - Compliance Tool 调用
  - Ads Diagnostic Tool
  - Customer Service Tool
  - Action Gate
  - Stage framework
  - HTTP endpoint
  - MCP tool
```

## 4.0 End-to-End Demo Pipeline

当前新增一键 demo：

```text
CLI: python scripts/demo_crossborder_pipeline.py
Output: examples/crossborder/demo_pipeline_result.json
```

面试讲解版文档：

```text
docs/crossborder_demo_walkthrough.md
```

它把已经完成的 Agent-as-Tool 能力串成完整链路：

```text
Amazon public fixture data
  -> Data Intake
  -> Product Research v2
  -> Listing Generation
  -> Compliance Check
  -> Ads Diagnostic
  -> Customer Service
  -> Action Gate Summary
```

这个 demo 的设计目标不是自动发布商品，而是展示跨境电商 Agent 框架的边界：

```text
Agent 做判断、生成、诊断、草拟；
Tool 做事实查询、指标计算、结构化转换；
Workflow/Gate 做权限控制、人审和高风险动作拦截。
```

报告包含：

```text
demo                     平台、市场、workflow_id
stages.data_intake       公开数据清洗覆盖率和补齐报告
stages.product_research  选品五维评分
stages.listing_generation Listing 草稿
stages.compliance_check  合规结构化决策
stages.ads_diagnostic    广告指标诊断和 gated_actions
stages.customer_service  客服意图、回复草稿和 gated_actions
gate_summary             所有动作的 gate 结果汇总
final_summary            面试/演示用的一页结论
```

典型输出结论：

```text
product_research_decision = pass
listing_compliance_decision = pass
ads_decision = requires_human_review
customer_service_decision = requires_human_review
ready_for_publish = true
human_review_required = true
```

这表示：

```text
商品和 Listing 可以进入发布准备；
但广告和客服里的高风险动作被 Action Gate 拦截，需要人审。
```

## 4.1 当前 Stage Pipeline

跨境电商主流程已经按阶段拆开，每个阶段都标注运行形态：

| Stage | 类型 | 当前实现 | 后续演进 |
|---|---|---|---|
| intake | rule_only | 归一化 workflow/product metadata | 接上游商品资料、店铺上下文 |
| product_research | rule_first_agent_fallback | 需求、利润、竞争、物流、合规五维评分 | 接趋势、竞品、评论痛点、侵权风险 Agent |
| category | rule_first_agent_fallback | 关键词规则判断类目族 | 接选品/类目 Agent 做复杂分类 |
| listing | agent_required | 确定性模板生成 Listing | 替换为 Listing Agent-as-Tool |
| platform_rules | rule_only | 平台长度、bullet、关键词、风险词预检 | 按 Amazon/Temu/Walmart 深化规则 |
| assets | rule_only | 收集图片/证照 URL/path | 下载、OCR、去重、素材质量检查 |
| compliance | tool_call | 调用合规 Agent-as-Tool | 可通过 Python/HTTP/MCP 切换 |
| rewrite | agent_required | 根据合规建议自动改写一次 | 接 Listing Rewrite Agent |
| publish_gate | gate | 映射 ready/revision/human/block | 接人审、发布权限、平台 API |

当前原则：

```text
Stage 只编排，不隐藏高风险动作；
Agent 只生成/判断/建议，不直接发布；
Publish Gate 决定能否进入后续 workflow。
```

## 4.2 Product Research Tool

当前新增选品 Tool：

```text
Python: crossborder.product_research.research_product()
HTTP:   POST /tools/crossborder/product-research
MCP:    crossborder_product_research
CLI:    python src/crossborder/product_research.py examples/crossborder/product_research_cable_organizer.json
```

第一版不抓真实平台数据，先用上游传入的结构化信号做稳定评分：

```text
demand              monthly_search_volume + review_pain_points
profitability       target_price - landed_cost
competition         competitor_count + avg_rating
logistics           weight_kg / oversized / fragile / battery / liquid
compliance          claims/title/category 风险词预检
```

Amazon-first v2 数据入口已经扩展为：

```text
competitors[]        ASIN、价格、评分、评论数、估算月销量、BSR、Prime、卖家数、listing 质量、优劣势
pain_points[]        评论痛点 topic、频次、严重度、例句、来源 ASIN
cost_model           unit_cost、头程、关税、包装、Amazon referral/FBA/仓储/广告/退货/其他成本
logistics            重量、尺寸、oversized、fragile、battery、liquid、hazmat、meltable
compliance_precheck  商标、专利、受限类目、证书、医疗/农药/儿童产品风险
```

Amazon 选品的阶段边界：

```text
Product Data Intake
  -> 结构化接收 Amazon 市场数据，不在这里做主观判断

Metrics / Rule Layer
  -> 需求、利润、竞争、物流、合规五维确定性评分

Agent Judgment Layer（后续）
  -> 解释为什么值得做/不值得做，提炼差异化切入点和产品改良点

Workflow Gate
  -> pass / requires_revision / requires_human_review / blocked
```

注意：Amazon referral fee、FBA fee、仓储费、广告 CPA、退货成本会变化，当前不硬编码平台费率；优先由上游数据源或费用计算工具传入 `cost_model`。后续可以单独做 `amazon_fee_estimator`，但它也应该是可配置版本规则，不要散落在选品 Agent 里。

### Public Dataset Loader

当前新增本地公开数据 loader：

```text
Python: crossborder.data_intake.amazon_reviews_2023_loader.build_product_research_request()
CLI:    python src/crossborder/data_intake/amazon_reviews_2023_loader.py --meta ... --reviews ... --keyword ...
```

常用 CLI：

```text
--run-research   转换公开数据后，立即调用 product_research v2
--output FILE    保存 JSON 输出，便于后续 workflow 或人工检查
```

它读取 Amazon Reviews 2023 / McAuley 风格 JSONL：

```text
meta_*.jsonl     parent_asin、title、price、average_rating、rating_number、categories、features、description、images、details
review *.jsonl   parent_asin、asin、rating、title、text、verified_purchase
```

并转换成选品 v2 输入：

```text
competitors[]        由 metadata + review 聚合生成
pain_points[]        从低分评论关键词聚合生成
cost_model           由 unit_cost + target_price 简单估算，后续应由费用工具替换
logistics            从 details/title/description 做轻量解析
compliance_precheck  从标题/类目/描述做风险词预检
data_intake_report   记录清洗覆盖率、缺失字段、推断字段和风险提示
```

`data_intake_report` 用来区分原始字段和补齐字段：

```text
missing_fields    price / average_rating / review_count / images / features / weight / unit_cost
inferred_fields   target_price_from_competitor_median / estimated_monthly_sales_from_review_count / fee estimates
warnings          没有评论、缺 unit_cost、无法解析重量、可能需要证书等
```

重要限制：

```text
公开数据不是实时 Amazon 数据；
estimated_monthly_sales 是离线测试代理值，不是真实销量；
FBA/referral/广告/退货成本目前是粗估或上游传入；
这个 loader 用于低成本验证数据链路，不用于生产决策。
```

输出稳定字段：

```text
decision
opportunity_level
score
score_breakdown
issues
suggestions
human_review_required
audit.research_id
```

在 Listing workflow 中，`product_research` 目前是 advisory stage：它会写入 `stage_results` 和 `notes`，但不会直接阻断 Listing 生成。真正选品决策应由外部 workflow 调用 `crossborder_product_research`，再决定是否进入 Listing 工作流。

## 4.3 Listing Generation Tool

当前新增 Listing Tool：

```text
Python: crossborder.listing_agent.generate_listing_tool()
HTTP:   POST /tools/crossborder/generate-listing
MCP:    crossborder_generate_listing_draft
CLI:    python src/crossborder/listing_agent.py examples/crossborder/listing_generation_massager.json
```

第一版仍使用确定性模板，不强依赖 LLM：

```text
title         brand + product title + top features
bullets       features / materials / audience
description   practical-use intro + bullet details
search_terms  category + keyword_hints + features + materials
```

输出稳定字段：

```text
decision
listing
confidence
issues
suggestions
human_review_required
audit.listing_id
```

在完整 Listing workflow 中，`listing` stage 已经通过 Listing Tool 生成草稿，并把 `listing_id/runtime/confidence` 写入 `stage_results`。后续如果切到 OpenAI Agents SDK，只需要替换 `generate_listing_tool()` 内部实现，HTTP/MCP/workflow contract 不变。

## 4.4 Ads Diagnostic + Action Gate

当前新增广告诊断 Tool：

```text
Python: crossborder.ads.diagnostic_agent.diagnose_ads()
HTTP:   POST /tools/crossborder/ads/diagnose
MCP:    crossborder_ads_diagnose
CLI:    python src/crossborder/ads/diagnostic_agent.py examples/crossborder/ads_diagnostic_bad_acos.json
```

广告诊断先做确定性指标计算：

```text
CTR  = clicks / impressions
CVR  = orders / clicks
ACOS = spend / sales
ROAS = sales / spend
CPC  = spend / clicks
CPA  = spend / orders
```

再判断问题：

```text
no_clicks       有曝光没点击
low_ctr         点击率低
no_conversion   有点击没订单
low_cvr         转化率低
high_acos       ACOS 高于目标
wasted_spend    花费产生但无销售
```

诊断结果会生成 `suggested_actions`，并自动进入 Action Gate：

```text
Ads Diagnostic
  -> suggested_actions
  -> Action Gate
  -> gated_actions
```

这意味着 Agent 可以建议：

```text
add_negative_keyword
pause_campaign
monitor_campaign
```

但外部系统应只消费 `gated_actions`：

```text
allowed=true                  可以由 workflow 自动继续
requires_human_review=true    需要人工批准
blocked                       Agent 不允许自主执行
```

当前新增 Action Gate：

```text
Python: crossborder.action_gate.evaluate_action_gate()
HTTP:   POST /tools/crossborder/action-gate
MCP:    crossborder_action_gate
```

高风险动作默认不会自动执行：

```text
publish_listing
change_price
increase_budget
refund_order
compensate_buyer
promise_delivery_date
submit_appeal
delete_listing
```

核心边界：

```text
Agent 负责诊断和建议；
Action Gate 负责权限和人审；
真正执行由外部 workflow / backend 完成。
```

## 4.5 Customer Service Tool + Action Gate

当前新增客服 Tool：

```text
Python: crossborder.customer_service.agent.respond_to_customer()
HTTP:   POST /tools/crossborder/customer-service/respond
MCP:    crossborder_customer_service_respond
CLI:    python src/crossborder/customer_service/agent.py examples/crossborder/customer_refund_request.json
```

客服 Agent 做三件事：

```text
intent      refund_request / return_request / delivery_delay / product_issue / cancel_request / negative_feedback / general_question
sentiment   positive / neutral / negative
draft_reply 只生成回复草稿，不直接承诺高风险事项
```

然后把动作建议送进 Action Gate：

```text
Customer Service Agent
  -> draft_reply
  -> suggested_actions
  -> Action Gate
  -> gated_actions
```

低风险动作：

```text
request_order_info
```

受控动作：

```text
send_reply           需要 customer_message 权限
refund_order         默认人审
compensate_buyer     默认人审
promise_delivery_date 默认人审
```

核心边界：

```text
Agent 可以分类、总结、草拟回复；
不能擅自退款、赔偿、承诺交期；
外部系统只应执行 gated_actions.allowed=true 的动作。
```

## 5. 技术选型建议

### 当前默认：保留现有 Strands + FastAPI + MCP

继续沿用当前技术栈作为主线：

```text
Strands Agents SDK   -> 当前合规多专家/视觉/文本专家已接入
FastAPI              -> HTTP Tool API 和看板后端
MCP Python SDK       -> 对外 Agent-as-Tool 接入层
Pydantic             -> 输入/输出合同
SQLite               -> MVP 审计和 demo 存储
React                -> 本地看板
```

理由：

```text
1. 现有合规 Agent 已经跑通，不应为了选型重写核心能力。
2. FastAPI + MCP 已经能同时服务业务系统和外部 Agent 平台。
3. Pydantic schema 已经成为 Tool Contract 的事实标准。
4. 当前阶段更重要的是阶段拆分、权限、人审和审计，而不是替换 Agent SDK。
```

### OpenAI SDK / Agents SDK：建议做并行 spike，不立即替换

OpenAI 官方文档建议：

```text
Responses API: 适合一次模型调用 + 工具 + 应用自己掌握逻辑。
Agents SDK: 适合应用自己掌握 orchestration、tool execution、approvals、state。
```

本项目长期形态符合 Agents SDK 的目标：多专家、工具调用、审批、人审、状态、MCP、可观测。但当前已有 Strands 实现，因此建议：

```text
短期：保留 Strands 主线
中期：新增 OpenAI Agents SDK spike 分支/模块
长期：如果 tracing、handoff、guardrails、MCP 集成体验明显优于现有实现，再迁移核心 Agent runtime
```

Spike 范围建议：

```text
1. 用 OpenAI Agents SDK 重写一个最小 Listing Agent
2. 调用现有 compliance MCP tool
3. 输出同一套 CrossBorderResult schema
4. 对比 Strands 版本的复杂度、可观测性、成本、稳定性
```

不要在 spike 中改动现有合规核心。

## 6. 多框架混用的风险控制

后期可以根据不同 Agent 场景选择不同 AI runtime，但不同框架只能藏在 Agent-as-Tool 内部，不能泄漏到主 workflow。

推荐边界：

```text
CrossBorder Workflow
        |
        v
AgentTool Adapter Interface
        |
        +-- StrandsComplianceAdapter
        +-- OpenAIListingAdapter
        +-- LangGraphResearchAdapter
        +-- CustomerServiceAdapter
        |
        v
统一 AgentToolResult
```

主 workflow 永远只认识：

```python
AgentTool.run(input) -> AgentToolResult
```

主 workflow 不直接依赖：

```text
Strands Agent
OpenAI Agent
LangGraph StateGraph
```

### 容易出 bug 的地方

| 风险 | 表现 | 约束 |
|---|---|---|
| 输入输出不一致 | 不同框架返回 `verdict/status/decision` 等不同字段 | 所有 Agent-as-Tool 适配为统一 result schema |
| 状态污染 | 框架 memory/thread state 导致结果不可复现 | 默认无状态，所有上下文显式传入 |
| 错误格式不一致 | 有的抛异常，有的返回空文本，有的返回 error | 统一 `error.code/message`，失败默认进入人审或 failed |
| 权限不一致 | Agent 自动调用高风险工具 | Agent-as-Tool 默认只 analyze/suggest，execute 走 workflow gate |
| 审计不一致 | Strands/OpenAI/LangGraph trace 分散 | 统一写项目自己的 audit log |
| 依赖冲突 | 多框架版本、环境变量、provider 配置冲突 | 每个 runtime 放 adapter，必要时拆服务 |

### 统一 AgentToolResult

所有 Agent-as-Tool 最终都应映射成同一类结果：

```json
{
  "tool_name": "listing.generate",
  "runtime": "openai_agents_sdk",
  "decision": "pass",
  "confidence": 0.86,
  "issues": [],
  "suggestions": [],
  "artifacts": {},
  "human_review_required": false,
  "error": null,
  "audit": {
    "workflow_id": "wf_123",
    "run_id": "run_456",
    "model": "gpt-5.5",
    "input_hash": "...",
    "output_hash": "...",
    "latency_ms": 1234,
    "trace_ref": "..."
  }
}
```

统一状态机：

```text
pass
requires_revision
requires_human_review
blocked
failed
```

不同框架自己的状态必须在 adapter 内映射到上述状态。

### 多框架使用原则

可以混用：

```text
Compliance Agent        -> Strands
Listing Agent           -> OpenAI Agents SDK / Responses API
Product Research Agent  -> LangGraph
Ads Diagnostic Agent    -> SQL + LLM
Customer Service Agent  -> OpenAI Responses API / Agents SDK
Cost/Inventory/Orders   -> 普通后端工具
```

但主系统必须保持稳定：

```text
Tool Contract
Pydantic schema
Workflow decision enum
Audit log
Permission gate
```

结论：

```text
混用不同 AI 框架会增加 bug 风险；
但只要框架被 adapter 隔离，并统一输入输出、状态、错误、审计和权限，就是可控的。
```

## 7. 下一步开发顺序

推荐顺序：

```text
1. Stage framework
   intake / category / listing / platform_rules / assets / compliance / rewrite / publish_gate

2. Listing Agent-as-Tool 正式化
   从当前 deterministic generator 演进成 Agent + 平台模板 + 规则校验

3. Product Research Agent-as-Tool
   接趋势、竞品、评论痛点、利润、物流、侵权/合规风险打分

4. Ads Diagnostic Agent-as-Tool
   SQL 指标计算 + Agent 归因建议

5. Customer Service Agent-as-Tool
   分类、总结、拟回复；执行动作接权限和人审

6. Deterministic Tool 层
   成本、库存、订单、报表、平台字段校验
```

## 8. 当前结论

框架已经确定：

```text
CrossBorder Orchestrator
+ Agent-as-Tool 子能力
+ Deterministic Tools
+ Workflow Gate
+ MCP / HTTP / Python 三种接入方式
+ Audit Log
```

技术选型默认继续使用现有框架，不立刻切 OpenAI Agents SDK。OpenAI Agents SDK 值得作为后续 spike，因为它正好覆盖编排、工具执行、审批、状态、MCP 和可观测这些长期需求。
