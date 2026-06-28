# 项目4 深度讲解：多模态广告合规审核 Agent（跨境电商岗）

> 目标：把这个项目**每一点每个细节**掰开，让你真懂、能扛追问。
> 读法：先懂 §1 本质 + §2 数据流，再逐点看 §3。面试主打 §3.6（置信度校准）+ §3.7（并行+辩论）+ §4（可插拔）+ §8（跨境全链路）。
> ⚠️ 诚实边界集中在 §9，务必读——避免吹过头。

---

## 1. 这个项目到底是什么（一句话 + 一段话）

**一句话**：一套**场景无关的多模态内容审核引擎**——「看图 → 多专家分工 → 置信度路由 → 人工审批 → 可审计推理链」这条主流程固定不变，**换知识库 + 换专家 agent 就能切业务场景**；首发实例是**电商广告法素材审核**。框架用 **Amazon Strands Agents SDK（Python）**。

**关键定位（务必背）**：它**不跟大厂全量分类器拼吞吐和成本**（必输），而是定位成「**分类器之上的疑难复审层**」，专吃分类器的四个硬伤：
| 分类器软肋 | 本引擎优势 |
|---|---|
| 谐音/拆字/繁体/图内藏字 → 要重新标注重训 | LLM 零样本理解语义 |
| 图、文单看合规、组合才违规 | VLM 图文联合推理 |
| 只给"违规分"，不可解释 | 输出**违规法条 + 整改建议 + 推理链** |
| 改规则要重训上线 | 改知识库/prompt 即时生效 |

```
全量素材 → [初筛：便宜规则/分类器粗筛] → 明确 case 直接放行/拦截
                                       ↓ 疑难 case（拿不准/疑似规避/需解释）
                        [本引擎：多模态多 agent 复审]
```
> 这个"不正面刚、做分类器补位层"的定位本身就是加分项——说明你懂工程取舍，不是无脑上大模型。

---

## 2. 一条素材的完整数据流（背下这条主线）

`orchestrator.py` 里 `ReviewEngine.review()` 的真实顺序：

```
0) 去重缓存：相同素材命中历史结论 → 直接返回（省 API）
1) 初筛 prescreen：纯文本扫黑名单
      ├─ 纯文案且无命中 → PASS 放行（不烧大模型）
      └─ 命中违禁词 / 带图片 → 进复审
2) 看图 vision_agent：Qwen-VL 把图 → 结构化文字（OCR+画面+可疑迹象），只读一次
3) 反馈闭环：拉本场景的人工纠正样本，作为专家 few-shot 注入
4) 跑专家：3 个专家 并行扇出（asyncio）/ 串行
5) 冲突辩论：专家分歧才触发一轮互评，否则跳过
6) 合并+路由 merge_and_route：汇总违规 → 置信度校准 → PASS / VIOLATION / NEEDS_HUMAN
7) 人工审批闸门：NEEDS_HUMAN 且配了 handler → 人裁决
→ 产出 ReviewOutcome：结论 + 违规列表 + 置信度 + 推理链 + token + 延迟
```

每一步都往 `reasoning_chain`（推理链）里 append 一条——**这就是"可审计"的落地**，面试可以说"每条判罚都能回放它是怎么得出的"。

---

## 3. 逐点掰开

### 3.1 两层架构：初筛 + 多专家复审（对应你说的"fast/deep 同一个哲学"）

**初筛 `prescreen`（看真实代码逻辑）**：纯文本、便宜，扫知识库里每条规则的 `blacklist`。
- 纯文案 + 无命中 → **直接放行**，不浪费大模型。
- 命中违禁词 → 进复审（确认 + 出整改建议）。
- **带图片 → 强制进复审**（理由：图内可能藏违禁词，便宜的文本筛根本看不到）。

> 面试话术："初筛挡掉明显的、便宜的；复审处理规则覆盖不了的语义和图文组合。带图必复审，因为违规经常藏在图里，这是多模态审核和纯文本审核的本质区别。"

