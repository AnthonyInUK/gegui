# 广告合规 Agent — Agent-as-Tool 部分逐行讲解（含逻辑与公式）

> 对照源码：`src/core/tool_contract.py`（核心契约）、`src/mcp_server.py`、`src/web/app.py`、`src/crossborder/stages/compliance.py`、`src/crossborder/tools.py`。
> 一句话先记住：**Agent-as-Tool = 把"一整个多 agent 系统"封装成"一个有类型化输入输出的工具"，让别的 agent / 工作流像调用普通函数一样调用它，而完全不需要知道它内部有看图 agent、3 个专家、辩论、路由。**

---

## 0. 为什么需要 Agent-as-Tool（先懂动机，否则讲不出价值）

你的合规引擎内部很复杂：看图 agent（Qwen-VL）→ 3 个专家 agent（并行）→ 冲突辩论 → 置信度校准 → 人工闸门。

如果别的系统（比如跨境全链路工作流）想用它，有两种做法：
- ❌ 把这堆内部逻辑暴露出去 → 调用方要懂你的 Scene、专家、阈值，强耦合，你一改它就崩。
- ✅ **Agent-as-Tool**：在引擎外面包一层**稳定契约**——固定的请求结构 `ComplianceCheckRequest` 进，固定的响应结构 `ComplianceCheckResponse` 出。调用方只认这层契约，内部随便改。

> 面试金句："我把整个多 agent 合规引擎封成了一个 Agent-as-Tool——对外只暴露一个稳定的、机器可读的输入输出契约。上层工作流把'合规审核'当成一个工具步骤来调，不用关心里面有几个 agent、怎么辩论。这样**内部能力可以独立演进，调用契约不变**。"

源码注释原文（`tool_contract.py` 顶部）：
> "This layer keeps the existing ReviewEngine/Scene abilities intact, but exposes them as **stable, machine-readable tool inputs and outputs for other agents**."

---

## 1. 整体调用链（数据怎么流）

```
调用方（MCP / FastAPI / 工作流）
   │  传入 ComplianceCheckRequest（结构化）
   ▼
run_compliance_check(req)                 ← Agent-as-Tool 的唯一入口
   ├─ _scene_for(task_type)               ← 选场景（广告 / 证照）
   ├─ _material_for(req)                  ← 结构化输入 → 引擎吃的 ReviewMaterial（含下载远程图）
   ├─ ReviewEngine(scene,...).review()    ← 跑整个多 agent 引擎（看图→专家→辩论→路由）
   ├─ storage.save_outcome(...)           ← 落库 + 拿 check_id
   ├─ 映射：outcome → 对外响应字段（decision / risk / issues / docs / rewrite / evidence）
   └─ 组装 AuditInfo（版本 + input_hash + reasoning_chain）
   ▼
返回 ComplianceCheckResponse（结构化决策，供上层路由）
```

**关键**：`run_compliance_check` 内部调的就是你前面那套 `ReviewEngine`。Agent-as-Tool **不是另写一套逻辑，而是给已有引擎套一层稳定的"翻译层"**——把外部通用结构翻成引擎的内部结构，再把引擎结论翻成外部决策。

---

## 2. 输入契约 `ComplianceCheckRequest`（每个字段干嘛）

```python
class ComplianceCheckRequest(BaseModel):
    task_type: TaskType = ad_review       # 任务类型 → 决定走哪个 Scene
    platform: str = ""                    # 平台（amazon/tiktok/walmart…）
    market: str = "CN"                    # 市场/法域（决定用哪国规则）
    product: ProductInput                 # 商品：title/category/claims/materials/attributes
    content: ContentInput                 # 素材：title/description/ad_copy/image_urls/image_paths
    documents: list[DocumentInput]        # 证照/文档：type/file_url/file_path/issuer
    caller: CallerInput                   # 调用方身份 + 权限声明
    metadata: dict                        # 透传额外信息
```

**4 种 task_type**（`TaskType` 枚举）：`ad_review`（广告审核）、`listing_review`（listing 审核）、`product_eligibility`（商品资质）、`certificate_verification`（证照核验）。

