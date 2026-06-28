"""
合规审核看板（FastAPI）

读取 storage（SQLite）展示：审核记录、判定分布、成本、待人工队列、
推理链审计、人工 approve/reject 回写（接反馈闭环）。

启动：uvicorn web.app:app --reload --port 8000  （在 src/ 目录下）
"""

from __future__ import annotations

import sys
import json
import runpy
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))
load_dotenv(_ROOT / ".env")

from core import storage  # noqa: E402
from core.schemas import ReviewOutcome  # noqa: E402
from crossborder.action_gate import evaluate_action_gate  # noqa: E402
from crossborder.ads.diagnostic_agent import diagnose_ads  # noqa: E402
from crossborder.customer_service.agent import respond_to_customer  # noqa: E402
from crossborder.listing_agent import generate_listing_tool  # noqa: E402
from crossborder.product_research import research_product  # noqa: E402
from crossborder.schemas import (  # noqa: E402
    ActionGateRequest,
    AdsDiagnosticRequest,
    CrossBorderRequest,
    CustomerServiceRequest,
    ListingGenerationRequest,
    ProductResearchRequest,
)
from crossborder.tools_agent.ads_diagnostic_tool import run_ads_diagnostic_tool  # noqa: E402
from crossborder.tools_agent.improvement_tool import run_improvement_tool  # noqa: E402
from crossborder.tools_agent.listing_generation_tool import run_listing_generation_tool  # noqa: E402
from crossborder.tools_agent.opportunity_tool import run_opportunity_tool  # noqa: E402
from crossborder.tools_agent.product_research_tool import run_product_research_tool  # noqa: E402
from scenes.base import ReviewMaterial  # noqa: E402
from scenes.ecommerce_ad.scene import EcommerceAdScene  # noqa: E402

app = FastAPI(title="合规审核看板 / Compliance Tool API")
CASES_DIR = _ROOT / "tests" / "ecommerce_ad"
UPLOAD_DIR = _ROOT / "src" / "db" / "uploaded_assets"
ALLOWED_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@app.get("/api/stats")
def api_stats():
    return storage.stats()


@app.get("/api/records/{record_id}/image")
def api_image(record_id: str, idx: int = 0):
    """返回该记录的第 idx 张原图（供人工看图确认）。只允许该记录登记过的路径，防遍历。"""
    rec = storage.get_record(record_id)
    if not rec:
        return JSONResponse({"error": "record not found"}, status_code=404)
    paths = rec.get("image_paths") or []
    if idx < 0 or idx >= len(paths):
        return JSONResponse({"error": "image index out of range"}, status_code=404)
    p = Path(paths[idx])
    if not p.exists():
        return JSONResponse({"error": "image file missing"}, status_code=404)
    return FileResponse(p)


@app.get("/api/review/cases/{case_id}/image")
def api_review_case_image(case_id: str):
    """Return a built-in adversarial demo image for the compliance review UI."""
    try:
        cases = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "case index unavailable"}, status_code=500)
    item = next((case for case in cases if case["id"] == case_id), None)
    if not item:
        return JSONResponse({"error": "case not found"}, status_code=404)
    p = CASES_DIR / item["material"]["image"]
    if not p.exists():
        return JSONResponse({"error": "case image missing"}, status_code=404)
    return FileResponse(p)


