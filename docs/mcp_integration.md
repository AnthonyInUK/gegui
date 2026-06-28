# MCP 接入说明：跨境电商合规 Agent-as-Tool

这个项目可以作为跨境电商 Agent 的合规工具层使用：

```text
跨境电商 Agent / Listing Agent / Ad Agent
        |
        | MCP tool call
        v
Compliance MCP Server
        |
        v
ReviewEngine + 场景专家 + 知识库 + SQLite 审计
        |
        v
结构化决策：pass / requires_revision / requires_human_review / blocked
```

## 启动 MCP Server

在项目根目录：

```bash
.venv/bin/python src/mcp_server.py
```

MCP 默认使用 stdio 传输，由外部 Agent 平台作为 client 拉起该进程。

## MCP Client 配置示例

把下面配置给支持 MCP 的外部 Agent 平台：

```json
{
  "mcpServers": {
    "hoyoverse-compliance": {
      "command": "/Users/anthony/Desktop/llm/hoyoverse-compliance-agent/.venv/bin/python",
      "args": [
        "/Users/anthony/Desktop/llm/hoyoverse-compliance-agent/src/mcp_server.py"
      ],
      "cwd": "/Users/anthony/Desktop/llm/hoyoverse-compliance-agent"
    }
  }
}
```

## 暴露的工具

```text
compliance_check
compliance_check_ad
compliance_check_listing
compliance_verify_certificate
```

推荐跨境电商 Listing/Ad Agent 优先调用：

```text
compliance_check_ad
```

证照/资质 Agent 调用：

```text
compliance_verify_certificate
```

## 输入示例

```json
{
  "platform": "amazon",
  "market": "US",
  "product": {
    "title": "Pain relief massager",
    "category": "health_personal_care",
    "claims": ["relieves chronic pain"],
    "materials": ["ABS", "silicone"]
  },
  "content": {
    "title": "Pain relief massager",
    "description": "Portable massager for daily relaxation.",
    "ad_copy": "Relieves chronic pain fast.",
    "image_urls": [
      "https://example.com/listing-image.png"
    ],
    "image_paths": [
      "/absolute/path/to/listing-image.png"
    ]
  },
  "documents": [
    {
      "type": "certificate",
      "file_url": "https://example.com/certificate.png",
      "file_path": "/absolute/path/to/certificate.png",
      "issuer": "example issuer"
    }
  ],
  "caller": {
    "agent": "ListingAgent",
    "workflow_id": "wf_123",
    "permissions": ["read", "analyze", "suggest", "block"]
  },
  "metadata": {
    "seller_id": "seller_001"
  }
}
```

当前引擎支持两种资产输入：

```text
content.image_urls          远程商品图 URL，工具会下载到本地临时文件
content.image_paths         已在本机/容器内的商品图路径
documents[].file_url        远程证照图 URL，工具会下载到本地临时文件
documents[].file_path       已在本机/容器内的证照图路径
```

远程资产会缓存到：

```text
src/db/downloaded_assets/
```

下载限制：

```text
scheme: http / https
type: image/*
size: <= 20MB
timeout: 15s
```

## 输出字段

外部 Agent 只需要稳定读取这些字段：

```text
decision
risk_level
confidence
issues
required_documents
suggested_rewrite
human_review_required
audit.check_id
audit.workflow_id
```

典型输出：

```json
{
  "decision": "requires_revision",
  "risk_level": "medium",
  "confidence": 0.82,
  "risk_categories": ["medical_terms_on_normal_goods"],
  "issues": [
    {
      "field": "content.ad_copy",
      "text": "Relieves chronic pain fast.",
      "severity": "high",
      "reason": "普通商品使用医疗用语",
      "suggestion": "改为客观舒缓、放松类表达",
      "category": "medical_terms_on_normal_goods",
      "source_expert": "ad_law"
    }
  ],
  "human_review_required": false,
  "audit": {
    "check_id": "REV-12345678",
    "workflow_id": "wf_123"
  }
}
```

## Workflow 路由建议

```text
decision = pass
  -> Listing/Ad workflow 继续

decision = requires_revision
  -> 调 Rewrite Agent 或让 Listing Agent 修改文案

decision = requires_human_review
  -> 进入人工复核队列，禁止自动发布

decision = blocked
  -> 阻断发布/投放，但不自动删除、不自动申诉
```

## 和 FastAPI 的关系

FastAPI 和 MCP 是两种入口，复用同一套核心逻辑：

```text
HTTP: /tools/compliance/check
MCP:  compliance_check_ad
Core: run_compliance_check() -> ReviewEngine
```

普通后端系统适合走 HTTP；Agent 平台、Agent IDE、多 Agent 编排更适合走 MCP。
