# 通用多模态审核引擎 — 架构设计

## 一句话定位

一套**场景无关的多模态内容审核/核验引擎**：核心的「看图 → 多专家分工 → 置信度路由 → 人工审批 → 可审计推理链」流程固定不变，**换知识库 + 换专家 agent 就能切换业务场景**。首发实例为**电商广告法素材审核**。

技术框架：**Amazon Strands Agents SDK（Python）**。

---

## 为什么用 agent 而不是传统分类器

不与大厂的全量分类器比吞吐和成本（必输），而是定位在**分类器之上的「疑难复审层」**，专门吃分类器的硬伤：

| 维度 | 分类器软肋 | 本引擎优势 |
|------|-----------|-----------|
| 对抗性规避 | 谐音/拆字/繁体/图内藏字需重新标注重训 | LLM 零样本理解语义 |
| 跨模态隐性违规 | 图、文单看合规、组合才违规 | VLM 图文联合推理 |
| 可解释 | 只给「违规分」 | 输出违规法条 + 整改建议 + 推理链 |
| 迭代速度 | 改规则要重训上线 | 改知识库 / prompt 即时生效 |

```
全量素材 → [初筛层：便宜规则/分类器粗筛] → 明确 case 直接放行/拦截
                                            ↓ 疑难 case（拿不准 / 疑似规避 / 需解释）
                          [本引擎：多模态多 agent 复审]
```

---

## 为什么用 Strands（业务刚需 ↔ 框架特性）

审核业务的本质 = **分工看 → 拿不准喊人 → 留底存档**，恰好对上 Strands 的三个一等公民特性：

| 审核刚需 | Strands 特性 |
|---------|-------------|
| 机器拿不准 → 转人工 | `BeforeToolCallEvent` + `event.interrupt()`（人工审批是框架原语） |
| VL 眼睛 + 文本脑子 | per-agent model（每个 agent 绑不同模型） |
| 判罚可审计 | 内置 observability / trace + 推理链存储 |
| 规则按领域分工迭代 | 轻量 multi-agent（agents-as-tools / graph） |

---

## 模型策略

| 角色 | 模型 | 原因 |
|------|------|------|
| 看图（视觉提取） | Qwen-VL（通义千问，DashScope OpenAI 兼容端点） | 中文图内文字 OCR 强、便宜；VL 模型 tool-calling 弱，故只让它"看"不让它"调工具" |
| 专家推理 | Qwen-Max / DeepSeek（文本） | tool-calling 强，负责法条比对、调工具、多轮推理 |
| 备用 | Anthropic / Bedrock | demo / 演示 |

**省 token 关键设计**：图只由看图 agent 读**一次**，转成结构化文字后，下游专家 agent 只读文本、不重复读图。

---

## 可插拔架构

```
src/
├── core/                      # 引擎核心（场景无关，永远不动）
│   ├── model_provider.py      # 模型工厂（Qwen-VL / Qwen-Max / DeepSeek / Anthropic）
│   ├── vision_agent.py        # 通用看图 agent（Qwen-VL）
│   ├── orchestrator.py        # 编排 + 置信度路由
│   ├── hooks.py               # 人工审批 hook（interrupt）
│   ├── prescreen.py           # 初筛层
│   ├── schemas.py             # pydantic 结果模型
│   └── storage.py             # 结果 + 推理链审计存储（SQLite）
│
├── scenes/                    # 可插拔场景（要扩展业务就在这加目录）
│   ├── base.py                # Scene 抽象接口
│   ├── ecommerce_ad/          # ★ 首发实例：电商广告法
│   │   ├── knowledge_base.json   # 违禁词 + 法条 + 类目资质规则
│   │   ├── experts.py            # 广告法 / 资质类目 / 跨模态一致性 专家 agent
│   │   └── scene.py              # 注册：绑定 KB + 专家 + 初筛规则
│   └── merchant_license/      # （预留）商家证照核验 — 证明可插拔
│
└── tests/
    └── ecommerce_ad/
        └── adversarial_cases/ # 对抗样本（谐音/拆字/图内字/跨模态）+ 预期输出
```

### Scene 接口契约（这是"可插拔"的核心）

一个 `Scene` 向引擎提供四样东西，引擎其余部分完全场景无关：
1. `knowledge_base` — 该场景的规则 / 法条
2. `expert_agents` — 该场景的专家 agent 列表
3. `prescreen_rules` — 初筛粗筛规则
4. `output_schema` — 该场景的结构化结论字段

引擎拿到一个 Scene 实例即可跑完整流程，切场景 = 换一个 Scene。

