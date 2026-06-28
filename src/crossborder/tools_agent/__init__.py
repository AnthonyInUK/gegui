"""Agent-as-Tool wrappers for cross-border ecommerce capabilities."""

__all__ = [
    "run_ads_diagnostic_tool",
    "run_improvement_tool",
    "run_listing_generation_tool",
    "run_opportunity_tool",
    "run_product_research_tool",
]


def __getattr__(name: str):
    if name == "run_ads_diagnostic_tool":
        from crossborder.tools_agent.ads_diagnostic_tool import run_ads_diagnostic_tool

        return run_ads_diagnostic_tool
    if name == "run_listing_generation_tool":
        from crossborder.tools_agent.listing_generation_tool import run_listing_generation_tool

        return run_listing_generation_tool
    if name == "run_improvement_tool":
        from crossborder.tools_agent.improvement_tool import run_improvement_tool

        return run_improvement_tool
    if name == "run_product_research_tool":
        from crossborder.tools_agent.product_research_tool import run_product_research_tool

        return run_product_research_tool
    if name == "run_opportunity_tool":
        from crossborder.tools_agent.opportunity_tool import run_opportunity_tool

        return run_opportunity_tool
    raise AttributeError(name)