**`CallerInput.permissions`（容易被追问，体现"最小权限"）**：
```python
permissions: list[Literal["read","analyze","suggest","block"]] = ["read","analyze","suggest"]
```
调用方**声明自己被允许做什么**。默认只有"读/分析/建议"，没有"block"。这是能力声明/最小权限原则——**这个工具本身只读、不改外部世界**（见 §6 MCP 声明）。

---

## 3. `_scene_for`：task_type → 场景路由（可插拔的体现）

```python
def _scene_for(task_type):
    if task_type == certificate_verification:
        return MerchantLicenseScene()     # 证照核验场景
    return EcommerceAdScene()             # 默认：电商广告法场景
```
> 同一个 Agent-as-Tool 入口，按 task_type 切到不同 Scene。换场景=换 Scene，契约和入口不变。这把"可插拔引擎"和"统一工具入口"接在了一起。

---

## 4. `_material_for`：结构化输入 → 引擎输入（翻译层 1）

引擎内部吃的是 `ReviewMaterial(text, image_paths, metadata)`。这个函数把通用契约**摊平**成引擎要的形状：

- **text**：把 product.title / category / claims + content.title / description / ad_copy **拼成一段文字**（过滤空值）。若全空，退化用 documents 的文本。
- **image_paths**：合并三个来源——
  1. `content.image_paths`（调用方直接给的本地图）
  2. `content.image_urls` 下载下来的本地图（见 §5）
  3. `documents` 里的 file_path / file_url 下载的图（证照图）
- **metadata**：把 task_type/platform/market/product/documents/caller/下载记录全塞进去，供审计和下游用。

> 一句话："Agent-as-Tool 的输入是给机器读的结构化字段；引擎要的是一段文本+图片列表。`_material_for` 就是这两者之间的适配器。"

---

## 5. ⭐ `_download_remote_asset`：安全下载远程图（防 SSRF/滥用，面试高分点）

调用方可能传 `image_urls`（网图）。直接下载是危险的（SSRF、超大文件、非图片）。这个函数做了**多重防护**，每条都有明确动机：

| 防护 | 代码 | 防什么 |
|---|---|---|
| **协议白名单** | scheme ∈ {http, https} | 挡 `file://`、`gopher://` 等 SSRF 向量 |
| **扩展名白名单** | ext ∈ {.png/.jpg/.jpeg/.webp/.gif/.bmp} | 挡非图片文件 |
| **Content-Type 校验** | 必须以 `image/` 开头 | 挡"扩展名伪装成图、实际是别的" |
| **大小上限（双重）** | `MAX_DOWNLOAD_BYTES = 20MB` | 防超大文件打爆磁盘 |
| **超时** | `DOWNLOAD_TIMEOUT_SECONDS = 15` | 防慢连接挂死 |
| **去重缓存** | `sha256(url)[:24]` 命中已下载就复用 | 省带宽，幂等 |
| **原子写** | 先写 `.tmp` 再 `replace` | 防半截文件 |

**大小上限为什么是"双重"（这是细节，能讲出来很加分）**：
1. 先看响应头 `Content-Length`，超过 20MB 直接拒。
2. 但 `Content-Length` **可能撒谎或缺失**（chunked 传输）。所以又用 `_LimitedWriter` 在**流式写盘时累加实际字节**：
```python
self.written += len(data)
if self.written > self.limit:   # 实际写入超限就当场中止
    raise AssetDownloadError("asset_too_large")
```
> 金句："文件大小我做了双重校验——先信任 Content-Length 头快速拒绝，但头可能撒谎，所以下载时再用一个限长写入器边写边数，真实超过 20MB 立刻中止。这是不信任外部输入的纵深防御。"

---

## 6. 三种暴露方式（同一个引擎，零逻辑重复）

`run_compliance_check` 这一个函数，被三处复用，**业务逻辑只有一份**：

| 暴露面 | 文件 | 谁来调 |
|---|---|---|
| **MCP 工具** | `mcp_server.py`（FastMCP） | 外部 agent 走 MCP 协议调用 |
| **HTTP API** | `web/app.py` 的 `_run_tool` | 前端 / 别的服务走 REST |
| **进程内调用** | `crossborder/stages/compliance.py` | 跨境工作流直接 import 调 |

`mcp_server.py` 注释把"这是只读工具"写死了（重要安全声明）：
> "Tools return structured decisions for workflow routing; they **do not publish, delete, appeal, or mutate external platforms**."

