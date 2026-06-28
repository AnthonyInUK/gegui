"""Asset intake stage for product images and certificates."""

from __future__ import annotations

from crossborder.stages.base import StageMode, StageResult, WorkflowContext


def run_assets_stage(ctx: WorkflowContext) -> StageResult:
    product = ctx.request.product
    document_urls = [doc.get("file_url") for doc in product.documents if doc.get("file_url")]
    document_paths = [doc.get("file_path") for doc in product.documents if doc.get("file_path")]
    ctx.derived["assets"] = {
        "image_urls": product.image_urls,
        "image_paths": product.image_paths,
        "document_urls": document_urls,
        "document_paths": document_paths,
    }
    return ctx.add_stage(
        StageResult(
            name="assets",
            mode=StageMode.rule_only,
            summary="Collected image and certificate references for downstream tool calls.",
            artifacts={
                "image_url_count": len(product.image_urls),
                "image_path_count": len(product.image_paths),
                "document_url_count": len(document_urls),
                "document_path_count": len(document_paths),
            },
        )
    )

