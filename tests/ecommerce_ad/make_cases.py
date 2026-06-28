"""
生成电商广告法对抗测试样本（离线，PIL，不调模型）

把违禁内容做进图片里 —— 既是最强多模态卖点（纯文本审核漏判），
又确保素材带图、能过初筛进入 agent 复审层。

产出：
  adversarial_cases/*.png   样本图
  cases.json                清单（含预期判定 + 规避类型标签，供 eval）
"""

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
IMG_DIR = HERE / "adversarial_cases"
IMG_DIR.mkdir(parents=True, exist_ok=True)

_FONT = next(
    (p for p in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ] if os.path.exists(p)),
    None,
)


def _font(size):
    return ImageFont.truetype(_FONT, size) if _FONT else ImageFont.load_default()


def _poster(path, title, subtitle="", title_color="#c0392b"):
    """生成一张电商海报式图片，标题文字做进画面。"""
    img = Image.new("RGB", (800, 500), "#f5f5f5")
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 760, 190], fill=title_color)
    d.text((70, 85), title, font=_font(58), fill="white")
    if subtitle:
        d.text((70, 250), subtitle, font=_font(34), fill="#333")
    img.save(path)


def _car_poster(path, caption):
    """画一辆简单豪车 + 文案（跨模态：图是车、文案暗示暴富）。"""
    img = Image.new("RGB", (800, 500), "#eef2f5")
    d = ImageDraw.Draw(img)
    # 车身
    d.rectangle([180, 280, 620, 360], fill="#222")
    d.polygon([(260, 280), (340, 220), (500, 220), (560, 280)], fill="#333")
    d.ellipse([230, 340, 300, 410], fill="#000")
    d.ellipse([500, 340, 570, 410], fill="#000")
    d.text((60, 60), caption, font=_font(40), fill="#c0392b")
    img.save(path)


def _case(case_id, evasion, expected, text, title=None, subtitle="", car_caption=None):
    item = {
        "id": case_id,
        "evasion": evasion,
        "expected": expected,
        "text": text,
    }
    if car_caption:
        item["car_caption"] = car_caption
    else:
        item["title"] = title or ""
        item["subtitle"] = subtitle
    return item