### 3.2 看图 Agent（`vision_agent.py`）—— 细节很多，容易被追问

- **模型**：Qwen-VL（通义千问，走 DashScope 的 OpenAI 兼容端点）。选它因为**中文图内文字 OCR 强、便宜**。
- **只让它"看"、不挂任何工具**（`tools=None`）。为什么？**VL 模型 tool-calling 能力弱**——扬长避短：看图归看图，调工具/推理交给文本模型。这是"per-agent model"思想（每个 agent 绑最适合的模型）。
- **图只读一次**：看图 agent 把图转成结构化文字（`ocr_text` / `visual_elements` / `suspicious_details`），下游 3 个专家**只读这段文字、不重复读图** → 省 token（图 token 很贵）。
- **鲁棒解析 `parse_extraction`**：兼容纯 JSON / ```json 代码块 / JSON 前后带解释文字三种；**解析失败兜底**——把全文塞进 `visual_elements`，保证不崩。
- 输出三个字段的设计意图：`suspicious_details` 专门捕捉"拆字/谐音/文字嵌图"等**规避迹象**，喂给下游专家重点看。

> 被追问"幻觉怎么办"：看图 agent **只做客观提取、不做合规判断**（prompt 明确要求），判断权交给有法条依据的专家。把"看"和"判"分开，降低单点幻觉。

### 3.3 三个专家 Agent（`scenes/ecommerce_ad/scene.py` 里 `expert_specs`）

全部依据同一份 `knowledge_base.json`，各管一摊：

| 专家 | 管什么 | 典型违规 |
|---|---|---|
| **ad_law**（广告法） | 绝对化用语、虚假功效、医疗用语、暴富暗示；**识破谐音/拆字/繁体/图内藏字** | "国家级""最佳"、"国jia级"、"國家級" |
| **qualification**（资质类目） | 类目是否需特定资质、是否缺证、类目错放 | 普通食品卖保健功效（缺蓝帽子）、械字号当普通化妆品 |
| **cross_modal**（跨模态一致性） | 图、文单看都合规、**组合才违规**的隐性违规 | 豪车图+"月入过万"暗示暴富；前后对比脸+普通护肤文案暗示医疗功效；二维码图+"加主页"违规导流 |

每个专家的 system prompt 都强制要求：每条违规给出 `rule_id / law_article / **law_quote（法条原文）** / evidence / location / suggestion`，且 **law_quote 必须是知识库真实存在的原文、不得编造，引不出就留空**。这条直接喂给下面的置信度校准。

> cross_modal 这个专家是最能体现"多模态"价值的——**单看图合规、单看文合规、组合才违规**，传统分类器最难处理。面试重点讲它。

### 3.4 模型策略（分工）

| 角色 | 模型 | 原因 |
|---|---|---|
| 看图 | Qwen-VL | 中文 OCR 强、便宜；但 tool-calling 弱 → 只看不调 |
| 专家推理 | Qwen-Max / DeepSeek（文本）| tool-calling 强，负责法条比对、多轮推理 |
| 备用 | Anthropic / Bedrock | demo 演示 |

`model_provider.py` 是个模型工厂，按 `model_role`（"vision"/"text"）取对应模型。**省 token 关键**：图只由看图 agent 读一次。

### 3.5 结构化输出 + 容错解析（国产模型适配的工程细节）

- 不依赖 SDK 的 `structured_output` schema 强约束，而是 **prompt 里写死 JSON 形状 + 容错解析**（`jsonutil.parse_into`）。为什么？**对 Qwen/DeepSeek 等国产接口更稳**（它们 structured output 支持参差）。
- 专家输出解析失败 → **兜底成 `NEEDS_HUMAN`、confidence=0**（`_finalize`）。即"模型不听话 → 不瞎判 → 转人工"。这是一条很务实的安全网。

### 3.6 ⭐ 置信度校准 —— 全项目最强的一个点，必背（`calibrate_confidence`）

**问题**：LLM 会**过度自信**——它说"我 95% 确定违规"，但可能根本没有法条依据，是它编的。

**你的解法**：把置信度**锚定在"有没有法条原文依据（law_quote）"**，而不是模型自评。
```
grounded = 有 law_quote 的违规条数 / 总违规条数
校准后置信 = raw_conf × (0.5 + 0.5 × grounded)
```
- 全部违规都引到了法条原文（grounded=1）→ 不打折。
- 一条都没引到原文（grounded=0）→ **置信度砍半** → 大概率掉到阈值 0.75 以下 → **转人工**。

> 金句："我不信模型自报的置信度，我把置信度重新锚定到'这条违规能不能引出知识库里的法条原文'。**编出来的违规没有原文支撑，会被自动打到阈值以下、转人工**。这是我对抗 LLM 过度自信的核心设计。"

路由规则（`merge_and_route`，纯函数、离线可测）：
- 无违规 → `PASS`，置信取各专家均值。
- 有违规 → 取**最有把握的检出专家**置信度 → 过校准 → ≥阈值=`VIOLATION`，<阈值=`NEEDS_HUMAN`。
- 每条违规都标注 `expert`（来自哪个专家），可追溯。

> `merge_and_route` 和 `calibrate_confidence` 都是**纯函数**，可以用假数据离线单测、不烧 API——这点和你项目1（CircuitBreaker 注入虚拟时钟）是同一个测试哲学，可以串起来讲。

### 3.7 并行扇出 + 冲突触发辩论（`debate.py`）—— 体现"懂成本的多 agent"

- **独立 case → 并行扇出**：3 个专家互不依赖，用 `asyncio.gather` 并发跑（`_run_experts_parallel`）。路线图记录延迟 **0.9s → 0.3s**。
- **冲突 case → 才触发一轮辩论**：
  - `detect_conflict`：分歧定义 = **有专家报违规、同时有专家判无违规**（"一个说违规一个说没事"）。
  - 触发时 `peer_summary` 把其他专家的判定+理由渲染成"对方意见"，每个专家**看到同伴意见后重新裁决**（可被说服改判，也可坚持但要给更充分的法条理由）。
  - **只辩一轮、只在冲突时辩** → 把"多 agent 通信"的成本压到少数 case。
  - 路线图里有真实触发记录：专家被说服改判（`docs/debate_demo.svg`）。

> 金句："多 agent 通信很贵，所以我不是让所有专家每次都开会。独立的 case 并行各judge各的；**只有出现实质分歧（一个判违规一个判没事）才触发一轮辩论**，让分歧专家互看理由重裁。把通信成本花在刀刃上。"

### 3.8 人工审批的两种机制（别混淆，面试容易被问区别）

| 机制 | 文件 | 何时用 |
|---|---|---|
| **确定性审批闸门** | `approval.py` | **当前 MVP 主路径**：编排器主导，路由出 `NEEDS_HUMAN` 时调 `approval_handler.decide()`，人裁决后 `apply_decision` 改写结论 |
| **Strands hook interrupt** | `hooks.py` | agent **自主**决定调危险工具时（如 `auto_takedown`/`write_knowledge_base`），`BeforeToolCallEvent` 触发 `event.interrupt()` 暂停等人放行 |

> 区别一句话："流程层面的'转人工'是我编排器主动控制的确定性闸门；而当 agent 被赋予能产生外部副作用的工具时，我用 Strands 原生的 `BeforeToolCallEvent + interrupt()` 在工具调用前拦截。前者控流程，后者控 agent 自主行为。human-in-the-loop 是 Strands 的一等公民机制。"

### 3.9 反馈闭环（`build_corrections_hint`）

人工纠正过的样本会被存下来，下次审核时**作为 few-shot 注入专家 prompt**（"历史人工纠正案例，引以为戒"）。即：人工修正 → 喂回模型 → 减少重犯同类误判。这是一个轻量的"持续学习"。

### 3.10 去重缓存 + 成本/存储/审计（`storage.py`，SQLite）

- **去重缓存**：相同素材命中历史结论直接返回，`from_cache=True`，省 API。
- 存：结果 + **推理链**（可审计）+ token 成本 + 反馈样本。
- `evaluation.py`：按规避类型拆准确率 + 置信度校准曲线 + P/R（指标模块就绪）。

---

## 4. ⭐ 可插拔 Scene 架构（你的工程抽象能力，重点讲）

引擎核心（`core/`）**场景无关、永远不动**；业务都在 `scenes/` 里。一个 `Scene` 只需向引擎提供四样东西：
1. `knowledge_base` — 该场景的规则/法条
2. `expert_specs` — 专家 agent 列表
3. `prescreen` — 初筛粗筛规则
4. `output_schema` — 结构化结论字段

**证明它真可插拔**：除电商广告（`ecommerce_ad`）外，还做了第二个场景 `merchant_license`（商家证照核验）——**同一引擎零改，换 KB + 换专家就跑通新场景**。

> 金句："核心审核流程我抽成了场景无关的引擎，业务规则全部下沉到 Scene。加一个审核场景 = 加一个目录（知识库+专家），引擎一行不改。我用第二个场景（证照核验）验证了这点。" —— 这正好回应 JD 的"配套内部工具链/可扩展"。

---

## 5. 对抗测试集（`tests/ecommerce_ad/adversarial_cases/`）

8 个对抗样本 + 配图，覆盖：**谐音 / 拆字 / 图内字 / 繁体 / 医疗功效 / 跨模态 / 正常（防误杀）**。每个带预期输出。
> 测试现状：6 个测试文件 / **31 个测试函数**（比项目1的171少，别夸大）。纯函数（路由/校准/冲突检测/解析）离线测通；端到端真跑过（广告法已真检出违规、看图已真读出图内藏字、辩论已真触发改判）。

---

## 6. 前端 + 部署

- 后端 `web/app.py`（FastAPI）；前端 React/Vite（`frontend/`，有 dist 构建产物）。
- 看板展示：审核结果、**推理链**、成本、待人工队列、**辩论高亮**、人工回写反馈。
- 还有 `mcp_server.py`：把审核能力暴露成 MCP 工具。

> 这覆盖了 JD 的"全栈"——后端 FastAPI + 前端 React 都是你做的。

---

## 7. 面试高频追问 速答

**Q：为什么不用一个分类器就好，非要上多 agent？**
A：见 §1。我是分类器的**疑难复审层**，吃它的硬伤（规避/跨模态/可解释/快迭代），不跟它拼吞吐。

**Q：多个专家一起判，成本不爆炸吗？**
A：三招控成本——①图只读一次转文字下游复用；②独立 case 并行、**只有冲突才辩论一轮**；③去重缓存命中直接返回。

**Q：模型判错了把合规的判违规（误杀）怎么办？**
A：置信度校准（无法条原文支撑→转人工）+ NEEDS_HUMAN 闸门 + 对抗集里专门放了"正常样本"防误杀 + 人工纠正反馈闭环。

**Q：law_quote 模型也可能编啊？**
A：prompt 强约束"必须是知识库真实原文、引不出就留空"，且后续可加一步**字符串比对校验 law_quote 是否真在 KB 里**（这是我明确的下一步加固点）。

**Q：知识库就几条规则，能用吗？**
A：诚实——见 §9。当前是 demo 级 KB，重点验证的是**引擎架构**；扩规则 = 往 JSON 加条目，零改代码。

---

## 8. ⭐ 嫁接这家公司：你还做了跨境全链路（`crossborder/`）—— 这是王牌

**别只讲合规审核**。这个 repo 里还有一整个 `crossborder/` 模块，是一条**跨境电商全链路工作流**（`workflow.py`），stage 顺序：
```
intake（接入）→ product_research（选品）→ category（类目）→ listing（生成listing）
→ platform_rules（平台规则 Amazon/TikTok/Walmart）→ assets（素材）
→ compliance（合规审核，复用上面的引擎）→ (不过则 rewrite 重写，循环至多N次) → publish_gate（发布闸门）
```
还有 `ads/diagnostic_agent`（广告诊断）、`customer_service/agent`（智能客服）、`data_intake/amazon_reviews_2023_loader`（接 Amazon 评论数据）、`action_gate`（动作闸门）。

**这几乎是把 JD 逐条实现了**：
| JD 要的 | 你 crossborder 里有的 |
|---|---|
| 选品 | `product_research` stage + tool |
| Listing 优化 | `listing` 生成 + `rewrite` 重写循环 |
| 广告投放 | `ads/diagnostic_agent` |
| 多语种/合规 | `compliance` stage 复用审核引擎 |
| 智能客服 | `customer_service/agent` |
| 对接主流平台 | `platform_rules` / `platforms.py`（Amazon/TikTok/Walmart）|
| 发布前把关 | `publish_gate` + `action_gate` |

> 王牌话术："我这个项目不止是广告合规——我把它扩成了一条跨境电商全链路：选品→类目→生成listing→套平台规则→素材→合规审核→不合规自动重写→发布闸门。合规引擎是其中一个 stage。**这条 pipeline 的形状和你们要做的全链路 agent 高度一致**，我已经趟过一遍。"

⚠️ 但要诚实：crossborder 多数 stage 是**离线可跑的工作流骨架 + 部分真实接入**（如 Amazon 评论 loader），不是接了真实平台 API 的生产系统。讲"架构和链路我走通了"，别说"我对接了 Amazon 生产 API"。

---

## 9. ⚠️ 诚实边界（务必读，别吹过头被抓）

1. **知识库小**：`knowledge_base.json` 只有 **4 条 violation_rules** + evasion_patterns + 类目映射。是 demo 级，验证架构用的。被问就说"规则可扩展、加 JSON 即可，重点是引擎"。
2. **测试 31 个**（项目1是171）。别把项目1的数字安到这个上。
3. **辩论/审批多为离线测通 + 少量真跑**，不是大批量生产验证。路线图里 M12 "Eval 深化"标的是"真跑待批量"。
4. **crossborder 是工作流骨架**，没接真实平台生产 API（见 §8 警告）。
5. **单月项目（2026.06）**：体量比项目1小。定位成"我快速验证了一套可插拔多模态审核范式 + 跨境链路骨架"，主打**架构和范式**，不主打规模。
6. **Strands SDK 是 AWS 的框架**：human-in-loop hook、observability 是框架能力，你用得对、但不是你发明的——和项目1一样，主动划清框架 vs 自研边界。

---

## 10. 数字/名词 速记卡

- 框架：Amazon **Strands Agents SDK**（Python）；定位=分类器之上的**疑难复审层**
- 主流程：缓存→初筛→看图→(few-shot)→专家(并行)→冲突辩论→合并路由→人工闸门
- 看图：**Qwen-VL**，只看不调工具，**图只读一次**，鲁棒 JSON 解析兜底
- 专家：**3 个**（ad_law / qualification / cross_modal），文本模型 Qwen-Max/DeepSeek
- ⭐ 置信度校准：锚定 **law_quote 法条原文**，无依据→砍半→转人工；阈值 **0.75**
- 路由结论：PASS / VIOLATION / **NEEDS_HUMAN**
- 并行：asyncio 扇出 **0.9s→0.3s**；辩论：**冲突才触发、只辩一轮**
- 人工：approval 确定性闸门 + Strands `BeforeToolCallEvent.interrupt()`
- 可插拔：Scene 四契约（KB/专家/初筛/schema）；第二场景 merchant_license 零改验证
- 对抗集：8 样本（谐音/拆字/图内字/繁体/医疗/跨模态/正常）；测试 **31 个**
- 全栈：FastAPI + React 看板 + MCP server
- ⭐ 跨境全链路 `crossborder/`：选品→类目→listing→平台规则→素材→合规→重写→发布闸门
- 诚实：KB 仅4条规则 / demo级 / 单月 / 骨架非生产API
</content>
