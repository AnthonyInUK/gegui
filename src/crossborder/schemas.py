"""
Schemas for the cross-border ecommerce agent.

These models describe the workflow boundary around product intake, listing
generation, compliance review, and final routing.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Platform(str, Enum):
    amazon = "amazon"
    temu = "temu"
    walmart = "walmart"


class Market(str, Enum):
    US = "US"
    EU = "EU"
    UK = "UK"
    JP = "JP"
    CN = "CN"


class WorkflowStatus(str, Enum):
    ready_to_publish = "ready_to_publish"
    needs_revision = "needs_revision"
    needs_human_review = "needs_human_review"
    blocked = "blocked"


class ActionDecision(str, Enum):
    allowed = "allowed"
    requires_human_review = "requires_human_review"
    blocked = "blocked"


class ProductBrief(BaseModel):
    title: str
    category: str = ""
    brand: str = ""
    sku: str = ""
    features: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    audience: str = ""
    image_urls: list[str] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ListingDraft(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    description: str = ""
    search_terms: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)

    def as_ad_copy(self) -> str:
        parts = [self.title, *self.bullets, self.description]
        return "\n".join(p for p in parts if p)


class CrossBorderRequest(BaseModel):
    platform: Platform = Platform.amazon
    market: Market = Market.US
    product: ProductBrief
    workflow_id: str = ""
    seller_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompetitorSnapshot(BaseModel):
    asin: str = ""
    title: str = ""
    brand: str = ""
    price: float | None = None
    rating: float | None = None
    review_count: int | None = None
    estimated_monthly_sales: int | None = None
    bsr: int | None = None
    prime: bool | None = None
    seller_count: int | None = None
    listing_quality_score: int | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class ReviewPainPoint(BaseModel):
    topic: str
    frequency: int = 1
    severity: int = 3
    example: str = ""
    source_asins: list[str] = Field(default_factory=list)


class ImprovementRequirement(BaseModel):
    pain_topic: str
    requirement: str
    priority: str
    frequency: int = 0
    severity: int = 0
    evidence_quote: str = ""
    source_asins: list[str] = Field(default_factory=list)


class ImprovementSpec(BaseModel):
    product_title: str = ""
    keyword: str = ""
    requirements: list[ImprovementRequirement] = Field(default_factory=list)
    differentiation_bullets: list[str] = Field(default_factory=list)
    emphasis_keywords: list[str] = Field(default_factory=list)
    honesty_note: str = ""
    audit: dict[str, Any] = Field(default_factory=dict)


class ImprovementSpecRequest(BaseModel):
    pain_points: list[ReviewPainPoint] = Field(default_factory=list)
    product_title: str = ""
    keyword: str = ""
    workflow_id: str = ""
    seller_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostModel(BaseModel):
    unit_cost: float | None = None
    inbound_shipping: float | None = None
    duty: float | None = None
    prep_packaging: float | None = None
    referral_fee: float | None = None
    fulfillment_fee: float | None = None
    storage_fee_monthly: float | None = None
    ads_cpa_estimate: float | None = None
    return_cost_allowance: float | None = None
    other_costs: float | None = None

    def total_landed_cost(self) -> float | None:
        values = [
            self.unit_cost,
            self.inbound_shipping,
            self.duty,
            self.prep_packaging,
            self.referral_fee,
            self.fulfillment_fee,
            self.storage_fee_monthly,
            self.ads_cpa_estimate,
            self.return_cost_allowance,
            self.other_costs,
        ]
        if self.unit_cost is None:
            return None
        return round(sum(value or 0 for value in values), 2)


class LogisticsProfile(BaseModel):
    weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    oversized: bool = False
    fragile: bool = False
    battery: bool = False
    liquid: bool = False
    magnet: bool = False
    hazmat: bool = False
    meltable: bool = False


class CompliancePrecheck(BaseModel):
    trademark_risk: bool = False
    patent_risk: bool = False
    restricted_category: bool = False
    certificate_required: bool = False
    medical_claim_risk: bool = False
    pesticide_claim_risk: bool = False
    children_product_risk: bool = False
    notes: list[str] = Field(default_factory=list)


class DataIntakeReport(BaseModel):
    source: str
    raw_meta_rows: int = 0
    raw_review_rows: int = 0
    matched_items: int = 0
    matched_reviews: int = 0
    generated_competitors: int = 0
    generated_pain_points: int = 0
    # Fraction of the competitor pool that actually carries a price (0-1).
    # The 2023 dataset omits price on ~80% of rows and per-niche coverage can
    # drop to ~5%, so this is surfaced rather than silently imputed.
    price_coverage: float = 0.0
    missing_fields: dict[str, int] = Field(default_factory=dict)
    inferred_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProductResearchRequest(BaseModel):
    platform: Platform = Platform.amazon
    market: Market = Market.US
    product: ProductBrief
    workflow_id: str = ""
    seller_id: str = ""
    target_price: float | None = None
    landed_cost: float | None = None
    monthly_search_volume: int | None = None
    competitor_count: int | None = None
    avg_rating: float | None = None
    review_pain_points: list[str] = Field(default_factory=list)
    competitors: list[CompetitorSnapshot] = Field(default_factory=list)
    pain_points: list[ReviewPainPoint] = Field(default_factory=list)
    cost_model: CostModel | None = None
    logistics: LogisticsProfile | None = None
    compliance_precheck: CompliancePrecheck | None = None
    data_intake_report: DataIntakeReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductResearchResult(BaseModel):
    decision: str
    opportunity_level: str
    score: int
    confidence: float
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    candidate_ranking: list[dict[str, Any]] = Field(default_factory=list)
    research_pipeline: list[dict[str, Any]] = Field(default_factory=list)
    selection_rationale: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    human_review_required: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)


class OpportunityToolRequest(BaseModel):
    seed_keyword: str = Field(min_length=1)
    target_price: float | None = None
    max_candidates: int = 8
    workflow_id: str = ""
    seller_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListingGenerationRequest(BaseModel):
    platform: Platform = Platform.amazon
    market: Market = Market.US
    product: ProductBrief
    workflow_id: str = ""
    seller_id: str = ""
    locale: str = "en-US"
    tone: str = "marketplace_native"
    keyword_hints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListingGenerationResult(BaseModel):
    decision: str
    listing: ListingDraft
    confidence: float = 1.0
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    human_review_required: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)


class ListingPackage(BaseModel):
    listing: ListingDraft
    platform: Platform
    market: Market
    seller_id: str = ""
    workflow_id: str = ""
    compliance_check_id: str = ""
    ready: bool = False


class CrossBorderResult(BaseModel):
    status: WorkflowStatus
    platform: Platform
    market: Market
    workflow_id: str = ""
    seller_id: str = ""
    listing: ListingDraft
    listing_package: ListingPackage | None = None
    compliance: dict[str, Any]
    compliance_check_id: str = ""
    revision_attempts: int = 0
    notes: list[str] = Field(default_factory=list)
    stage_results: list[dict[str, Any]] = Field(default_factory=list)


class AdsCampaignSnapshot(BaseModel):
    campaign_id: str = ""
    campaign_name: str = ""
    ad_group_id: str = ""
    keyword: str = ""
    match_type: str = ""
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    sales: float = 0.0
    orders: int = 0
    units: int = 0
    attributed_conversions: int | None = None


class AdsDiagnosticRequest(BaseModel):
    platform: Platform = Platform.amazon
    market: Market = Market.US
    workflow_id: str = ""
    seller_id: str = ""
    asin: str = ""
    target_acos: float = 0.3
    min_clicks_for_conversion_judgment: int = 20
    campaigns: list[AdsCampaignSnapshot] = Field(default_factory=list)
    listing_context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdsDiagnosticResult(BaseModel):
    decision: str
    risk_level: str
    metrics: dict[str, float | int] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)
    gated_actions: list[dict[str, Any]] = Field(default_factory=list)
    human_review_required: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)


class ActionGateRequest(BaseModel):
    action_type: str
    actor_agent: str = ""
    workflow_id: str = ""
    seller_id: str = ""
    platform: Platform = Platform.amazon
    market: Market = Market.US
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    risk_level: str = "medium"
    permissions: list[str] = Field(default_factory=list)


class ActionGateResult(BaseModel):
    decision: ActionDecision
    action_type: str
    allowed: bool = False
    human_review_required: bool = False
    reasons: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class CustomerServiceRequest(BaseModel):
    platform: Platform = Platform.amazon
    market: Market = Market.US
    workflow_id: str = ""
    seller_id: str = ""
    order_id: str = ""
    buyer_message: str
    product_title: str = ""
    order_status: str = ""
    delivery_status: str = ""
    days_since_delivery: int | None = None
    return_window_days: int = 30
    customer_history: dict[str, Any] = Field(default_factory=dict)
    policies: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerServiceResult(BaseModel):
    decision: str
    intent: str
    sentiment: str
    urgency: str
    draft_reply: str
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)
    gated_actions: list[dict[str, Any]] = Field(default_factory=list)
    human_review_required: bool = False
    audit: dict[str, Any] = Field(default_factory=dict)