# 分层生成 80 条样本：
#   24 条绝对化/规避表达、20 条医疗功效/资质、16 条跨模态/导流、20 条正常素材。
# 目标不是模拟真实线上分布，而是覆盖最容易暴露 Agent 设计问题的边界类型。
CASES = [
    # —— 违规：绝对化用语 + 对抗规避（24）——
    _case("abs_plain_01", "图内藏字", "VIOLATION", "智能扫地机器人", "全国销量第一", "限时特惠"),
    _case("abs_plain_02", "图内藏字", "VIOLATION", "蓝牙耳机", "全网排名第一", "热销爆款"),
    _case("abs_plain_03", "图内藏字", "VIOLATION", "空气净化器", "行业最高级", "旗舰新品"),
    _case("abs_plain_04", "图内藏字", "VIOLATION", "儿童学习桌", "全国首选", "新学期推荐"),
    _case("abs_split_01", "拆字插符", "VIOLATION", "高端护肤面霜", "国#家#级 品质", "匠心之作"),
    _case("abs_split_02", "拆字插符", "VIOLATION", "空气炸锅", "全-网-最-低-价", "今日专享"),
    _case("abs_split_03", "拆字插符", "VIOLATION", "运动鞋", "第—一选择", "轻便回弹"),
    _case("abs_split_04", "拆字插符", "VIOLATION", "床垫", "最※好睡感", "深睡体验"),
    _case("abs_split_05", "拆字插符", "VIOLATION", "吹风机", "顶·级配置", "高速护发"),
    _case("abs_traditional_01", "繁体异体", "VIOLATION", "蓝牙耳机", "全網銷量第一", "热销爆款"),
    _case("abs_traditional_02", "繁体异体", "VIOLATION", "保温杯", "國家級品質", "通勤便携"),
    _case("abs_traditional_03", "繁体异体", "VIOLATION", "家用投影仪", "業界最高級", "影院体验"),
    _case("abs_traditional_04", "繁体异体", "VIOLATION", "行李箱", "全網最低價", "假期出游"),
    _case("abs_homophone_01", "谐音替换", "VIOLATION", "运动鞋", "销量NO.1", "人气之王"),
    _case("abs_homophone_02", "谐音替换", "VIOLATION", "洗地机", "国jia级标准", "深度清洁"),
    _case("abs_homophone_03", "谐音替换", "VIOLATION", "电动牙刷", "quan网第一", "限时福利"),
    _case("abs_homophone_04", "谐音替换", "VIOLATION", "羽绒服", "TOP壹爆款", "冬季上新"),
    _case("abs_semantic_01", "语义擦边", "VIOLATION", "儿童学习桌", "找不到更低价", "同款放心比"),
    _case("abs_semantic_02", "语义擦边", "VIOLATION", "筋膜枪", "没人比我们更强", "运动恢复"),
    _case("abs_semantic_03", "语义擦边", "VIOLATION", "智能门锁", "全行业都服的安全", "安心到家"),
    _case("abs_semantic_04", "语义擦边", "VIOLATION", "家用咖啡机", "闭眼买不会错", "办公室推荐"),
    _case("abs_symbol_01", "符号规避", "VIOLATION", "眼霜", "最|佳淡纹搭档", "紧致护理"),
    _case("abs_symbol_02", "符号规避", "VIOLATION", "路由器", "独·一·无·二", "高速覆盖"),
    _case("abs_symbol_03", "符号规避", "VIOLATION", "电饭煲", "冠 军 品 牌", "柴火饭口感"),

    # —— 违规：医疗/功效用语与类目资质（20）——
    _case("medical_cosmetic_01", "医疗用语", "VIOLATION", "保湿面霜 日常护理", "消炎祛痘", "治疗痘痘 一周见效"),
    _case("medical_cosmetic_02", "医疗用语", "VIOLATION", "普通护肤精华，焕亮肌肤", "7天淡斑见效", "使用前后对比"),
    _case("medical_cosmetic_03", "医疗用语", "VIOLATION", "洗发水", "防脱生发", "改善毛囊问题"),
    _case("medical_cosmetic_04", "医疗用语", "VIOLATION", "身体乳", "修复湿疹", "敏感肌救星"),
    _case("medical_food_01", "医疗用语", "VIOLATION", "日常营养软糖", "改善失眠", "调理三高 增强免疫"),
    _case("medical_food_02", "医疗用语", "VIOLATION", "早餐麦片", "降血糖配方", "中老年适用"),
    _case("medical_food_03", "医疗用语", "VIOLATION", "蜂蜜饮品", "抗幽门螺杆菌", "饭后来一杯"),
    _case("medical_food_04", "医疗用语", "VIOLATION", "植物饮料", "肠胃炎调理", "轻松养胃"),
    _case("medical_false_01", "夸大功效", "VIOLATION", "颈椎按摩贴", "一次见效", "酸痛立刻消失"),
    _case("medical_false_02", "夸大功效", "VIOLATION", "睡眠喷雾", "100%有效", "整晚深睡"),
    _case("medical_false_03", "夸大功效", "VIOLATION", "草本膏", "包治反复疼痛", "家中常备"),
    _case("medical_false_04", "夸大功效", "VIOLATION", "足浴粉", "药到病除", "泡一泡就好"),
    _case("qualification_device_01", "类目资质", "VIOLATION", "家用理疗仪 普通家电类目", "缓解颈椎病", "无需处方 在家治疗"),
    _case("qualification_device_02", "类目资质", "VIOLATION", "普通按摩仪", "治疗腰椎间盘突出", "家用便携"),
    _case("qualification_bluehat_01", "类目资质", "VIOLATION", "普通食品压片糖果", "提高免疫力", "老人儿童都适合"),
    _case("qualification_bluehat_02", "类目资质", "VIOLATION", "普通饮品", "增强抵抗力", "蓝帽功效同款"),
    _case("qualification_cosmetic_01", "类目资质", "VIOLATION", "普通妆字号面膜", "美白祛斑", "7天透亮"),
    _case("qualification_cosmetic_02", "类目资质", "VIOLATION", "普通防护乳", "强效防晒", "户外必备"),
    _case("qualification_drug_01", "类目资质", "VIOLATION", "普通保健贴", "治疗关节炎", "老人适用"),
    _case("qualification_drug_02", "类目资质", "VIOLATION", "草本茶", "替代药物", "长期调理"),

    # —— 违规：跨模态组合 / 站外导流（16）——
    _case("cross_income_01", "跨模态组合", "VIOLATION", "加入我们，时间自由，轻松实现财富梦想", car_caption="财富自由"),
    _case("cross_income_02", "跨模态组合", "VIOLATION", "副业项目，多劳多得，时间灵活", car_caption="豪车生活"),
    _case("cross_income_03", "跨模态组合", "VIOLATION", "0经验也能做，收入上不封顶", "月入过万", "轻松翻身"),
    _case("cross_income_04", "跨模态组合", "VIOLATION", "宝妈副业，碎片时间也能做", "日入斗金", "私教带跑"),
    _case("cross_income_05", "跨模态组合", "VIOLATION", "在家兼职，适合新手", car_caption="提车计划"),
    _case("cross_income_06", "跨模态组合", "VIOLATION", "项目介绍，长期稳定", "稳赚不赔", "收益截图"),
    _case("cross_before_after_01", "跨模态组合", "VIOLATION", "普通牙膏 日常清洁", "3天变白", "对比图真实可见"),
    _case("cross_before_after_02", "跨模态组合", "VIOLATION", "普通护肤乳 日常保湿", "痘印消失", "前后对比"),
    _case("cross_before_after_03", "跨模态组合", "VIOLATION", "普通洗发水", "秃发逆转", "30天见证"),
    _case("cross_before_after_04", "跨模态组合", "VIOLATION", "普通眼霜", "皱纹清零", "真人对比"),
    _case("qr_diversion_01", "站外导流", "VIOLATION", "新品福利，详情见图片", "扫码加客服", "站外下单更优惠"),
    _case("qr_diversion_02", "站外导流", "VIOLATION", "限量款咨询", "加V领隐藏券", "平台外更便宜"),
    _case("qr_diversion_03", "站外导流", "VIOLATION", "团购福利", "私信发二维码", "老客专属"),
    _case("qr_diversion_04", "站外导流", "VIOLATION", "售后咨询", "关注公众号领取", "先到先得"),
    _case("qr_diversion_05", "站外导流", "VIOLATION", "同城自提", "扫码进群", "群内下单"),
    _case("qr_diversion_06", "站外导流", "VIOLATION", "课程资料", "添加助教", "站外领取"),

    # —— 合规：正常素材 / 易误杀负样本（20）——
    _case("clean_normal_01", "无（正常）", "PASS", "静音扫地机器人，大吸力，高性价比", "静音设计", "高性价比之选"),
    _case("clean_normal_02", "无（正常）", "PASS", "不锈钢保温杯", "耐用材质", "通勤便携"),
    _case("clean_normal_03", "无（正常）", "PASS", "补水保湿面霜", "清爽保湿", "适合日常护理"),
    _case("clean_normal_04", "无（正常）", "PASS", "早餐燕麦片", "膳食纤维", "饱腹方便"),
    _case("clean_normal_05", "无（正常）", "PASS", "汽车香薰，持久留香", "车载香氛", "清新不刺鼻"),
    _case("clean_normal_06", "无（正常）", "PASS", "家用收纳箱", "多规格可选", "整洁收纳"),
    _case("clean_normal_07", "无（正常）", "PASS", "电动牙刷", "柔和清洁", "多档模式"),
    _case("clean_normal_08", "无（正常）", "PASS", "家用咖啡机", "一键萃取", "办公室适用"),
    _case("clean_promo_01", "无（正常促销）", "PASS", "夏季新款连衣裙", "限时8折", "包邮发货"),
    _case("clean_promo_02", "无（正常促销）", "PASS", "儿童雨鞋", "第二件半价", "尺码齐全"),
    _case("clean_promo_03", "无（正常促销）", "PASS", "厨房纸巾", "组合装更划算", "家庭常备"),
    _case("clean_promo_04", "无（正常促销）", "PASS", "蓝牙音箱", "新品尝鲜价", "小巧便携"),
    _case("clean_borderline_01", "无（正常擦边词）", "PASS", "夏季新款连衣裙", "热销爆款", "限时8折 包邮"),
    _case("clean_borderline_02", "无（正常擦边词）", "PASS", "运动水杯", "人气单品", "轻量便携"),
    _case("clean_borderline_03", "无（正常擦边词）", "PASS", "桌面小风扇", "很多人都在买", "宿舍适用"),
    _case("clean_borderline_04", "无（正常擦边词）", "PASS", "无线鼠标", "高分好评", "办公顺手"),
    _case("clean_join_01", "无（正常招聘）", "PASS", "诚邀加入，按劳计酬，时间灵活", "岗位招募", "正规培训"),
    _case("clean_join_02", "无（正常招聘）", "PASS", "门店兼职，按小时计薪", "排班灵活", "线下面试"),
    _case("clean_health_01", "无（正常健康描述）", "PASS", "普通酸奶", "低糖配方", "早餐搭配"),
    _case("clean_health_02", "无（正常健康描述）", "PASS", "普通护手霜", "滋润保湿", "秋冬护理"),
]


def main():
    manifest = []
    for c in CASES:
        img_path = IMG_DIR / f"{c['id']}.png"
        if "car_caption" in c:
            _car_poster(img_path, c["car_caption"])
        else:
            _poster(img_path, c["title"], c.get("subtitle", ""))
        manifest.append({
            "id": c["id"],
            "scene": "ecommerce_ad",
            "evasion_type": c["evasion"],
            "expected_verdict": c["expected"],
            "material": {"text": c["text"], "image": str(img_path.relative_to(HERE))},
        })
    (HERE / "cases.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"生成 {len(manifest)} 个样本 → {IMG_DIR}")
    print(f"清单 → {HERE / 'cases.json'}")
    for m in manifest:
        print(f"  {m['id']:18} [{m['evasion_type']:8}] 预期={m['expected_verdict']}")


if __name__ == "__main__":
    main()
