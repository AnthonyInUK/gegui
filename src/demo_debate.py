"""
冲突触发辩论 demo：跑一条跨模态案例，展示 冲突检测 → 辩论 → 裁决 全过程，
并把终端输出导出为截图（SVG）+ markdown 存证。
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from core.orchestrator import ReviewEngine  # noqa: E402
from scenes.base import ReviewMaterial  # noqa: E402
from scenes.ecommerce_ad.scene import EcommerceAdScene  # noqa: E402

console = Console(record=True, width=100)

CASE_IMG = ROOT / "tests/ecommerce_ad/adversarial_cases/cross_borderline.png"
CASE_TEXT = "诚邀加入，时间灵活，多劳多得"


def main():
    console.print(Panel.fit(
        f"[bold]电商广告法审核 · 冲突触发辩论 demo[/bold]\n"
        f"文案：{CASE_TEXT}\n图片：豪车海报（跨模态暴富暗示）",
        title="待审素材", border_style="cyan",
    ))

    eng = ReviewEngine(EcommerceAdScene(), use_cache=False, use_feedback=False, use_debate=True)
    material = ReviewMaterial(text=CASE_TEXT, image_paths=[str(CASE_IMG)])
    outcome = eng.review(material)

    console.print(Rule("[bold]推理链（含冲突→辩论）[/bold]"))
    for step in outcome.reasoning_chain:
        style = "yellow" if ("冲突" in step or "辩论" in step) else "white"
        console.print(f"  {step}", style=style)

    console.print(Rule("[bold]最终结论[/bold]"))
    color = {"VIOLATION": "red", "PASS": "green", "NEEDS_HUMAN": "yellow"}.get(outcome.final_verdict, "white")
    console.print(f"判定：[{color}]{outcome.final_verdict}[/{color}]  "
                  f"置信度：{outcome.confidence}  需人工：{outcome.needs_human}")
    console.print(f"成本：{outcome.tokens} tokens / {outcome.latency_ms} ms")
    for v in outcome.violations:
        console.print(f"  ⚠️ [{v.get('expert')}] {v.get('rule_name')}：{v.get('evidence')}")
        console.print(f"     法条：{v.get('law_article')} | 建议：{v.get('suggestion')}")

    # 存证：终端截图（SVG）+ markdown
    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    console.save_svg(str(out_dir / "debate_demo.svg"), title="冲突触发辩论 demo")
    (out_dir / "debate_demo.md").write_text(
        "# 冲突触发辩论 demo\n\n"
        f"**素材**：{CASE_TEXT}（+ 豪车海报图）\n\n"
        f"**判定**：{outcome.final_verdict}　置信度 {outcome.confidence}　"
        f"成本 {outcome.tokens} tokens / {outcome.latency_ms} ms\n\n"
        "## 推理链\n" + "\n".join(f"- {s}" for s in outcome.reasoning_chain) + "\n\n"
        "## 违规项\n" + "\n".join(
            f"- [{v.get('expert')}] {v.get('rule_name')}：{v.get('evidence')} "
            f"（{v.get('law_article')}）→ {v.get('suggestion')}"
            for v in outcome.violations
        ) + "\n",
        encoding="utf-8",
    )
    console.print(f"\n[dim]已保存：docs/debate_demo.svg（截图）, docs/debate_demo.md[/dim]")


if __name__ == "__main__":
    main()
