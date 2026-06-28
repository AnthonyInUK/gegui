"""
审核结果存储（SQLite，场景无关，全离线）

一张主表 review_records 承载：
  - 素材与最终结论（含违规明细、专家结论、推理链 → 可审计）
  - 人工裁决（反馈闭环的数据来源）
  - 成本/延迟统计（tokens、耗时 → 量化经济账）
  - 内容哈希（去重缓存）

设计成纯本地读写，不依赖任何模型调用。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.schemas import ReviewOutcome
from scenes.base import ReviewMaterial

DB_PATH = Path(__file__).parent.parent / "db" / "reviews.db"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS review_records (
            id            TEXT PRIMARY KEY,
            scene_id      TEXT,
            content_hash  TEXT,
            material_text TEXT,
            image_paths   TEXT,
            final_verdict TEXT,
            confidence    REAL,
            needs_human   INTEGER,
            violations    TEXT,     -- JSON
            expert_results TEXT,    -- JSON
            reasoning_chain TEXT,   -- JSON，审计
            human_decision TEXT,    -- APPROVE/REJECT/NULL，反馈闭环
            human_notes   TEXT,
            tokens        INTEGER DEFAULT 0,
            latency_ms    INTEGER DEFAULT 0,
            created_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hash ON review_records(content_hash);
        CREATE INDEX IF NOT EXISTS idx_verdict ON review_records(final_verdict);
        """)


def content_hash(material: ReviewMaterial) -> str:
    """对素材内容算哈希（文案 + 图片字节），用于去重缓存。"""
    h = hashlib.sha256()
    h.update(material.text.encode("utf-8"))
    for p in sorted(material.image_paths):
        try:
            h.update(hashlib.sha256(Path(p).read_bytes()).digest())
        except OSError:
            h.update(p.encode("utf-8"))
    return h.hexdigest()


def get_cached(material: ReviewMaterial) -> ReviewOutcome | None:
    """命中相同内容的历史结论则直接复用（省 API）。"""
    init_db()
    ch = content_hash(material)
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM review_records WHERE content_hash=? ORDER BY created_at DESC LIMIT 1",
            (ch,),
        ).fetchone()
    return _row_to_outcome(row) if row else None


def save_outcome(
    material: ReviewMaterial,
    outcome: ReviewOutcome,
    scene_id: str,
    tokens: int = 0,
    latency_ms: int = 0,
) -> str:
    """落库一条审核记录，返回 record_id。"""
    init_db()
    rid = f"REV-{uuid.uuid4().hex[:8].upper()}"
    with _conn() as c:
        c.execute(
            """INSERT INTO review_records VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid, scene_id, content_hash(material),
                material.text, json.dumps(material.image_paths, ensure_ascii=False),
                outcome.final_verdict, outcome.confidence, int(outcome.needs_human),
                json.dumps(outcome.violations, ensure_ascii=False),
                json.dumps(outcome.expert_results, ensure_ascii=False),
                json.dumps(outcome.reasoning_chain, ensure_ascii=False),
                None, None, tokens, latency_ms,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return rid


def record_feedback(record_id: str, decision: str, notes: str = "") -> dict:
    """写入人工裁决（反馈闭环入口）。decision: APPROVE / REJECT。"""
    init_db()
    with _conn() as c:
        cur = c.execute(
            "UPDATE review_records SET human_decision=?, human_notes=? WHERE id=?",
            (decision, notes, record_id),
        )
        ok = cur.rowcount > 0
    return {"record_id": record_id, "updated": ok, "decision": decision}


def get_record(record_id: str) -> dict | None:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM review_records WHERE id=?", (record_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_records(verdict: str | None = None, needs_human: bool | None = None) -> list[dict]:
    init_db()
    q, params = "SELECT * FROM review_records WHERE 1=1", []
    if verdict:
        q += " AND final_verdict=?"; params.append(verdict)
    if needs_human is not None:
        q += " AND needs_human=?"; params.append(int(needs_human))
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def stats() -> dict:
    """看板用聚合统计：各判定计数、待人工数、累计成本。"""
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT final_verdict, needs_human, tokens FROM review_records").fetchall()
    total = len(rows)
    by_verdict: dict[str, int] = {}
    for r in rows:
        by_verdict[r["final_verdict"]] = by_verdict.get(r["final_verdict"], 0) + 1
    return {
        "total": total,
        "by_verdict": by_verdict,
        "needs_human": sum(1 for r in rows if r["needs_human"]),
        "total_tokens": sum(r["tokens"] or 0 for r in rows),
    }


def get_correction_samples(scene_id: str | None = None) -> list[dict]:
    """取人工推翻了模型判断的样本（反馈闭环：用作专家 few-shot 纠正）。

    '推翻' = 模型判 VIOLATION 但人工 REJECT，或模型 PASS 但人工 APPROVE。
    纠正样本不跨场景，故按 scene_id 过滤。
    """
    init_db()
    q = """SELECT * FROM review_records
           WHERE human_decision IS NOT NULL
             AND ((final_verdict='VIOLATION' AND human_decision='REJECT')
               OR (final_verdict='PASS' AND human_decision='APPROVE'))"""
    params: list = []
    if scene_id:
        q += " AND scene_id=?"; params.append(scene_id)
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("image_paths", "violations", "expert_results", "reasoning_chain"):
        d[k] = json.loads(d[k]) if d.get(k) else []
    d["needs_human"] = bool(d["needs_human"])
    return d


def _row_to_outcome(row: sqlite3.Row) -> ReviewOutcome:
    d = _row_to_dict(row)
    return ReviewOutcome(
        final_verdict=d["final_verdict"],
        confidence=d["confidence"] or 0.0,
        needs_human=d["needs_human"],
        violations=d["violations"],
        expert_results=d["expert_results"],
        reasoning_chain=d["reasoning_chain"] + ["[缓存] 命中相同内容历史结论"],
        prescreen_reason="",
    )