> 金句："我用一个 `run_compliance_check` 函数作为单一事实源，分别用 MCP、FastAPI、进程内调用三种方式暴露，**没有复制任何业务逻辑**。而且这个 Agent-as-Tool 是**纯只读**的——它只产出结构化决策供路由，绝不替你发布/删除/申诉/改动平台。副作用留给人或专门的 action agent。"

---

## 7. ⭐⭐ 输出映射的逻辑与公式（你要的"公式"全在这）

引擎产出的是内部 `ReviewOutcome`（final_verdict ∈ {PASS, VIOLATION, NEEDS_HUMAN} + confidence + violations）。Agent-as-Tool 要把它翻成**调用方能直接路由的决策**。

### 7.1 `_decision_for(verdict, confidence)` → 最终动作

```
PASS                          → "pass"（放行）
NEEDS_HUMAN                   → "requires_human_review"（转人工）
VIOLATION 且 confidence ≥ 0.9 → "blocked"（高置信违规，直接拦）
VIOLATION 且 confidence < 0.9 → "requires_revision"（违规但没那么确定，要求整改）
```
**逻辑**：只有"判了违规、且置信度 ≥ 0.9"才硬拦（blocked）；违规但置信不到 0.9 → 给整改机会（requires_revision）。0.9 是"硬拦阈值"，比引擎内部转人工的 0.75 阈值更高——**两道阈值各司其职**：
- 0.75（引擎内）：低于它 → 转人工。
- 0.9（工具层）：高于它且违规 → 才敢自动 block。

### 7.2 `_risk_level_for(verdict, confidence)` → 风险等级

```
PASS                          → low
NEEDS_HUMAN                   → unknown   （拿不准，所以风险"未知"而非低）
VIOLATION 且 confidence ≥ 0.9 → high
VIOLATION 且 confidence < 0.9 → medium
```
> 注意 NEEDS_HUMAN 给的是 `unknown` 不是 `low`——"机器没把握"≠"安全"，这个区分很重要。

### 7.3 `_issue_from_violation`：内部违规 → 对外 issue

把引擎的 `Violation` 字段重映射成对外 `ComplianceIssue`，并定**严重度**：
```python
severity = "high" if rule_id in {"absolute_terms", "forgery_suspect"} else "medium"
```
即：绝对化用语、证照伪造嫌疑 → 高危；其余 → 中危。`category = rule_id`，`source_expert` 标注是哪个专家检出的（可追溯）。

### 7.4 `_required_documents`：违规 → 需补哪些证件（关键词驱动）

扫每条违规的文本（rule_id+rule_name+suggestion）：
```
命中 资质/蓝帽/许可证/missing_license → 要 "qualification_certificate"（资质证明）
命中 医疗/功效/medical               → 要 "test_report"（检测报告/功效证据）
```
用 `dict.setdefault` 去重。**逻辑**：不只说"你违规了"，还告诉商家"你要补什么材料才能合规"——这是给整改闭环喂料。

### 7.5 `_suggested_rewrite`：给整改文案

```
无 issue → 返回 {}
有 issue → 取第一条非空 suggestion；都没有就用默认
          "移除绝对化、医疗功效、收益承诺等高风险表达，改为客观描述。"
返回 {"ad_copy": suggestion}
```
> 这就是"不止判罚、还给整改建议"的落地——直接给可改的文案方向。

### 7.6 `_evidence_for`：证据链（锚定法条原文）

每条违规 → 一个 `EvidenceItem(title=法条编号/规则名, summary=law_quote/evidence)`。**优先用 `law_quote`（知识库法条原文）**——和前面"置信度校准锚定 law_quote"是同一条主线：**判罚必须有原文依据**。无违规时返回一条"未发现违规"的证据。

---

## 8. ⭐ `AuditInfo`：每次工具调用都可审计、可版本化（工程成熟度）

