"""
Agent-as-Tool contract for the compliance engine.

This layer keeps the existing ReviewEngine/Scene abilities intact, but exposes
them as stable, machine-readable tool inputs and outputs for other agents.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from core import storage
from core.model_provider import active_provider_name
from core.orchestrator import ReviewEngine
from scenes.base import ReviewMaterial, Scene
from scenes.ecommerce_ad.scene import EcommerceAdScene
from scenes.merchant_license.scene import MerchantLicenseScene


POLICY_VERSION = "local-kb-2026-06-20"
TOOL_CONTRACT_VERSION = "compliance-tool-v1"
ROOT = Path(__file__).resolve().parent.parent.parent
DOWNLOAD_DIR = ROOT / "src" / "db" / "downloaded_assets"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 15
ALLOWED_URL_SCHEMES = {"http", "https"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class AssetDownloadError(ValueError):
    """Raised when a remote image/certificate cannot be downloaded safely."""


class TaskType(str, Enum):
    ad_review = "ad_review"
    listing_review = "listing_review"
    product_eligibility = "product_eligibility"
    certificate_verification = "certificate_verification"


class Decision(str, Enum):
    passed = "pass"
    requires_revision = "requires_revision"
    requires_human_review = "requires_human_review"
    blocked = "blocked"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"


class ProductInput(BaseModel):
    title: str = ""
    category: str = ""
    claims: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ContentInput(BaseModel):
    title: str = ""
    description: str = ""
    ad_copy: str = ""
    image_urls: list[str] = Field(default_factory=list)
    image_paths: list[str] = Field(
        default_factory=list,
        description="Local image paths currently supported by the engine.",
    )


class DocumentInput(BaseModel):
    type: str = ""
    file_url: str = ""
    file_path: str = Field(
        default="",
        description="Local document/image path currently supported by the engine.",
    )
    issuer: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CallerInput(BaseModel):
    agent: str = ""
    workflow_id: str = ""
    permissions: list[Literal["read", "analyze", "suggest", "block"]] = Field(
        default_factory=lambda: ["read", "analyze", "suggest"]
    )


class ComplianceCheckRequest(BaseModel):
    task_type: TaskType = TaskType.ad_review
    platform: str = ""
    market: str = "CN"
    product: ProductInput = Field(default_factory=ProductInput)
    content: ContentInput = Field(default_factory=ContentInput)
    documents: list[DocumentInput] = Field(default_factory=list)
    caller: CallerInput = Field(default_factory=CallerInput)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComplianceIssue(BaseModel):
    field: str = ""
    text: str = ""
    severity: Literal["low", "medium", "high"] = "medium"
    reason: str = ""
    suggestion: str = ""
    category: str = ""
    source_expert: str = ""


class RequiredDocument(BaseModel):
    name: str
    reason: str = ""


class EvidenceItem(BaseModel):
    source: str = "policy_knowledge_base"
    title: str = ""
    summary: str = ""


class AuditInfo(BaseModel):
    check_id: str
    workflow_id: str = ""
    input_hash: str
    model: str
    policy_version: str = POLICY_VERSION
    ruleset_version: str
    tool_contract_version: str = TOOL_CONTRACT_VERSION
    created_at: str
    reasoning_chain: list[str] = Field(default_factory=list)


class ComplianceCheckResponse(BaseModel):
    decision: Decision
    risk_level: RiskLevel
    confidence: float
    risk_categories: list[str] = Field(default_factory=list)
    issues: list[ComplianceIssue] = Field(default_factory=list)
    required_documents: list[RequiredDocument] = Field(default_factory=list)
    suggested_rewrite: dict[str, str] = Field(default_factory=dict)
    human_review_required: bool = False
    evidence: list[EvidenceItem] = Field(default_factory=list)
    audit: AuditInfo


def run_compliance_check(req: ComplianceCheckRequest) -> ComplianceCheckResponse:
    scene = _scene_for(req.task_type)
    material = _material_for(req)
    outcome = ReviewEngine(scene, use_cache=True, use_feedback=True, use_debate=True).review(material)

    record_id = storage.save_outcome(
        material,
        outcome,
        scene_id=scene.scene_id,
        tokens=outcome.tokens,
        latency_ms=outcome.latency_ms,
    )

    issues = [_issue_from_violation(v) for v in outcome.violations]
    risk_categories = sorted({i.category for i in issues if i.category})
    required_docs = _required_documents(outcome.violations)
    suggested_rewrite = _suggested_rewrite(req, issues)

    return ComplianceCheckResponse(
        decision=_decision_for(outcome.final_verdict, outcome.confidence),
        risk_level=_risk_level_for(outcome.final_verdict, outcome.confidence),
        confidence=outcome.confidence,
        risk_categories=risk_categories,
        issues=issues,
        required_documents=required_docs,
        suggested_rewrite=suggested_rewrite,
        human_review_required=outcome.needs_human,
        evidence=_evidence_for(outcome.violations, scene),
        audit=AuditInfo(
            check_id=record_id,
            workflow_id=req.caller.workflow_id,
            input_hash=storage.content_hash(material),
            model=active_provider_name("text"),
            ruleset_version=scene.scene_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            reasoning_chain=outcome.reasoning_chain,
        ),
    )


def _scene_for(task_type: TaskType) -> Scene:
    if task_type == TaskType.certificate_verification:
        return MerchantLicenseScene()
    return EcommerceAdScene()


def _material_for(req: ComplianceCheckRequest) -> ReviewMaterial:
    text_parts = [
        req.product.title,
        req.product.category,
        " ".join(req.product.claims),
        req.content.title,
        req.content.description,
        req.content.ad_copy,
    ]
    doc_text = " ".join(
        f"{d.type} {d.issuer} {d.file_url} {d.file_path}".strip() for d in req.documents
    )
    downloaded = _download_request_assets(req)
    image_paths = list(req.content.image_paths)
    image_paths.extend(downloaded["content_image_paths"])
    image_paths.extend(d.file_path for d in req.documents if d.file_path)
    image_paths.extend(downloaded["document_file_paths"])
    return ReviewMaterial(
        text="\n".join(p for p in text_parts if p).strip() or doc_text,
        image_paths=image_paths,
        metadata={
            "task_type": req.task_type.value,
            "platform": req.platform,
            "market": req.market,
            "product": req.product.model_dump(),
            "documents": [d.model_dump() for d in req.documents],
            "caller": req.caller.model_dump(),
            "downloaded_assets": downloaded,
            **req.metadata,
        },
    )


def _download_request_assets(req: ComplianceCheckRequest) -> dict[str, list[str]]:
    content_paths = [
        _download_remote_asset(url, kind="content_image")
        for url in req.content.image_urls
        if url
    ]
    document_paths = [
        _download_remote_asset(doc.file_url, kind=f"document_{doc.type or 'file'}")
        for doc in req.documents
        if doc.file_url
    ]
    return {
        "content_image_paths": content_paths,
        "document_file_paths": document_paths,
    }


def _download_remote_asset(url: str, kind: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise AssetDownloadError(f"unsupported_url_scheme: {parsed.scheme or '<empty>'}")

    ext = Path(parsed.path).suffix.lower()
    content_type = ""
    if ext and ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise AssetDownloadError(f"unsupported_asset_type: {ext}")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    existing = next(DOWNLOAD_DIR.glob(f"{url_hash}.*"), None)
    if existing:
        return str(existing)

    req = Request(
        url,
        headers={
            "User-Agent": "hoyoverse-compliance-agent/1.0",
            "Accept": "image/*,*/*;q=0.8",
        },
        method="GET",
    )

    try:
        with urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            declared_length = resp.headers.get("content-length")
            if declared_length and int(declared_length) > MAX_DOWNLOAD_BYTES:
                raise AssetDownloadError("asset_too_large")
            if content_type and not content_type.startswith("image/"):
                raise AssetDownloadError(f"unsupported_content_type: {content_type}")
            if not ext:
                ext = mimetypes.guess_extension(content_type) or ".img"
            if ext == ".jpe":
                ext = ".jpg"
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise AssetDownloadError(f"unsupported_asset_type: {ext}")

            tmp_path = DOWNLOAD_DIR / f"{url_hash}.tmp"
            final_path = DOWNLOAD_DIR / f"{url_hash}{ext}"
            with tmp_path.open("wb") as f:
                shutil.copyfileobj(resp, _LimitedWriter(f, MAX_DOWNLOAD_BYTES))
            tmp_path.replace(final_path)
            return str(final_path)
    except AssetDownloadError:
        raise
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        raise AssetDownloadError(f"asset_download_failed: {kind}") from exc


class _LimitedWriter:
    def __init__(self, file_obj, limit: int):
        self.file_obj = file_obj
        self.limit = limit
        self.written = 0

    def write(self, data: bytes) -> int:
        self.written += len(data)
        if self.written > self.limit:
            raise AssetDownloadError("asset_too_large")
        return self.file_obj.write(data)


def _decision_for(verdict: str, confidence: float) -> Decision:
    if verdict == "PASS":
        return Decision.passed
    if verdict == "NEEDS_HUMAN":
        return Decision.requires_human_review
    if confidence >= 0.9:
        return Decision.blocked
    return Decision.requires_revision


def _risk_level_for(verdict: str, confidence: float) -> RiskLevel:
    if verdict == "PASS":
        return RiskLevel.low
    if verdict == "NEEDS_HUMAN":
        return RiskLevel.unknown
    if confidence >= 0.9:
        return RiskLevel.high
    return RiskLevel.medium


def _issue_from_violation(v: dict[str, Any]) -> ComplianceIssue:
    rule_id = str(v.get("rule_id") or "")
    evidence = str(v.get("evidence") or "")
    return ComplianceIssue(
        field=str(v.get("location") or "content"),
        text=evidence,
        severity="high" if rule_id in {"absolute_terms", "forgery_suspect"} else "medium",
        reason=str(v.get("rule_name") or v.get("law_article") or rule_id),
        suggestion=str(v.get("suggestion") or ""),
        category=rule_id,
        source_expert=str(v.get("expert") or ""),
    )


def _required_documents(violations: list[dict[str, Any]]) -> list[RequiredDocument]:
    docs: dict[str, str] = {}
    for v in violations:
        text = " ".join(str(v.get(k) or "") for k in ("rule_id", "rule_name", "suggestion"))
        if "资质" in text or "蓝帽" in text or "许可证" in text or "missing_license" in text:
            docs.setdefault("qualification_certificate", "相关类目或功效声明需要补充资质证明。")
        if "医疗" in text or "功效" in text or "medical" in text:
            docs.setdefault("test_report", "功效或医疗相关声明需要证据支持。")
    return [RequiredDocument(name=k, reason=v) for k, v in docs.items()]


def _suggested_rewrite(req: ComplianceCheckRequest, issues: list[ComplianceIssue]) -> dict[str, str]:
    if not issues:
        return {}
    suggestion = next((i.suggestion for i in issues if i.suggestion), "")
    if not suggestion:
        suggestion = "移除绝对化、医疗功效、收益承诺等高风险表达，改为客观描述。"
    target = req.content.ad_copy or req.content.description or req.content.title
    if not target:
        return {}
    return {"ad_copy": suggestion}


def _evidence_for(violations: list[dict[str, Any]], scene: Scene) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for v in violations:
        items.append(
            EvidenceItem(
                title=str(v.get("law_article") or v.get("rule_name") or scene.display_name),
                summary=str(v.get("law_quote") or v.get("evidence") or ""),
            )
        )
    if not items:
        items.append(
            EvidenceItem(
                title=scene.display_name,
                summary="No policy violations were detected by the configured scene rules.",
            )
        )
    return items
