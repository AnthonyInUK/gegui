"""
Listing generation agent.

The first version is deterministic and platform-aware enough for workflow
testing. Later, each platform can replace this with an LLM prompt or stricter
template without changing the workflow boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.platforms import get_platform_policy
from crossborder.schemas import (
    ListingDraft,
    ListingGenerationRequest,
    ListingGenerationResult,
    Platform,
    ProductBrief,
)


def generate_listing(product: ProductBrief, platform: Platform) -> ListingDraft:
    result = generate_listing_tool(
        ListingGenerationRequest(product=product, platform=platform)
    )
    return result.listing


def generate_listing_tool(req: ListingGenerationRequest) -> ListingGenerationResult:
    product = req.product
    policy = get_platform_policy(req.platform)
    title = _compose_title(product)
    bullets = _compose_bullets(product, req.platform)
    description = _compose_description(product, bullets)
    search_terms = _compose_search_terms(product, req.keyword_hints)
    draft = ListingDraft(
        title=title,
        bullets=bullets,
        description=description,
        search_terms=search_terms,
        image_urls=product.image_urls,
        image_paths=product.image_paths,
    )
    listing = policy.normalize_listing(draft)
    issues = _generation_issues(product, listing)
    return ListingGenerationResult(
        decision="requires_human_review" if _needs_human_review(product) else "pass",
        listing=listing,
        confidence=0.92 if not issues else 0.78,
        issues=issues,
        suggestions=_generation_suggestions(issues),
        human_review_required=_needs_human_review(product),
        audit={
            "listing_id": f"lst_{uuid4().hex[:12]}",
            "workflow_id": req.workflow_id,
            "tool": "crossborder.listing.generate",
            "runtime": "deterministic_template",
            "platform_policy": req.platform.value,
            "input_hash": _input_hash(req),
            "created_at": datetime.now(UTC).isoformat(),
            "version": "listing-generator-v1",
        },
    )


def apply_compliance_rewrite(listing: ListingDraft, suggested_rewrite: dict[str, str]) -> ListingDraft:
    rewrite = suggested_rewrite.get("ad_copy") or suggested_rewrite.get("description")
    if not rewrite:
        return listing
    return listing.model_copy(update={"description": rewrite})


def _compose_title(product: ProductBrief) -> str:
    pieces = [product.brand, product.title]
    if product.features:
        pieces.append(", ".join(product.features[:3]))
    return " ".join(p.strip() for p in pieces if p and p.strip())


def _compose_bullets(product: ProductBrief, platform: Platform) -> list[str]:
    policy = get_platform_policy(platform)
    base = product.features or product.claims or ["Built for everyday use"]
    bullets = []
    for feature in base[:5]:
        bullets.append(feature)
    if product.materials:
        bullets.append(f"Made with {', '.join(product.materials[:3])}")
    if product.audience:
        bullets.append(f"Designed for {product.audience}")
    return bullets[: policy.bullet_count]


def _compose_description(product: ProductBrief, bullets: list[str]) -> str:
    intro = f"{product.title} is designed for practical, everyday use."
    details = " ".join(bullets)
    return f"{intro} {details}".strip()


def _compose_search_terms(product: ProductBrief, keyword_hints: list[str] | None = None) -> list[str]:
    terms = [product.category, *(keyword_hints or []), *product.features, *product.materials]
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        normalized = term.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(term.strip())
    return result[:12]


def _generation_issues(product: ProductBrief, listing: ListingDraft) -> list[dict]:
    issues = []
    if not product.features and not product.claims:
        issues.append(
            {
                "category": "thin_product_input",
                "severity": "medium",
                "reason": "No product features or claims were provided.",
                "suggestion": "Provide concrete features, use cases, materials, dimensions, or audience context.",
            }
        )
    if len(listing.bullets) < 3:
        issues.append(
            {
                "category": "short_listing",
                "severity": "low",
                "reason": "Listing has fewer than three bullets.",
                "suggestion": "Add more buyer-facing benefits or product specifications.",
            }
        )
    return issues


def _generation_suggestions(issues: list[dict]) -> list[str]:
    if not issues:
        return ["Listing draft is ready for platform rules and compliance review."]
    return [issue["suggestion"] for issue in issues]


def _needs_human_review(product: ProductBrief) -> bool:
    return not product.features and not product.claims


def _input_hash(req: ListingGenerationRequest) -> str:
    payload = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python src/crossborder/listing_agent.py <request.json>")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = generate_listing_tool(ListingGenerationRequest.model_validate(payload))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
