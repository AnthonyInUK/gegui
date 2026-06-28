# 冲突触发辩论 demo

**素材**：诚邀加入，时间灵活，多劳多得（+ 豪车海报图）

**判定**：VIOLATION　置信度 0.9　成本 10775 tokens / 33341 ms

## 推理链
- [初筛] 含图片，需多模态复审（图内可能藏违禁词）
- [看图] OCR=['诚邀加入'] 可疑=[]
- [并行] 3 专家并发扇出（asyncio）
- [专家:ad_law] verdict=PASS conf=1.0 违规0项
- [专家:qualification] verdict=PASS conf=1.0 违规0项
- [专家:cross_modal] verdict=VIOLATION conf=0.9 违规1项
- [冲突检测] 分歧：['cross_modal'] 判违规，['ad_law', 'qualification'] 判无违规
- [辩论] 触发一轮专家互评，已据对方意见重新裁决
- [辩论后:ad_law] verdict=PASS conf=0.9 违规0项
- [辩论后:qualification] verdict=VIOLATION conf=0.9 违规1项
- [辩论后:cross_modal] verdict=VIOLATION conf=0.9 违规1项
- [路由] VIOLATION 校准后置信=0.9 阈值=0.75

## 违规项
- [qualification] 虚假收入/暴富暗示：诚邀加入，时间灵活，多劳多得 + 图中黑色的简化汽车轮廓图 （广告法第四条（虚假广告））→ 修改文案，避免使用可能引起误解的收入暗示，如'多劳多得'。
- [cross_modal] 虚假收入/暴富暗示：诚邀加入，时间灵活，多劳多得 + 图中黑色的简化汽车轮廓图 （广告法第四条（虚假广告））→ 移除豪车图像或修改文案，避免暗示轻松获得高收入
