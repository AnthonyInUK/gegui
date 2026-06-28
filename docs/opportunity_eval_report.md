# Opportunity Engine Eval Report

Seed: `neck massager`

## 1. Noise Filter

人工标注品牌词/意图词/真实赛道，评估 `_is_sellable_niche` 是否能把噪音挡在机会池外。

- Precision: **1.0**
- Recall: **1.0**
- F1: **1.0**
- Confusion: `{'tp': 5, 'fp': 0, 'tn': 5, 'fn': 0}`

## 2. Signal Coverage

统计每个赛道拿到几个有效信号，以及 live/cached/proxy/snapshot/unavailable 的来源分布。

- Full coverage count: **5**
- Avg usable signals: **4.0**
- Coverage histogram: `{'0': 0, '1': 0, '2': 0, '3': 0, '4': 5}`
- Provenance breakdown: `{'live': 0, 'cached': 5, 'snapshot': 5, 'proxy': 10, 'unavailable': 0}`

## 3. Signal Ablation

逐个移除信号源重排 top-3，观察是否存在单一信号独大或无贡献信号。

- Baseline top3: `['electric neck massager', 'neck and shoulder massager with heat', 'massager for neck']`

| Removed signal | Provider | Top1 changed | Displacement | New top3 |
|---|---|---:|---:|---|
| trend_momentum | google_trends | False | 2 | `['electric neck massager', 'neck and shoulder massager with heat', 'neck massager']` |
| absolute_demand | review_volume_proxy | False | 0 | `['electric neck massager', 'neck and shoulder massager with heat', 'massager for neck']` |
| differentiation | review_pain_density | False | 0 | `['electric neck massager', 'neck and shoulder massager with heat', 'massager for neck']` |
| surge | amazon_bestsellers_snapshot | False | 0 | `['electric neck massager', 'neck and shoulder massager with heat', 'massager for neck']` |

## 4. Degradation Triggers

降级率不是越高越好，它用于确认价格不足、合规风险等诚实机制确实会在真实赛道中触发。

- Evaluated niches: **5**
- Price degradation rate: **0.8**
- Compliance human-review rate: **1.0**
- Blocked rate: **0.0**
- Avg price coverage: **0.16**

## Resume Line

Built an eval harness for a no-ground-truth ecommerce opportunity engine: noise-filter F1, signal coverage, signal ablation, and honest degradation-rate checks.
