"""Platform policy profiles for cross-border listing workflows."""

from __future__ import annotations

from dataclasses import dataclass

from crossborder.schemas import ListingDraft, Platform, ProductBrief


RISKY_PHRASES = {
    "cure": "support",
    "treat": "support",
    "treatment": "support",
    "guaranteed": "designed to",
    "guarantee": "designed to",
    "best": "popular",
    "No.1": "featured",
    "NO.1": "featured",
    "#1": "featured",
}

MEDICAL_RISK_PATTERNS = {
    "chronic pain",
    "pain relief",
    "relieves pain",
    "relieve pain",
    "arthritis",
    "disease",
    "diagnose",
    "therapy",
}


@dataclass(frozen=True)
class PlatformPolicy:
    platform: Platform
    title_limit: int
    bullet_limit: int
    bullet_count: int
    search_terms_limit: int
    description_limit: int

    def soften(self, text: str) -> str:
        out = text
        for risky, safer in RISKY_PHRASES.items():
            out = out.replace(risky, safer)
        return out

    def clip(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "..."

    def normalize_listing(self, listing: ListingDraft) -> ListingDraft:
        return ListingDraft(
            title=self.clip(self.soften(listing.title), self.title_limit),
            bullets=[
                self.clip(self.soften(b), self.bullet_limit)
                for b in listing.bullets[: self.bullet_count]
            ],
            description=self.clip(self.soften(listing.description), self.description_limit),
            search_terms=_dedupe(
                [self.clip(self.soften(term), self.bullet_limit) for term in listing.search_terms]
            )[: self.search_terms_limit],
            image_urls=listing.image_urls,
            image_paths=listing.image_paths,
        )

    def preflight_issues(self, product: ProductBrief, listing: ListingDraft) -> list[dict]:
        text = " ".join(
            [
                product.title,
                product.category,
                " ".join(product.features),
                " ".join(product.claims),
                listing.as_ad_copy(),
            ]
        ).lower()
        hits = sorted(
            phrase
            for phrase in {*RISKY_PHRASES.keys(), *MEDICAL_RISK_PATTERNS}
            if phrase.lower() in text
        )
        if not hits:
            return []
        return [
            {
                "field": "product.claims",
                "text": ", ".join(hits),
                "severity": "medium",
                "reason": "Potential health or absolute claim requires safer wording/substantiation.",
                "suggestion": "Use comfort, relaxation, or general support language; avoid disease, cure, treatment, guarantee, or pain-relief claims.",
                "category": "marketplace_claim_preflight",
                "source_expert": f"{self.platform.value}_policy",
            }
        ]


POLICIES = {
    Platform.amazon: PlatformPolicy(
        platform=Platform.amazon,
        title_limit=180,
        bullet_limit=220,
        bullet_count=5,
        search_terms_limit=12,
        description_limit=2000,
    ),
    Platform.temu: PlatformPolicy(
        platform=Platform.temu,
        title_limit=120,
        bullet_limit=180,
        bullet_count=4,
        search_terms_limit=10,
        description_limit=1500,
    ),
    Platform.walmart: PlatformPolicy(
        platform=Platform.walmart,
        title_limit=150,
        bullet_limit=220,
        bullet_count=5,
        search_terms_limit=12,
        description_limit=2000,
    ),
}


def get_platform_policy(platform: Platform) -> PlatformPolicy:
    return POLICIES[platform]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(item.strip())
    return result