---

## MVP 范围 vs 可扩展（刻意收窄，避免膨胀）

| 维度 | MVP 做 | 可扩展（写文档，不在 MVP 实现） |
|------|--------|-------------------------------|
| 专家 agent | 广告法 / 资质类目 / 跨模态一致性 ×3 | 盗图侵权、违禁品、价格欺诈、落地页一致性 …… 加一个 = 加一段 ExpertSpec，零改引擎 |
| 多模态 | **识图**：OCR（图内藏字）+ 视觉语义（豪车/对比脸/二维码） | 视频抽帧、直播语音转写、证照/落地页文档 |
| multi-agent | orchestrator + 子专家**串行**调度（agents-as-tools） | Strands **Graph** 并行编排专家（互不依赖，可同时审）——明确升级点 |

> 「识图」不只是 OCR：跨模态违规（豪车图 + "月入过万"文案）靠的是 VL 的视觉语义理解，
> 而非读字。本场景的多模态需求 = OCR + 视觉语义，已被看图 agent 覆盖。

## 开发路线图（紧凑 MVP，约 3 周全天）

| 里程碑 | 内容 | 工期 | 状态 |
|--------|------|------|------|
| M1 地基 | Scene 接口 + model_provider 加 Qwen 两档 + 图片输入处理 | 2 天 | ✅ 完成 |
| M2 看图 | 通用 vision_agent（Qwen-VL）跑通：图 → 结构化文字 | 1.5 天 | ✅ 真跑通（读出图内藏字） |
| M3 电商知识库 | 违禁词/法条/类目资质 JSON + EcommerceAdScene | 1.5 天 | ✅ 完成 |
| M4 专家 agent | 广告法 / 资质类目 / 跨模态一致性 ×3 | 3 天 | ✅ 3 个专家全注册（广告法已真跑出违规） |
| M5 编排+路由 | orchestrator + 置信度汇总 | 1.5 天 | ✅ 路由纯函数离线测通（PASS/VIOLATION/NEEDS_HUMAN） |
| M6 人工审批 | 闸门（编排器）+ 真 Strands interrupt hook（工具守卫） | 1 天 | ✅ 闸门+hook 离线测通 |
| M7 存储+输出 | pydantic 结果 + SQLite + 推理链 + 成本/缓存/反馈 | 1.5 天 | ✅ 存储+缓存+反馈+成本离线测通 |
| M8 对抗测试集 | 8 样本（谐音/拆字/图内字/繁体/医疗/跨模态/正常）+ 图 | 2.5 天 | ✅ 样本+图齐全 |
| M10 第二场景 | 商家证照核验（证明可插拔：换 KB+专家，引擎零改） | 2 天 | ✅ 同一引擎零改跑通新场景 |
| M11 并行专家 | 串行 → 并行（asyncio）+ 延迟优化 | 1.5 天 | ✅ 3专家并发，0.9s→0.3s |
| M11.5 冲突辩论 | 专家分歧时触发一轮互评辩论（真 agent 间通信） | 1 天 | ✅ 真跑触发：专家被说服改判（docs/debate_demo.svg） |
| M12 Eval 深化 | 按规避类型拆准确率 + 置信度校准曲线 + P/R | 1.5 天 | ✅ 指标模块+运行器就绪（真跑待批量） |
| M13 Web 看板 | FastAPI + React/Aceternity：结果/推理链/成本/待人工/反馈 | 3 天 | ✅ React 看板跑通（审计链+辩论高亮+人工回写） |
| M9 收尾 | Rich CLI + README + 联调 + 录 demo | 2 天 | ⏳ |

## 已建代码地图