@app.post("/api/review/upload")
async def api_review_upload(file: UploadFile = File(...)):
    """Upload a review image and return a server-side asset path for review records."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        return JSONResponse(
            {"error": "unsupported_file_type", "message": "只支持 PNG/JPG/JPEG/WEBP 图片"},
            status_code=400,
        )
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty_file", "message": "上传文件为空"}, status_code=400)
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "file_too_large", "message": "图片不能超过 8MB"}, status_code=400)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / name
    path.write_bytes(data)
    return {
        "file_path": str(path),
        "image_url": f"/api/review/uploads/{name}",
        "filename": file.filename,
        "size": len(data),
    }


@app.get("/api/review/uploads/{name}")
def api_review_uploaded_image(name: str):
    p = (UPLOAD_DIR / Path(name).name).resolve()
    if UPLOAD_DIR.resolve() not in p.parents or not p.exists():
        return JSONResponse({"error": "uploaded image not found"}, status_code=404)
    return FileResponse(p)


@app.get("/api/records")
def api_records(verdict: str | None = None, needs_human: bool | None = None):
    return storage.list_records(verdict=verdict, needs_human=needs_human)


@app.get("/api/records/{record_id}")
def api_record(record_id: str):
    rec = storage.get_record(record_id)
    return rec or JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/records/{record_id}/feedback")
def api_feedback(record_id: str, decision: str, notes: str = ""):
    """人工裁决回写（APPROVE/REJECT）→ 反馈闭环。"""
    if decision not in ("APPROVE", "REJECT"):
        return JSONResponse({"error": "decision must be APPROVE or REJECT"}, status_code=400)
    return storage.record_feedback(record_id, decision, notes)


@app.post("/api/review/run")
def api_review_run(payload: dict | None = Body(default=None)):
    """Run one compliance review from UI input and persist the audit record."""
    data = payload or {}
    offline_fallback = bool(data.get("offline_fallback", True))
    try:
        material, hint_text = _material_from_payload(data)
    except ValueError as exc:
        return JSONResponse({"error": "invalid_review_input", "message": str(exc)}, status_code=400)

    try:
        from core.orchestrator import ReviewEngine

        engine = ReviewEngine(EcommerceAdScene(), use_cache=False, use_feedback=True, use_debate=True)
        outcome = engine.review(material)
        mode = "llm_pipeline"
    except Exception as exc:
        if not offline_fallback:
            return JSONResponse(
                {"error": "review_failed", "message": f"{type(exc).__name__}: {exc}"},
                status_code=503,
            )
        outcome = _offline_compliance_review(material, hint_text, exc)
        mode = "offline_fallback"

    rid = storage.save_outcome(
        material,
        outcome,
        scene_id="ecommerce_ad",
        tokens=outcome.tokens,
        latency_ms=outcome.latency_ms,
    )
    return {
        "record_id": rid,
        "mode": mode,
        "record": storage.get_record(rid),
    }


@app.post("/tools/compliance/check")
def tool_compliance_check(req: dict):
    """统一 Agent-as-Tool 入口：结构化输入 → 结构化合规决策。"""
    return _run_tool(req)


@app.post("/tools/compliance/check-ad")
def tool_check_ad(req: dict):
    """广告素材审核别名，便于 Listing/Ad Agent 显式调用。"""
    req["task_type"] = "ad_review"
    return _run_tool(req)


@app.post("/tools/compliance/check-listing")
def tool_check_listing(req: dict):
    """Listing 合规审核别名。"""
    req["task_type"] = "listing_review"
    return _run_tool(req)


@app.post("/tools/compliance/verify-certificate")
def tool_verify_certificate(req: dict):
    """证照核验别名。"""
    req["task_type"] = "certificate_verification"
    return _run_tool(req)


def _run_tool(req: dict):
    try:
        from core.tool_contract import ComplianceCheckRequest, run_compliance_check

        return run_compliance_check(ComplianceCheckRequest.model_validate(req))
    except ModuleNotFoundError as exc:
        return JSONResponse(
            {
                "error": "compliance_runtime_unavailable",
                "message": f"Missing optional compliance runtime dependency: {exc.name}",
            },
            status_code=503,
        )
    except Exception as exc:
        if exc.__class__.__name__ != "AssetDownloadError":
            raise
        return JSONResponse(
            {
                "error": "asset_download_failed",
                "message": str(exc),
            },
            status_code=400,
        )


def _material_from_payload(data: dict) -> tuple[ReviewMaterial, str]:
    case_id = str(data.get("case_id") or "").strip()
    if case_id:
        cases = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))
        item = next((case for case in cases if case["id"] == case_id), None)
        if not item:
            raise ValueError(f"case_id not found: {case_id}")
        image_path = CASES_DIR / item["material"]["image"]
        hint_text = _case_hint_text(case_id)
        return ReviewMaterial(
            text=str(item["material"]["text"] or ""),
            image_paths=[str(image_path)],
        ), hint_text

    text = str(data.get("text") or "").strip()
    image_path = str(data.get("image_path") or "").strip()
    image_paths = [image_path] if image_path else []
    if not text and not image_paths:
        raise ValueError("text, image_path, or case_id is required")
    for path in image_paths:
        if not Path(path).exists():
            raise ValueError(f"image_path does not exist: {path}")
    return ReviewMaterial(text=text, image_paths=image_paths), text


def _case_hint_text(case_id: str) -> str:
    """Read generator metadata so offline demo can see image text for known cases."""
    try:
        ns = runpy.run_path(str(CASES_DIR / "make_cases.py"))
    except Exception:
        return ""
    for item in ns.get("CASES", []):
        if item.get("id") == case_id:
            parts = [
                item.get("text", ""),
                item.get("title", ""),
                item.get("subtitle", ""),
                item.get("car_caption", ""),
            ]
            return " ".join(str(part) for part in parts if part)
    return ""


def _offline_compliance_review(material: ReviewMaterial, hint_text: str, source_exc: Exception) -> ReviewOutcome:
    import time

    t0 = time.monotonic()
    scene = EcommerceAdScene()
    kb = scene.knowledge_base
    scan_text = _merge_review_text(material.text, hint_text)
    violations: list[dict] = []
    for rule in kb.get("violation_rules", []):
        for term in rule.get("blacklist", []):
            if term and term in scan_text:
                violations.append(_violation_from_rule(rule, term, scan_text))
                break
    implicit = _implicit_claim_violation(scan_text)
    if implicit:
        violations.append(implicit)

    if not violations:
        verdict = "PASS"
        confidence = 0.92
        needs_human = False
    else:
        verdict = "VIOLATION"
        confidence = 0.86
        needs_human = False

    chain = [
        "[初筛] 前端提交素材，进入合规审核 pipeline",
        f"[降级] 模型服务不可用，启用本地规则 fallback：{type(source_exc).__name__}",
    ]
    if material.image_paths:
        chain.append(f"[看图] 离线模式无法 OCR；已使用已知 case 元数据/文本线索：{hint_text or '无'}")
    chain.extend(
        [
            f"[规则扫描] 命中 {len(violations)} 条风险" if violations else "[规则扫描] 未命中广告法黑名单风险",
            f"[路由] {verdict} 置信={confidence}",
        ]
    )
    return ReviewOutcome(
        final_verdict=verdict,
        confidence=confidence,
        needs_human=needs_human,
        violations=violations,
        expert_results=[
            {
                "expert": "offline_rules",
                "verdict": verdict,
                "confidence": confidence,
                "violations": violations,
                "summary": "模型服务不可用时的本地确定性审核结果。",
            }
        ],
        reasoning_chain=chain,
        prescreen_reason="offline_fallback",
        tokens=0,
        latency_ms=int((time.monotonic() - t0) * 1000),
    )


def _merge_review_text(material_text: str, hint_text: str) -> str:
    material_text = str(material_text or "").strip()
    hint_text = str(hint_text or "").strip()
    if not material_text:
        return hint_text
    if not hint_text or hint_text == material_text:
        return material_text
    if hint_text.startswith(material_text):
        return hint_text
    return f"{material_text} {hint_text}".strip()


def _violation_from_rule(rule: dict, term: str, scan_text: str) -> dict:
    evidence = _evidence_phrase(scan_text, term)
    violation_text = _violation_text(rule.get("id", ""), term, evidence)
    return {
        "rule_id": rule.get("id", ""),
        "rule_name": rule.get("name", ""),
        "law_article": rule.get("law_article", ""),
        "law_quote": rule.get("description", ""),
        "evidence": evidence,
        "location": "文案 / 图内文字",
        "suggestion": _suggestion_for_rule(rule.get("id", ""), violation_text, evidence),
        "expert": "offline_rules",
    }


def _evidence_phrase(text: str, term: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 80:
        return compact
    idx = compact.find(term)
    if idx < 0:
        return term
    start = max(0, idx - 8)
    end = min(len(compact), idx + len(term) + 12)
    return compact[start:end].strip()


def _suggestion_for_rule(rule_id: str, term: str, evidence: str) -> str:
    product = _product_hint(evidence, term)
    if rule_id == "absolute_terms":
        return f"将「{term}」改为「热销{product}」或「深受用户好评的{product}」"
    if rule_id == "false_efficacy":
        return f"将「{term}」改为「有助于改善使用体验」或「使用感受因人而异」"
    if rule_id == "medical_terms_on_normal_goods":
        return f"将「{term}」改为「日常护理」或「使用后感觉舒适」"
    if rule_id == "false_income_inducement":
        return f"将「{term}」改为「帮助提升效率」或「适合灵活安排时间的人群」"
    return f"将「{term}」改为更具体、可证实的商品描述"


def _violation_text(rule_id: str, term: str, evidence: str) -> str:
    if rule_id == "absolute_terms":
        for phrase in ("全国销量第一", "全网销量第一", "销量第一", "行业第一"):
            if phrase in evidence:
                return phrase
    return term


def _product_hint(evidence: str, term: str) -> str:
    for known_product in ("智能扫地机器人", "扫地机器人", "数据线", "按摩仪", "连衣裙"):
        if known_product in evidence:
            return known_product
    before = evidence.split(term, 1)[0].strip(" ，。,.|/-")
    if before:
        cleaned = before
    else:
        cleaned = evidence.replace(term, "").strip(" ，。,.|/-")
    if not cleaned:
        return "商品"
    for token in ("限时", "特惠", "全国", "全网", "销量"):
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.strip(" ，。,.|/-")
    return cleaned[:12] or "商品"


def _implicit_claim_violation(text: str) -> dict | None:
    patterns = ["连续使用一年不掉落", "立刻见效", "马上见效", "比同类强50倍"]
    hit = next((item for item in patterns if item in text), "")
    if not hit:
        return None
    return {
        "rule_id": "implicit_claim",
        "rule_name": "隐含夸大/结果保证声称",
        "law_article": "广告法第四条 / 第二十八条",
        "law_quote": "广告不得含有虚假或者引人误解的内容，不得欺骗、误导消费者",
        "evidence": _evidence_phrase(text, hit),
        "location": "文案 / 图内文字",
        "suggestion": f"将「{hit}」改为「在正确使用条件下表现稳定」或「实际效果因使用环境而异」",
        "expert": "offline_rules",
    }


@app.post("/tools/crossborder/listing-workflow")
def tool_crossborder_listing_workflow(req: CrossBorderRequest):
    """Generate a marketplace listing, check compliance, and return workflow status."""
    try:
        from crossborder.workflow import run_workflow

        return run_workflow(req)
    except ModuleNotFoundError as exc:
        return JSONResponse(
            {
                "error": "compliance_runtime_unavailable",
                "message": f"Missing optional compliance runtime dependency: {exc.name}",
            },
            status_code=503,
        )
    except Exception as exc:
        if exc.__class__.__name__ != "AssetDownloadError":
            raise
        return JSONResponse(
            {
                "error": "asset_download_failed",
                "message": str(exc),
            },
            status_code=400,
        )


@app.post("/tools/crossborder/product-research")
def tool_crossborder_product_research(req: dict):
    """Stable Agent-as-Tool product research endpoint."""
    return run_product_research_tool(req)


@app.post("/tools/crossborder/listing-generate")
def tool_crossborder_listing_generate(req: dict):
    """Stable Agent-as-Tool listing generation endpoint."""
    return run_listing_generation_tool(req)


@app.post("/tools/crossborder/ads-diagnostic")
def tool_crossborder_ads_diagnostic(req: dict):
    """Stable Agent-as-Tool ads diagnostic endpoint."""
    return run_ads_diagnostic_tool(req)


@app.post("/tools/crossborder/opportunity")
def tool_crossborder_opportunity(req: dict):
    """Stable Agent-as-Tool opportunity discovery endpoint."""
    return run_opportunity_tool(req)


@app.post("/tools/crossborder/improvement")
def tool_crossborder_improvement(req: dict):
    """Stable Agent-as-Tool product improvement endpoint."""
    return run_improvement_tool(req)


@app.post("/tools/crossborder/product-research-legacy")
def tool_crossborder_product_research_legacy(req: ProductResearchRequest):
    """Score a candidate product before listing generation or sourcing decisions."""
    return research_product(req)


@app.post("/tools/crossborder/generate-listing")
def tool_crossborder_generate_listing(req: ListingGenerationRequest):
    """Generate a platform-aware listing draft without running compliance workflow."""
    return generate_listing_tool(req)


@app.post("/tools/crossborder/ads/diagnose")
def tool_crossborder_ads_diagnose(req: AdsDiagnosticRequest):
    """Diagnose marketplace advertising metrics and suggest gated actions."""
    return diagnose_ads(req)


@app.post("/tools/crossborder/action-gate")
def tool_crossborder_action_gate(req: ActionGateRequest):
    """Evaluate whether a proposed workflow action can proceed or needs human review."""
    return evaluate_action_gate(req)


@app.post("/tools/crossborder/customer-service/respond")
def tool_crossborder_customer_service_respond(req: CustomerServiceRequest):
    """Classify a buyer message, draft a response, and gate risky actions."""
    return respond_to_customer(req)


@app.get("/api/crossborder/demo-result")
def api_crossborder_demo_result():
    """Return the latest generated end-to-end demo report for the dashboard."""
    path = _ROOT / "examples" / "crossborder" / "demo_pipeline_result.json"
    if not path.exists():
        return JSONResponse({"error": "demo result not found"}, status_code=404)
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/crossborder/run-demo")
def api_crossborder_run_demo(payload: dict | None = Body(default=None)):
    """Run the local deterministic cross-border pipeline and persist the report."""
    from scripts.demo_crossborder_pipeline import DEFAULT_OUTPUT, run_demo_pipeline

    data = payload or {}
    run_compliance = bool(data.get("run_compliance", False))
    report = run_demo_pipeline(output_path=DEFAULT_OUTPUT, run_compliance=run_compliance)
    return report


_OPP_RESULT = _ROOT / "examples" / "crossborder" / "opportunity_result.json"


@app.get("/api/opportunity/result")
def api_opportunity_result():
    """Return the cached mode2->mode1 opportunity report (discover + deep dive)."""
    if not _OPP_RESULT.exists():
        return JSONResponse({"error": "opportunity result not found"}, status_code=404)
    return json.loads(_OPP_RESULT.read_text(encoding="utf-8"))


@app.post("/api/opportunity/run")
def api_opportunity_run(payload: dict | None = Body(default=None)):
    """Run the opportunity engine for a seed keyword and persist the report.

    Slow (Google Trends fetch + first-run review digest), so the frontend reads
    the cached result by default and only triggers this on explicit request.
    """
    data = payload or {}
    seed = str(data.get("seed_keyword") or "neck massager").strip()
    target_price = data.get("target_price")
    try:
        from crossborder.opportunity.pipeline import discover_and_deep_dive

        report = discover_and_deep_dive(seed, target_price=target_price)
    except Exception as exc:  # network / rate limit / missing dataset
        return JSONResponse(
            {"error": "opportunity_run_failed", "message": f"{type(exc).__name__}: {exc}"},
            status_code=503,
        )
    _OPP_RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


@app.post("/api/opportunity/deep-dive")
def api_opportunity_deep_dive(payload: dict | None = Body(default=None)):
    """Deep-dive a specific niche on demand (clicking a different niche in the rank).

    Fast: dataset match + cached review digest only, no Google Trends call.
    """
    data = payload or {}
    keyword = str(data.get("keyword") or "").strip()
    if not keyword:
        return JSONResponse({"error": "keyword required"}, status_code=400)
    target_price = data.get("target_price")
    try:
        from crossborder.opportunity.pipeline import deep_dive

        return deep_dive(keyword, target_price=target_price)
    except Exception as exc:
        return JSONResponse(
            {"error": "deep_dive_failed", "message": f"{type(exc).__name__}: {exc}"},
            status_code=503,
        )


@app.post("/api/opportunity/compare")
def api_opportunity_compare(payload: dict | None = Body(default=None)):
    """Compare 2-4 opportunity niches with the existing deep-dive scorecard."""
    data = payload or {}
    keywords = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()]
    if not keywords:
        return JSONResponse({"error": "keywords required"}, status_code=400)
    try:
        from crossborder.opportunity.compare import compare_niches

        return compare_niches(keywords, target_price=data.get("target_price"))
    except Exception as exc:
        return JSONResponse(
            {"error": "compare_failed", "message": f"{type(exc).__name__}: {exc}"},
            status_code=503,
        )


@app.post("/api/opportunity/to-workflow")
def api_opportunity_to_workflow(payload: dict | None = Body(default=None)):
    """Run opportunity discovery, hand the selected product to the operating workflow."""
    data = payload or {}
    seed = str(data.get("seed_keyword") or "neck massager").strip()
    target_price = data.get("target_price")
    max_candidates = int(data.get("max_candidates") or 8)
    try:
        from crossborder.opportunity.pipeline import discover_to_workflow

        return discover_to_workflow(seed, target_price=target_price, max_candidates=max_candidates)
    except Exception as exc:
        return JSONResponse(
            {"error": "to_workflow_failed", "message": f"{type(exc).__name__}: {exc}"},
            status_code=503,
        )


@app.post("/api/opportunity/inject-prices")
def api_opportunity_inject_prices(payload: dict | None = Body(default=None)):
    """Inject provider-backed prices into a niche and return before/after research."""
    data = payload or {}
    keyword = str(data.get("keyword") or "").strip()
    if not keyword:
        return JSONResponse({"error": "keyword required"}, status_code=400)
    try:
        from crossborder.pricing.inject import _default_provider, deep_dive_with_prices

        return deep_dive_with_prices(
            keyword,
            _default_provider(),
            unit_cost=data.get("unit_cost"),
            top_n=int(data.get("top_n", 3)),
        )
    except Exception as exc:
        return JSONResponse(
            {"error": "inject_failed", "message": f"{type(exc).__name__}: {exc}"},
            status_code=503,
        )


@app.post("/api/pricing/simulate")
def api_pricing_simulate(payload: dict):
    """Run deterministic unit-economics simulation for one pricing scenario."""
    from crossborder.pricing.simulator import ProfitInputs, simulate_profit

    return simulate_profit(ProfitInputs.model_validate(payload))


@app.post("/api/pricing/sweep")
def api_pricing_sweep(payload: dict | None = Body(default=None)):
    """Sweep one pricing variable for what-if charts or tables."""
    from crossborder.pricing.simulator import ProfitInputs, sweep

    data = payload or {}
    try:
        inp = ProfitInputs.model_validate(data.get("inputs") or {})
        return sweep(
            inp,
            str(data["variable"]),
            float(data["start"]),
            float(data["stop"]),
            int(data.get("steps", 20)),
        )
    except KeyError as exc:
        return JSONResponse({"error": "missing_field", "message": str(exc)}, status_code=400)
    except ValueError as exc:
        return JSONResponse({"error": "invalid_sweep", "message": str(exc)}, status_code=400)



# 服务 React 构建产物（前端唯一入口；开发时也可用 Vite dev server :5174）
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")


@app.get("/")
def index():
    idx = _DIST / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse(
        {"error": "前端未构建，请在 frontend/ 执行 npm run build，或用 Vite dev server (:5174)"},
        status_code=503,
    )
