"""
图片输入处理 —— 本地图片 → Strands 多模态 content block

Strands 的图片 content block 格式：
    {"image": {"format": "png", "source": {"bytes": b"..."}}}
用户消息是 content block 列表：
    [{"text": "..."}, {"image": {...}}, ...]

为省 token，过大的图会等比缩放到最长边 ≤ MAX_EDGE。
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

MAX_EDGE = 1536  # 最长边像素上限，超过则等比缩放（省 token，OCR 仍够清晰）

# PIL 格式名 → Strands 支持的 ImageFormat
_FORMAT_MAP = {
    "JPEG": "jpeg",
    "JPG": "jpeg",
    "PNG": "png",
    "GIF": "gif",
    "WEBP": "webp",
}


def load_image_block(path: str | Path) -> dict:
    """把一张本地图片读成 Strands 的 image content block。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"图片不存在: {path}")

    with Image.open(path) as img:
        fmt = _FORMAT_MAP.get((img.format or "").upper())

        # 等比缩放过大图片
        resized = max(img.size) > MAX_EDGE
        if resized:
            img.thumbnail((MAX_EDGE, MAX_EDGE))

        if fmt is None or resized:
            # 缩放过 或 格式不支持 → 重新编码为 PNG
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            data, fmt = buf.getvalue(), "png"
        else:
            # 原图未动且格式支持 → 直接用原始字节
            data = path.read_bytes()

    return {"image": {"format": fmt, "source": {"bytes": data}}}


def build_user_content(text: str, image_paths: list[str] | None = None) -> list[dict]:
    """组装一条多模态用户消息：文本 + 若干图片。

    返回的 content block 列表可直接喂给 Strands agent：agent(content)。
    """
    content: list[dict] = []
    if text:
        content.append({"text": text})
    for p in image_paths or []:
        content.append(load_image_block(p))
    return content