每个响应都强制带一个审计块：
```python
class AuditInfo:
    check_id            # 落库记录 id，能回查
    workflow_id         # 来自调用方，串起整条工作流
    input_hash          # 输入内容哈希 → 相同输入可识别/去重
    model               # 实际用的模型（active_provider_name("text")）
    policy_version      # "local-kb-2026-06-20"  知识库/政策版本
    ruleset_version     # = scene_id，用了哪套规则
    tool_contract_version  # "compliance-tool-v1"  契约版本
    created_at          # 时间戳
    reasoning_chain     # 完整推理链（引擎一步步的记录）
```
> 金句："这个 Agent-as-Tool 的每次返回都带审计信息——**输入哈希、模型、知识库版本、契约版本、完整推理链**。意味着任何一条合规判罚，事后都能回答'用哪套规则、哪个模型、怎么推出来的'。而且**契约带版本号（compliance-tool-v1）**，将来升级输出结构不会悄悄打破调用方。"

**三个 version 字段的意义**（容易被追问"为什么要三个版本"）：
- `policy_version`：法条/违禁词知识库变了 → 政策版本变。
- `ruleset_version`：换了 Scene（广告↔证照）→ 规则集变。
- `tool_contract_version`：输入输出结构本身变了 → 契约版本变。
三者解耦：知识库更新不必动契约版本；契约升级也不影响政策版本。

---

## 9. 上层工作流怎么"把它当工具调"（Agent-as-Tool 的消费端）

跨境工作流里，合规就是一个 stage（`stages/compliance.py`）：
```python
ctx.compliance = checker(ctx.request, ctx.listing)   # 调 Agent-as-Tool
return StageResult(
    name="compliance",
    mode=StageMode.tool_call,                        # 明确标成"工具调用"步骤
    decision=ctx.compliance.get("decision"),         # 拿结构化决策去路由
    ...
)
```
`checker` 最终走到 `crossborder/tools.py: check_listing_compliance` → 调 `run_compliance_check` → 还叠了一层 `_apply_platform_preflight`（平台特定预检，如 Amazon 额外规则）。

**然后工作流据此路由**（`workflow.py`）：合规 decision 不是 pass → 进 `rewrite` 重写 → 再审，循环至多 N 次 → 最后 `publish_gate`。

> 金句："上层那个跨境工作流 agent，把我的合规引擎当成一个 tool_call 步骤：传 listing 进去，拿回结构化 decision，**不 pass 就触发 rewrite 重写再审，循环到通过或转人工**。这就是真正的'agent 调用 agent-as-tool'——复杂多 agent 系统在上层眼里只是一个可靠的工具。"

---

## 10. ⚠️ 诚实边界

1. `_required_documents` / `_suggested_rewrite` 是**关键词/规则驱动**的轻量映射，不是模型生成的精细整改——被问就说"这层是确定性后处理，重在稳定可控；更细的改写可以再上模型"。
2. `_apply_platform_preflight` 的平台规则是 demo 级，不是接了 Amazon 真实政策 API。
3. 硬拦阈值 0.9 是经验值，没做过大规模校准（路线图里有置信度校准曲线 M12，标"真跑待批量"）。
4. Strands/MCP 是框架能力；你做的是**契约设计 + 输入适配 + 安全下载 + 输出映射公式 + 审计版本化**这层。

---

## 11. 速记卡（面试前扫一眼）

- Agent-as-Tool = 把多 agent 引擎封成**稳定类型化契约**（`ComplianceCheckRequest`→`ComplianceCheckResponse`），别的 agent 当工具调，不碰内部。
- 入口唯一：`run_compliance_check`；三种暴露：MCP / FastAPI / 进程内，**零逻辑重复**；纯**只读**、无副作用。
- task_type→Scene 路由（广告/证照），可插拔。
- 输入适配 `_material_for`：结构化字段→text+图片列表。
- 安全下载：协议/扩展名/Content-Type 白名单 + **20MB 双重限长** + 15s 超时 + sha256 去重 + 原子写。
- 决策公式：PASS→pass；NEEDS_HUMAN→requires_human_review；VIOLATION & conf**≥0.9→blocked**，否则→requires_revision。
- 风险公式：PASS→low / NEEDS_HUMAN→**unknown** / 违规≥0.9→high / 否则 medium。
- severity：absolute_terms、forgery_suspect→high，其余 medium。
- 证据锚定 **law_quote** 法条原文；required_documents/rewrite 给整改闭环喂料。
- 审计：input_hash + model + **3 个版本号（policy/ruleset/tool_contract）** + reasoning_chain。
- 两道阈值：**0.75**（引擎内→转人工）vs **0.9**（工具层→才敢自动 block）。
</content>