```
src/
├── core/
│   ├── model_provider.py   ✅ 按角色(vision/text)选 Qwen/DeepSeek/Anthropic
│   ├── images.py           ✅ 图片→content block（自动缩放省 token）
│   ├── schemas.py          ✅ VisionExtraction
│   ├── jsonutil.py         ✅ 容错 JSON 提取 + pydantic 字段提示生成
│   ├── vision_agent.py     ✅ 看图 agent（VL，无工具）
│   ├── experts.py          ✅ 专家 agent 运行器（通用）
│   ├── orchestrator.py     ✅ ReviewEngine + merge_and_route 置信度路由
│   ├── approval.py         ✅ 人工审批闸门（CLI/Auto 处理器，apply_decision 纯函数）
│   ├── hooks.py            ✅ Strands HookProvider：高风险工具 interrupt 守卫
│   ├── debate.py           ✅ 冲突触发式一轮辩论（detect_conflict/peer_summary 纯函数）
│   └── storage.py          ✅ SQLite：结果/审计/成本/去重缓存/反馈闭环数据源
└── scenes/
    ├── base.py             ✅ Scene 接口
    ├── ecommerce_ad/
    │   ├── knowledge_base.json  ✅ 广告法违禁词/法条/类目资质
    │   └── scene.py             ✅ EcommerceAdScene + AdReviewResult
    ├── merchant_license/        ✅ 第二场景：证照核验（证明可插拔，core 零改）
    │   ├── knowledge_base.json
    │   └── scene.py             ✅ MerchantLicenseScene + LicenseReviewResult
    └── web/app.py               ✅ FastAPI：/api/stats /records /feedback（React 看板后端）

frontend/                        ✅ React + Vite + Tailwind + framer-motion + Aceternity
├── src/App.tsx                  ✅ 看板：统计/记录表/审计推理链/人工裁决
├── src/components/ui/           ✅ Aceternity 风格：spotlight / background-gradient
├── src/api.ts                   ✅ 后端 API 客户端（Vite proxy → :8000）
└── eval_runner.py / demo_debate.py / seed_demo.py  ✅ 跑 eval / 辩论 demo / 灌种子数据
```

## 差异化增强（区别于"又一个 LLM 审核 demo"的关键）

1. **置信度校准（锚定法条原文）** — `calibrate_confidence`：每条违规须带 `law_quote`（法条原文），
   引不出原文的判定按比例拉低置信度（全无原文砍半），迫使"无依据判定"落到阈值下转人工。
   **破解 LLM 过度自信**这一通病——这是核心差异化，不是模型自评 confidence。
2. **反馈闭环** — 人工 APPROVE/REJECT 落库（`storage`）；模型被推翻的样本经 `get_correction_samples`
   提取，`build_corrections_hint` 渲染成 few-shot 注入专家 prompt。**人工修正 → 系统变好**。
3. **成本/延迟量化** — 每次审核记 `tokens` + `latency_ms`。主动量化经济账，呼应"大厂赢在成本"的清醒认知。
4. **去重缓存** — 按内容哈希（文案+图片字节）命中历史结论直接复用，省 API。

## 工程要点（实战踩坑，写进 plan 以免重蹈）

1. **结构化输出不靠 SDK 的 `structured_output`**：Qwen/DeepSeek 等国产 OpenAI 兼容接口
   不强制 pydantic 字段名（实测模型自创 `violation_found`/`id`）。统一策略：
   **prompt 里写死 JSON 形状（`pydantic_field_hint` 自动生成）+ 容错解析（`jsonutil`）**，
   解析失败兜底为 `NEEDS_HUMAN` 转人工。
2. **DashScope json 模式怪癖**：prompt 文本里必须出现 "json" 字样，否则 400。已在 `run_expert` prompt 内置。
3. **VL 模型不挂工具**：tool-calling 弱，看图 agent `tools=[]`，只做提取。
4. **图只读一次**：看图 agent 输出 `VisionExtraction.as_context()` 纯文本，下游专家复用，省 token。
5. **省钱原则**：能离线验证的（解析/契约/结构）不调模型；真跑只在链路首次贯通时做一次。
6. **并行用 asyncio 而非 Strands Graph**：三专家相互独立、各需自定义 JSON 解析，属"独立扇出"，
   用 `asyncio.gather` 最直接（实测 3 专家 0.9s→0.3s）。Strands Graph 留给"有 agent 间依赖的编排"。
   与 interrupt 同理：因地制宜，不为秀框架而硬用。
7. **多 agent 通信只在冲突时**：独立 case 并行扇出（不通信）；专家**分歧**时才触发一轮辩论
   （互看理由、可被说服改判）。按"分歧程度"决定要不要让 agent 对话，把通信成本压到少数 case。
8. **Qwen 拒绝空 tools**：Strands `format_request` 总序列化 `tools: []`，qwen-max 报
   '[] is too short - tools'。子类化 OpenAIModel，空 tools 时删掉该字段（`model_provider._no_empty_tools_model_cls`）。

**可砍**：Web dashboard（不做）；跨模态一致性 agent（赶时间可缓，作为演进）；多图处理（先单图）。

**首个完整链路（MVP 入口）**：
```
review("一张主图 PS 了'全国销量第一'，文案'轻松月入过万'")
→ 看图提取 → 广告法+跨模态专家判定 → 置信度路由 → 输出违规法条+整改建议 → 存档
```
