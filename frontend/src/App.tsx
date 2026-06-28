import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { api, type CompareResult, type CrossborderDemoReport, type ImprovementSpec, type ProfitInputs, type ProfitResult, type ReviewRecord, type ReviewRunResult, type ReviewUploadResult, type Stats, type SweepPoint } from './api'
import { AuroraBackground } from './components/ui/aurora-background'
import { Counter } from './components/ui/counter'
import { cn } from './lib/utils'

const VERDICT: Record<string, { ring: string; text: string; dot: string }> = {
  VIOLATION: { ring: 'ring-red-500/30 bg-red-500/10', text: 'text-red-300', dot: 'bg-red-400' },
  PASS: { ring: 'ring-emerald-500/30 bg-emerald-500/10', text: 'text-emerald-300', dot: 'bg-emerald-400' },
  NEEDS_HUMAN: { ring: 'ring-amber-500/30 bg-amber-500/10', text: 'text-amber-300', dot: 'bg-amber-400' },
}

const SCENE_NAME: Record<string, string> = {
  ecommerce_ad: '电商广告法',
  merchant_license: '证照核验',
}

const PIPELINE_STAGES = [
  ['data_intake', '公开数据接入'],
  ['product_research', '选品评分'],
  ['listing_generation', 'Listing 生成'],
  ['compliance_check', '合规审核'],
  ['ads_diagnostic', '广告诊断'],
  ['customer_service', '客服处理'],
  ['gate_summary', 'Action Gate'],
]

const STAGE_TO_DETAIL: Record<string, string> = {
  data_intake: 'intake',
  product_research: 'research',
  listing_generation: 'listing',
  compliance_check: 'compliance',
  ads_diagnostic: 'ops',
  customer_service: 'ops',
  gate_summary: 'gate',
}

const STEP_INFO: Record<string, { title: string; what: string; why: string; input: string; process: string; output: string }> = {
  product: {
    title: '商品与痛点',
    what: '确认本次 pipeline 最终进入分析的候选商品，并把公开评论里的负面反馈抽成可用痛点。',
    why: 'Listing 卖点、产品改良和广告诊断都不能凭空生成，必须从商品资料、竞品和真实评论里找依据。',
    input: '候选商品 metadata、source_parent_asin、类目路径、features、claims、image_urls、低分评论。',
    process: '按关键词命中商品后，聚合 parent_asin 下的 3 星及以下评论，用痛点词表识别 adhesive、too bulky、size mismatch 等主题。',
    output: '商品双语信息、评论痛点主题、出现次数、严重度、原始评论例句、来源 ASIN。',
  },
  intake: {
    title: '公开数据接入',
    what: '把公开 Amazon Reviews 2023 风格的 meta/review JSONL 转成统一的 ProductResearchRequest。',
    why: '外部数据格式不稳定，后面的选品、Listing 和合规工具不能直接吃原始 JSONL，需要先标准化。',
    input: 'meta_sample.jsonl、review_sample.jsonl、关键词 cable organizer、目标类目 Office Products。',
    process: '匹配商品标题/类目/描述，按 parent_asin 聚合评论，补齐目标价格、预估月销、FBA/广告/退货成本字段。',
    output: '候选商品、竞品快照、评论痛点、成本模型、物流档案、合规预检和 data_intake_report。',
  },
  research: {
    title: '选品评分',
    what: '判断这个候选品是否值得继续进入 Listing 和合规流程。',
    why: '选品不能只靠规则，也不能只靠主观判断，需要把需求、利润、竞争、物流、合规拆开打分。',
    input: '标准化后的商品、竞品、评论痛点、成本模型、物流字段、合规预检。',
    process: '用确定性评分规则计算 demand/profitability/competition/logistics/compliance 五项分数，再合成机会分。',
    output: 'pass / needs_human_review / blocked、机会等级、五项分数、建议和 audit.research_id。',
  },
  listing: {
    title: 'Listing 生成',
    what: '把商品特征和评论痛点转成 Amazon Listing 初稿。',
    why: '跨境电商的 Listing 要同时满足平台结构、关键词覆盖、本地化表达和合规措辞。',
    input: '商品 title/brand/features/claims、keyword_hints、Amazon US 平台策略。',
    process: '用稳定模板生成 title、bullets、description、search_terms，并软化高风险词。',
    output: 'Amazon 标题、五点描述、描述文案、搜索词和 audit.listing_id。',
  },
  compliance: {
    title: '合规审核',
    what: '把 Listing 作为结构化输入调用合规 Agent-as-Tool，判断是否可发布或需要修改/人审。',
    why: '跨境 Agent 不应该自己判断广告法/平台政策，而应该通过稳定 contract 调合规工具。',
    input: 'platform、market、product、content.title、description、ad_copy、image_urls、documents。',
    process: '执行规则/平台预检/合规工具判断，真实环境会返回 issues、evidence、suggested_rewrite、check_id。',
    output: 'decision、risk_level、human_review_required、evidence、audit.check_id。',
  },
  ops: {
    title: '运营与客服',
    what: '诊断广告指标和买家消息，生成建议动作，但不直接执行高风险动作。',
    why: 'ACOS/CVR 等计算是确定性的，是否调预算/暂停广告/退款则需要风险判断和权限控制。',
    input: '广告 campaign metrics、客服消息、订单/商品上下文、seller 权限。',
    process: '广告侧计算 ACOS/CVR/CPC/CPA 并识别低转化/高 ACOS；客服侧识别退款、负面情绪和紧急程度。',
    output: '广告问题、客服回复草稿、suggested_actions，以及进入 Action Gate 的动作。',
  },
  gate: {
    title: 'Action Gate',
    what: '拦截所有会影响广告、客服、退款、发布的高风险动作。',
    why: 'Agent 可以分析和建议，但不能绕过权限自动暂停广告、退款或承诺赔偿。',
    input: 'suggested_action、risk_level、caller permissions、workflow metadata。',
    process: '按动作类型检查所需权限和风险等级；缺权限或高风险时转人工审核。',
    output: 'allowed / requires_human_review / blocked、拦截原因、gate_id。',
  },
}

const DECISION_STYLE: Record<string, { ring: string; text: string; dot: string }> = {
  pass: { ring: 'ring-emerald-500/30 bg-emerald-500/10', text: 'text-emerald-300', dot: 'bg-emerald-400' },
  ready_to_publish: { ring: 'ring-emerald-500/30 bg-emerald-500/10', text: 'text-emerald-300', dot: 'bg-emerald-400' },
  needs_revision: { ring: 'ring-amber-500/30 bg-amber-500/10', text: 'text-amber-300', dot: 'bg-amber-400' },
  requires_revision: { ring: 'ring-amber-500/30 bg-amber-500/10', text: 'text-amber-300', dot: 'bg-amber-400' },
  requires_human_review: { ring: 'ring-amber-500/30 bg-amber-500/10', text: 'text-amber-300', dot: 'bg-amber-400' },
  needs_human_review: { ring: 'ring-amber-500/30 bg-amber-500/10', text: 'text-amber-300', dot: 'bg-amber-400' },
  compliance_runtime_unavailable: { ring: 'ring-slate-500/30 bg-slate-500/10', text: 'text-slate-300', dot: 'bg-slate-400' },
  no_niche: { ring: 'ring-slate-500/30 bg-slate-500/10', text: 'text-slate-300', dot: 'bg-slate-400' },
  blocked: { ring: 'ring-red-500/30 bg-red-500/10', text: 'text-red-300', dot: 'bg-red-400' },
  high: { ring: 'ring-red-500/30 bg-red-500/10', text: 'text-red-300', dot: 'bg-red-400' },
}

const DECISION_LABEL: Record<string, string> = {
  pass: '通过',
  ready_to_publish: '可生成发布包',
  needs_revision: '需要修改',
  requires_revision: '需要修改',
  requires_human_review: '需要人工审核',
  needs_human_review: '需要人工审核',
  compliance_runtime_unavailable: '合规运行时不可用',
  no_niche: '未发现赛道',
  blocked: '阻断',
  high: '高风险',
  low: '低风险',
  true: '是',
  false: '否',
}

const FIELD_LABEL: Record<string, string> = {
  demand: '需求',
  profitability: '利润',
  competition: '竞争',
  logistics: '物流',
  compliance: '合规',
  low_cvr: '转化率偏低',
  high_acos: 'ACOS 偏高',
  listing_conversion: 'Listing 转化',
  budget_control: '预算控制',
  refund_request: '退款请求',
  negative: '负面',
  add_negative_keyword: '添加否定关键词',
  pause_campaign: '暂停广告活动',
  send_reply: '发送客服回复',
  refund_order: '退款操作',
  requires_human_review: '需要人工审核',
  selected: '最终主推',
  candidate: '候选/竞品',
  landed: '到岸',
  referral: '佣金',
  fba: 'FBA',
  ads: '广告',
  returns: '退货',
  storage: '仓储',
  other: '其他',
}

const TEXT_CN: Record<string, string> = {
  'Validate differentiation against top ASINs before purchasing inventory.': '进货前需要对比头部 ASIN，确认是否有明确差异化。',
  'Turn high-frequency review pain points into product requirements and listing bullets.': '把高频差评痛点转成产品需求和 Listing 卖点。',
  'Listing draft is ready for platform rules and compliance review.': 'Listing 初稿已生成，可以进入平台规则和合规审核。',
  'CVR is low after enough clicks to judge conversion.': '点击量已经足够判断，但转化率偏低。',
  'ACOS is materially above target.': '广告花费销售比明显高于目标。',
  'Tighten keywords and improve listing page conversion before scaling spend.': '先收紧关键词并优化详情页转化，再扩大投放。',
  'Reduce bids on inefficient terms and separate winners from exploration campaigns.': '降低低效词出价，把有效词和探索词分开管理。',
  'Non-converting search terms should be reviewed for negative targeting.': '没有转化的搜索词需要审核是否加入否定词。',
  'Campaign has inefficient or wasteful spend signals.': '广告活动出现低效或浪费预算信号。',
  'Review listing quality, reviews, offer, delivery promise, and keyword intent; avoid scaling traffic until conversion improves.': '先检查 Listing 质量、评价、报价、配送承诺和关键词意图，转化改善前不要放量。',
  'Lower bids or pause inefficient ad groups, but route budget changes through Action Gate.': '可以降低出价或暂停低效广告组，但预算类动作必须经过 Action Gate。',
  'Message indicates refund, complaint, negative sentiment, or product failure risk.': '买家消息包含退款、投诉、负面情绪或产品故障风险。',
  'Use draft reply only; route monetary or delivery commitments through Action Gate.': '只能生成回复草稿，退款/赔偿/交期承诺必须走 Action Gate。',
  'Send or queue the drafted customer service response.': '发送或排队客服回复草稿。',
  'Buyer explicitly requested a refund.': '买家明确提出退款。',
  'Risk level is high; route to human review.': '风险等级高，需要人工审核。',
  'Missing required permissions: ads_manage.': '缺少广告管理权限。',
  'Missing required permissions: refund.': '缺少退款权限。',
  'High-risk marketplace/customer action requires human approval.': '高风险平台/客服动作必须人工批准。',
}

const PHRASE_CN: Record<string, string> = {
  'Reusable Silicone Cable Organizer Clips for Desk': '桌面可重复使用硅胶理线夹',
  'Compact cable clips': '小巧线缆夹',
  'Reusable silicone': '可重复使用硅胶',
  'Easy setup': '安装简单',
  'Keeps desk cables tidy for home office use.': '用于家庭办公场景，让桌面线缆更整洁。',
  'Cable Organizer': '理线器',
  'Office Products': '办公用品',
  'Office Electronics Accessories': '办公电子配件',
  adhesive: '粘性不足',
  'too bulky': '体积偏大',
  'size mismatch': '尺寸不匹配',
  durability: '耐用性问题',
  installation: '安装问题',
  odor: '异味',
  noise: '噪音',
  battery: '电池/续航',
  'Low Profile Cord Holder for Home Office': '低矮型家庭办公室线缆固定器',
}

function cnText(value?: string | number | boolean | null): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  return TEXT_CN[text] || PHRASE_CN[text] || FIELD_LABEL[text] || DECISION_LABEL[text] || text
}

function money(value?: number | null): string {
  return typeof value === 'number' ? `$${value.toFixed(2)}` : '—'
}

function pct(value?: number | null): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—'
}

function selectedCandidateReason(input: Record<string, any>, research: Record<string, any>): Array<Record<string, string>> {
  const competitors = input.competitors || []
  const selected = competitors[0] || {}
  const runnerUp = competitors[1] || {}
  const margin =
    typeof input.target_price === 'number' && typeof input.landed_cost === 'number'
      ? (input.target_price - input.landed_cost) / input.target_price
      : null
  return [
    {
      claim: `候选池共有 ${competitors.length} 条；当前主推 ${selected.asin || '—'}。`,
      evidence: `主推评论 ${selected.review_count ?? '—'}、预估月销 ${selected.estimated_monthly_sales ?? '—'}；对照评论 ${runnerUp.review_count ?? '—'}、预估月销 ${runnerUp.estimated_monthly_sales ?? '—'}。`,
      source: 'competitors[].review_count / competitors[].estimated_monthly_sales',
    },
    {
      claim: `利润项得分 ${research.score_breakdown?.profitability ?? '—'}，粗算毛利空间 ${pct(margin)}。`,
      evidence: `目标售价 ${money(input.target_price)}，预估全成本 ${money(input.landed_cost)}。`,
      source: 'target_price / landed_cost',
    },
    {
      claim: '评论痛点用于识别改良方向。',
      evidence: '痛点来自低星评论关键词匹配；只能说明样本内反馈，不代表完整市场结论。',
      source: 'pain_points[].example / pain_points[].source_asins',
    },
  ]
}

function EvidenceList({ items }: { items: Array<any> }) {
  return (
    <div className="space-y-2">
      {items.map((item, i) => {
        const claim = typeof item === 'string' ? item : item.claim
        const evidence = typeof item === 'string' ? '' : item.evidence
        const source = typeof item === 'string' ? '' : item.source
        return (
          <div key={`${claim}-${i}`} className="rounded-lg bg-black/25 px-3 py-2 text-sm leading-relaxed text-slate-200">
            <div className="flex gap-3">
              <span className="font-mono text-xs text-slate-500">{String(i + 1).padStart(2, '0')}</span>
              <span className="font-semibold text-slate-100">{claim}</span>
            </div>
            {evidence && <div className="mt-1 pl-8 text-xs text-slate-300">证据：{evidence}</div>}
            {source && <div className="mt-1 pl-8 font-mono text-[11px] text-slate-500">来源：{source}</div>}
          </div>
        )
      })}
    </div>
  )
}

function Bilingual({ value, className = '' }: { value?: string; className?: string }) {
  if (!value) return <span className={className}>—</span>
  const zh = cnText(value)
  return (
    <span className={className}>
      <span>{value}</span>
      {zh !== value && <span className="ml-2 text-slate-400">（{zh}）</span>}
    </span>
  )
}

function fmtTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function Badge({ v }: { v: string }) {
  const s = VERDICT[v] ?? VERDICT.PASS
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ring-1', s.ring, s.text)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
      {v}
    </span>
  )
}

function DecisionBadge({ v }: { v?: string | boolean }) {
  const label = String(v ?? 'unknown')
  const s = DECISION_STYLE[label] ?? DECISION_STYLE.requires_revision
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1', s.ring, s.text)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
      {cnText(label)}
    </span>
  )
}

function PriorityBadge({ v }: { v?: string }) {
  const key = v || 'low'
  const cls =
    key === 'high'
      ? 'bg-red-500/10 text-red-200 ring-red-500/25'
      : key === 'medium'
        ? 'bg-amber-500/10 text-amber-200 ring-amber-500/25'
        : 'bg-white/5 text-slate-300 ring-white/10'
  const label = key === 'high' ? '高优先级' : key === 'medium' ? '中优先级' : '低优先级'
  return <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1', cls)}>{label}</span>
}

function ImprovementPanel({ spec }: { spec?: ImprovementSpec }) {
  const requirements = spec?.requirements || []
  return (
    <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.035] p-5 backdrop-blur-xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-emerald-200">⑤ 改良需求书</div>
          <h3 className="mt-1 text-sm font-semibold text-slate-100">评论痛点 → 可执行改良 + 差异化卖点</h3>
        </div>
        <span className="rounded-full bg-black/25 px-2.5 py-1 text-xs text-slate-300 ring-1 ring-white/10">
          {requirements.length} 项需求
        </span>
      </div>

      {requirements.length === 0 ? (
        <div className="mt-4 rounded-xl bg-black/25 p-4 text-sm text-slate-400">无评论痛点，暂无改良建议。</div>
      ) : (
        <div className="mt-4 space-y-3">
          {requirements.map((req, i) => (
            <div key={`${req.pain_topic}-${i}`} className="rounded-xl border border-white/10 bg-black/25 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <PriorityBadge v={req.priority} />
                <span className="font-semibold text-white">
                  {req.pain_topic} <span className="text-slate-400">（{cnText(req.pain_topic)}）</span>
                </span>
                <span className="text-xs text-slate-500">频次 {req.frequency} · 严重度 {req.severity}</span>
              </div>
              <div className="mt-2 text-sm leading-relaxed text-slate-200">{req.requirement}</div>
              {req.evidence_quote && (
                <div className="mt-2 rounded-lg bg-black/25 px-3 py-2 text-xs italic leading-relaxed text-slate-300">
                  “{req.evidence_quote}”
                </div>
              )}
              {req.source_asins.length > 0 && (
                <div className="mt-2 font-mono text-[11px] text-slate-500">来源 ASIN：{req.source_asins.join(', ')}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {(spec?.differentiation_bullets || []).length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-emerald-200">候选差异化卖点</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {spec!.differentiation_bullets.map((bullet) => (
              <span key={bullet} className="rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-100 ring-1 ring-emerald-500/20">
                {bullet}
              </span>
            ))}
          </div>
        </div>
      )}

      {(spec?.emphasis_keywords || []).length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">强调关键词</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {spec!.emphasis_keywords.map((kw) => (
              <span key={kw} className="rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-slate-300 ring-1 ring-white/10">{kw}</span>
            ))}
          </div>
        </div>
      )}

      {spec?.honesty_note && <div className="mt-4 text-[11px] leading-relaxed text-slate-500">{spec.honesty_note}</div>}
    </div>
  )
}

function CompareScorecard({ result }: { result: CompareResult }) {
  const dims = result.comparison.dimensions || []
  const ordered = [...result.niches].sort((a, b) => {
    if (a.keyword === result.comparison.winner) return -1
    if (b.keyword === result.comparison.winner) return 1
    return 0
  })
  return (
    <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/[0.035] p-5 backdrop-blur-xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">多赛道横评 Scorecard</div>
          <h3 className="mt-1 text-base font-bold text-white">五维并排比较</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">赢家</span>
          <span className="rounded-full bg-amber-500/10 px-3 py-1 text-xs font-bold text-amber-100 ring-1 ring-amber-500/30">
            {result.comparison.winner || '暂无'}
          </span>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 rounded-l-xl bg-black/40 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">维度</th>
              {ordered.map((niche, i) => (
                <th key={niche.keyword} className={cn('bg-black/35 px-3 py-2 text-left align-top', i === ordered.length - 1 && 'rounded-r-xl')}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn('font-semibold', niche.error ? 'text-slate-500' : 'text-white')}>{niche.keyword}</span>
                    {niche.keyword === result.comparison.winner && (
                      <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-100 ring-1 ring-amber-500/25">winner</span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                    <span>竞品 {niche.competitors ?? 0}</span>
                    <span>价格覆盖 {pct(niche.price_coverage)}</span>
                  </div>
                  {niche.error && <div className="mt-1 text-[11px] text-red-300">无足够竞品</div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dims.map((dim) => (
              <tr key={dim}>
                <td className="sticky left-0 z-10 border-t border-white/10 bg-slate-950/95 px-3 py-3 font-semibold text-slate-300">{cnText(dim)}</td>
                {ordered.map((niche) => {
                  const best = result.comparison.best_per_dim?.[dim] === niche.keyword
                  const score = niche.score_breakdown?.[dim]
                  return (
                    <td key={`${niche.keyword}-${dim}`} className={cn('border-t border-white/10 px-3 py-3 font-bold', niche.error ? 'text-slate-600' : best ? 'bg-emerald-500/10 text-emerald-100' : 'text-slate-200')}>
                      {score ?? '—'}
                    </td>
                  )
                })}
              </tr>
            ))}
            <tr>
              <td className="sticky left-0 z-10 border-t border-white/10 bg-slate-950/95 px-3 py-3 font-semibold text-slate-300">总分</td>
              {ordered.map((niche) => (
                <td key={`${niche.keyword}-score`} className={cn('border-t border-white/10 px-3 py-3 text-lg font-black', niche.error ? 'text-slate-600' : niche.keyword === result.comparison.winner ? 'text-amber-100' : 'text-white')}>
                  {niche.score ?? '—'}
                </td>
              ))}
            </tr>
            <tr>
              <td className="sticky left-0 z-10 border-t border-white/10 bg-slate-950/95 px-3 py-3 font-semibold text-slate-300">决策</td>
              {ordered.map((niche) => (
                <td key={`${niche.keyword}-decision`} className="border-t border-white/10 px-3 py-3">
                  {niche.error ? <span className="text-xs text-slate-500">无数据</span> : <DecisionBadge v={niche.decision || 'requires_human_review'} />}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {result.comparison.notes.length > 0 && (
        <div className="mt-4 space-y-2">
          {result.comparison.notes.map((note) => (
            <div key={note} className="rounded-lg bg-amber-500/[0.08] px-3 py-2 text-xs text-amber-100 ring-1 ring-amber-500/20">{note}</div>
          ))}
        </div>
      )}
    </div>
  )
}

function ProfitVerdictBadge({ v }: { v?: string }) {
  const cls =
    v === 'healthy'
      ? 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/25'
      : v === 'thin'
        ? 'bg-amber-500/10 text-amber-200 ring-amber-500/25'
        : v === 'loss'
          ? 'bg-red-500/10 text-red-200 ring-red-500/25'
          : 'bg-white/5 text-slate-300 ring-white/10'
  const label = v === 'healthy' ? '健康' : v === 'thin' ? '偏薄' : v === 'loss' ? '亏损' : v === 'marginal' ? '临界' : '一般'
  return <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1', cls)}>{label}</span>
}

function ProfitSlider({
  label,
  value,
  min,
  max,
  step,
  suffix = '',
  format,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  suffix?: string
  format?: (value: number) => string
  onChange: (value: number) => void
}) {
  return (
    <label className="block rounded-xl bg-black/25 p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold text-slate-300">{label}</span>
        <span className="font-mono text-xs text-white">{format ? format(value) : `${value.toFixed(2)}${suffix}`}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-3 w-full accent-cyan-400"
      />
    </label>
  )
}

function ProfitCurve({ data }: { data: SweepPoint[] }) {
  if (!data.length) {
    return <div className="rounded-xl bg-black/25 p-4 text-sm text-slate-400">暂无扫描曲线。</div>
  }
  const width = 320
  const height = 120
  const pad = 14
  const xs = data.map((d) => d.x)
  const ys = data.map((d) => d.net_margin)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys, 0)
  const maxY = Math.max(...ys, 0.01)
  const xPos = (x: number) => pad + ((x - minX) / Math.max(maxX - minX, 1)) * (width - pad * 2)
  const yPos = (y: number) => height - pad - ((y - minY) / Math.max(maxY - minY, 0.01)) * (height - pad * 2)
  const points = data.map((d) => `${xPos(d.x).toFixed(1)},${yPos(d.net_margin).toFixed(1)}`).join(' ')
  const zeroY = yPos(0)
  const breakeven = findBreakevenPoint(data)
  return (
    <div className="rounded-xl border border-white/10 bg-black/25 p-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-36 w-full" role="img" aria-label="净利率扫描曲线">
        <line x1={pad} x2={width - pad} y1={zeroY} y2={zeroY} stroke="rgba(148,163,184,0.45)" strokeDasharray="4 4" />
        <polyline points={points} fill="none" stroke="rgb(34,211,238)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {data.map((d) => (
          <circle key={`${d.x}-${d.net_margin}`} cx={xPos(d.x)} cy={yPos(d.net_margin)} r="2.2" fill={d.net_margin < 0 ? 'rgb(248,113,113)' : 'rgb(52,211,153)'} />
        ))}
        {breakeven && (
          <circle cx={xPos(breakeven.x)} cy={yPos(0)} r="5" fill="rgb(251,191,36)" stroke="rgba(15,23,42,0.9)" strokeWidth="2" />
        )}
      </svg>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
        <span>{data[0].variable}：{data[0].x.toFixed(2)} → {data[data.length - 1].x.toFixed(2)}</span>
        <span>{breakeven ? `净利率穿 0 约在 ${breakeven.x.toFixed(2)}` : '当前扫描范围未穿 0'}</span>
      </div>
    </div>
  )
}

function findBreakevenPoint(data: SweepPoint[]): { x: number } | null {
  for (let i = 1; i < data.length; i += 1) {
    const prev = data[i - 1]
    const curr = data[i]
    if (prev.net_margin === 0) return { x: prev.x }
    if ((prev.net_margin < 0 && curr.net_margin >= 0) || (prev.net_margin > 0 && curr.net_margin <= 0)) {
      const span = curr.net_margin - prev.net_margin
      const ratio = span === 0 ? 0 : (0 - prev.net_margin) / span
      return { x: prev.x + (curr.x - prev.x) * ratio }
    }
  }
  return null
}

function sweepRange(inputs: ProfitInputs, variable: 'sale_price' | 'unit_cost' | 'ads_acos' | 'return_rate'): [number, number] {
  if (variable === 'ads_acos') return [0, 0.6]
  if (variable === 'return_rate') return [0, 0.2]
  if (variable === 'unit_cost') return [1, Math.max(2, inputs.sale_price)]
  const floor = Math.max(10, inputs.unit_cost * 1.5)
  return [floor, Math.max(floor + 10, inputs.sale_price * 1.6)]
}

function ProfitSimulatorPanel({
  inputs,
  profit,
  sweepVar,
  sweepData,
  onInputsChange,
  onSweepVarChange,
}: {
  inputs: ProfitInputs
  profit: ProfitResult | null
  sweepVar: 'sale_price' | 'unit_cost' | 'ads_acos' | 'return_rate'
  sweepData: SweepPoint[]
  onInputsChange: (next: ProfitInputs) => void
  onSweepVarChange: (next: 'sale_price' | 'unit_cost' | 'ads_acos' | 'return_rate') => void
}) {
  const set = (key: keyof ProfitInputs, value: number) => onInputsChange({ ...inputs, [key]: value })
  const breakdown = profit?.breakdown || {}
  const maxCost = Math.max(...Object.values(breakdown), 1)
  return (
    <div className="rounded-2xl border border-sky-500/20 bg-sky-500/[0.035] p-5 backdrop-blur-xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-sky-200">⑥ 利润模拟器 · what-if</div>
          <h3 className="mt-1 text-sm font-semibold text-slate-100">拖动价格、成本、ACOS 和退货率，看单件净利</h3>
        </div>
        {profit && <ProfitVerdictBadge v={profit.verdict} />}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <ProfitSlider label="售价 Sale Price" value={inputs.sale_price} min={10} max={150} step={1} format={money} onChange={(v) => set('sale_price', v)} />
        <ProfitSlider label="采购成本 Unit Cost" value={inputs.unit_cost} min={1} max={80} step={0.5} format={money} onChange={(v) => set('unit_cost', v)} />
        <ProfitSlider label="FBA 履约费" value={inputs.fba_fee || 0} min={0} max={20} step={0.25} format={money} onChange={(v) => set('fba_fee', v)} />
        <ProfitSlider label="ACOS 广告占比" value={inputs.ads_acos || 0} min={0} max={0.6} step={0.01} format={(v) => `${(v * 100).toFixed(0)}%`} onChange={(v) => set('ads_acos', v)} />
        <ProfitSlider label="退货率 Return Rate" value={inputs.return_rate || 0} min={0} max={0.2} step={0.005} format={(v) => `${(v * 100).toFixed(1)}%`} onChange={(v) => set('return_rate', v)} />
        <ProfitSlider label="头程分摊 Inbound" value={inputs.inbound_shipping_per_unit || 0} min={0} max={20} step={0.25} format={money} onChange={(v) => set('inbound_shipping_per_unit', v)} />
      </div>

      {profit && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className={cn('rounded-xl p-3 ring-1', profit.net_profit < 0 ? 'bg-red-500/10 text-red-100 ring-red-500/25' : 'bg-emerald-500/10 text-emerald-100 ring-emerald-500/25')}>
              <div className="text-xs text-slate-300">单件净利</div>
              <div className="mt-1 text-3xl font-black">{money(profit.net_profit)}</div>
            </div>
            <MetricBox label="净利率" value={pct(profit.net_margin)} />
            <MetricBox label="保本价" value={profit.breakeven_price === null ? '无解' : money(profit.breakeven_price)} />
            <MetricBox label="保本 ACOS" value={profit.breakeven_acos === null ? '无解' : pct(profit.breakeven_acos)} />
            <MetricBox label="ROI" value={profit.roi === null ? '—' : pct(profit.roi)} />
            <MetricBox label="到岸成本" value={money(profit.landed_cost)} />
            <MetricBox label="佣金" value={money(profit.breakdown.referral)} />
            <MetricBox label="广告费" value={money(profit.breakdown.ads)} />
          </div>

          <div className="mt-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">费用瀑布 Breakdown</div>
            <div className="mt-2 space-y-2">
              {Object.entries(profit.breakdown).map(([key, value]) => (
                <div key={key} className="grid grid-cols-[76px_1fr_72px] items-center gap-2 text-xs">
                  <span className="text-slate-400">{cnText(key)}</span>
                  <div className="h-2 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full bg-sky-300/70" style={{ width: `${Math.max(4, (value / maxCost) * 100)}%` }} />
                  </div>
                  <span className="text-right font-mono text-slate-200">{money(value)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">扫描曲线 Sweep</div>
              <select
                value={sweepVar}
                onChange={(e) => onSweepVarChange(e.target.value as 'sale_price' | 'unit_cost' | 'ads_acos' | 'return_rate')}
                className="rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-xs text-white outline-none focus:border-sky-400/50"
              >
                <option value="sale_price">售价</option>
                <option value="unit_cost">采购成本</option>
                <option value="ads_acos">ACOS</option>
                <option value="return_rate">退货率</option>
              </select>
            </div>
            <div className="mt-2"><ProfitCurve data={sweepData} /></div>
          </div>

          <div className="mt-4 text-[11px] leading-relaxed text-slate-500">{profit.note}</div>
        </>
      )}
    </div>
  )
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-black/25 p-3 ring-1 ring-white/10">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 text-lg font-bold text-white">{value}</div>
    </div>
  )
}

function NavButton({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-full px-3.5 py-2 text-sm font-semibold transition ring-1',
        active
          ? 'bg-white text-slate-950 ring-white'
          : 'bg-white/[0.04] text-slate-200 ring-white/10 hover:bg-white/[0.08]',
      )}
    >
      {children}
    </button>
  )
}

function RecordThumbs({ record }: { record: ReviewRecord }) {
  const count = record.image_paths.length
  if (!count) {
    return (
      <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-[11px] font-medium text-slate-500">
        无图
      </div>
    )
  }

  return (
    <div className="flex h-14 w-16 shrink-0 items-center">
      {record.image_paths.slice(0, 3).map((_, i) => (
        <div
          key={i}
          className={cn(
            'relative h-14 w-14 overflow-hidden rounded-lg border border-white/10 bg-slate-950 shadow-lg shadow-black/20',
            i > 0 && '-ml-10',
          )}
          style={{ zIndex: 10 - i }}
        >
          <img
            src={`/api/records/${record.id}/image?idx=${i}`}
            alt={`素材图 ${i + 1}`}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
          />
          {i === 2 && count > 3 && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/55 text-xs font-semibold text-white">
              +{count - 3}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function StatCard({ n, label, accent, i }: { n: number; label: string; accent: string; i: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: i * 0.06 }}
      className="group relative flex-1 min-w-[150px] overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl transition-colors hover:border-white/20"
    >
      <div className={cn('absolute -right-6 -top-6 h-20 w-20 rounded-full opacity-20 blur-2xl transition-opacity group-hover:opacity-40', accent)} />
      <div className="relative text-[34px] font-bold leading-none tabular-nums text-white">
        <Counter value={n} />
      </div>
      <div className="relative mt-2 text-xs uppercase tracking-wider text-slate-300 font-medium">{label}</div>
    </motion.div>
  )
}

function stageDecision(report: CrossborderDemoReport, key: string): string {
  if (key === 'gate_summary') {
    const counts = report.gate_summary.decision_counts || {}
    return counts.blocked ? 'blocked' : counts.requires_human_review ? 'requires_human_review' : 'pass'
  }
  const stage = report.stages[key] || {}
  return stage.decision || stage.status || stage.risk_level || 'pass'
}

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg bg-black/20 px-3 py-2 text-sm">
      <span className="shrink-0 text-slate-400">{label}</span>
      <span className="text-right text-slate-100">{value}</span>
    </div>
  )
}

function StageExplorer({
  report,
  initialActive,
  onBack,
}: {
  report: CrossborderDemoReport
  initialActive: string
  onBack: () => void
}) {
  const [active, setActive] = useState(initialActive)
  const input = report.input_summary || {}
  const product = input.selected_product || {}
  const dataReport = report.stages?.data_intake?.report || {}
  const research = report.stages?.product_research || {}
  const listing = report.stages?.listing_generation?.listing || {}
  const compliance = report.stages?.compliance_check || {}
  const ads = report.stages?.ads_diagnostic || {}
  const customer = report.stages?.customer_service || {}
  const competitors = input.competitors || []
  const painPoints = input.pain_points || []
  const sourceCategories = product.attributes?.source_categories || []

  const tabs = [
    ['product', '商品与痛点', '选了什么，评论到底说了什么'],
    ['intake', '数据接入', '候选池、命中和字段补齐'],
    ['research', '选品判断', '分数、竞品和选择依据'],
    ['listing', 'Listing 生成', '标题、五点、关键词双语'],
    ['compliance', '合规审核', '证据、风险和运行模式'],
    ['ops', '运营与客服', '广告/客服诊断依据'],
    ['gate', 'Action Gate', '哪些动作被拦，为什么'],
  ]
  const info = STEP_INFO[active] || STEP_INFO.product

  useEffect(() => {
    setActive(initialActive)
  }, [initialActive])

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            onClick={onBack}
            className="rounded-full bg-white/[0.06] px-3 py-1.5 text-sm font-semibold text-slate-200 ring-1 ring-white/10 transition hover:bg-white/[0.1]"
          >
            返回总览
          </button>
          <div>
            <div className="text-right text-xs font-semibold uppercase tracking-wider text-cyan-200">Step Detail</div>
            <h2 className="text-right text-xl font-bold text-white">{info.title}</h2>
          </div>
          <DecisionBadge
            v={
              active === 'product'
                ? 'pass'
                : active === 'gate'
                  ? stageDecision(report, 'gate_summary')
                  : active === 'ops'
                    ? stageDecision(report, 'ads_diagnostic')
                    : stageDecision(report, Object.entries(STAGE_TO_DETAIL).find(([, v]) => v === active)?.[0] || 'data_intake')
            }
          />
        </div>
        <div className="mt-4 overflow-x-auto pb-1">
          <div className="flex min-w-max gap-2">
            {tabs.map(([key, label], i) => (
              <button
                key={key}
                onClick={() => setActive(key)}
                className={cn(
                  'rounded-full px-3.5 py-2 text-sm font-semibold transition ring-1',
                  active === key
                    ? 'bg-cyan-500/15 text-cyan-100 ring-cyan-400/35'
                    : 'bg-black/20 text-slate-300 ring-white/10 hover:bg-white/[0.06]',
                )}
              >
                <span className="mr-2 font-mono text-xs text-slate-500">{String(i + 1).padStart(2, '0')}</span>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-5 backdrop-blur-xl">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
          <InfoRow label="做什么" value={info.what} />
          <InfoRow label="为什么做" value={info.why} />
          <InfoRow label="输入" value={info.input} />
          <InfoRow label="处理逻辑" value={info.process} />
          <InfoRow label="输出" value={info.output} />
        </div>

        <div className="mt-6 border-t border-white/10 pt-5">
        {active === 'product' && (
          <div className="space-y-5">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">商品信息 Product Info</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <InfoRow label="英文品名" value={<Bilingual value={product.title} />} />
                <InfoRow label="品牌 / ASIN" value={`${product.brand || '—'} / ${product.attributes?.source_parent_asin || '—'}`} />
                <InfoRow label="原始类目" value={<span>{sourceCategories.map((c: string) => `${c}（${cnText(c)}）`).join(' > ')}</span>} />
                <InfoRow label="图片 URL" value={<span className="break-all">{(product.image_urls || [])[0] || '—'}</span>} />
              </div>
              <div className="mt-3 rounded-xl bg-black/30 p-3">
                <div className="text-xs text-slate-400">商品特征 Features</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(product.features || []).map((item: string) => (
                    <span key={item} className="rounded-full bg-white/5 px-2.5 py-1 text-xs text-slate-200 ring-1 ring-white/10">
                      <Bilingual value={item} />
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-amber-200">评论痛点 Review Pain Points</div>
              <div className="mt-3 space-y-3">
                {painPoints.map((point: any) => (
                  <div key={point.topic} className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-lg font-bold text-amber-100">
                        {point.topic} <span className="text-slate-300">（{cnText(point.topic)}）</span>
                      </div>
                      <div className="text-sm text-slate-300">
                        出现 {point.frequency} 次 · 严重度 {point.severity}/5
                      </div>
                    </div>
                    <div className="mt-3 rounded-lg bg-black/30 px-3 py-2 text-sm leading-relaxed text-slate-100">
                      原始评论：<span className="text-white">"{point.example}"</span>
                    </div>
                    <div className="mt-2 text-xs text-slate-400">
                      来源 ASIN：{(point.source_asins || []).join('、') || '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {active === 'intake' && (
          <div className="space-y-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">数据接入明细 Data Intake</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <InfoRow label="公开数据格式" value="Amazon Reviews 2023 JSONL" />
              <InfoRow label="匹配条件" value={`keyword=${input.keyword || '—'} / category=${input.target_category || '—'}`} />
              <InfoRow label="商品 metadata" value={`${dataReport.raw_meta_rows ?? 0} 行，命中 ${dataReport.matched_items ?? 0} 行`} />
              <InfoRow label="评论 review" value={`${dataReport.raw_review_rows ?? 0} 行，命中 ${dataReport.matched_reviews ?? 0} 行`} />
              <InfoRow label="生成竞品" value={`${dataReport.generated_competitors ?? competitors.length} 个`} />
              <InfoRow label="生成痛点" value={`${dataReport.generated_pain_points ?? painPoints.length} 类`} />
            </div>
            <div className="rounded-xl bg-black/30 p-4">
              <div className="text-sm font-semibold text-slate-200">字段补齐</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {(dataReport.inferred_fields || []).map((field: string) => (
                  <span key={field} className="rounded-full bg-white/5 px-2.5 py-1 text-xs text-slate-300 ring-1 ring-white/10">
                    {field}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {active === 'research' && (
          <div className="space-y-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">选品判断 Product Research</div>
            <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/[0.06] p-4">
              <div className="text-sm font-semibold text-cyan-100">最终为什么选这条</div>
              <div className="mt-3">
                <EvidenceList items={research.selection_rationale || selectedCandidateReason(input, research)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {Object.entries(research.score_breakdown || {}).map(([k, v]) => (
                <div key={k} className="rounded-xl bg-black/30 p-3 text-center">
                  <div className="text-xs text-slate-400">{cnText(k)}</div>
                  <div className="mt-1 text-2xl font-bold text-white">{String(v)}</div>
                </div>
              ))}
            </div>

            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="text-sm font-semibold text-slate-200">候选排序 Candidate Ranking</div>
              <div className="mt-3 space-y-3">
                {(research.candidate_ranking || []).map((item: any) => (
                  <div key={item.asin} className="rounded-xl border border-white/10 bg-white/[0.035] p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="font-semibold text-white">
                        <Bilingual value={item.title} />
                        <span className="ml-2 text-xs text-slate-400">{item.asin}</span>
                      </div>
                      <span className={cn('rounded-full px-2.5 py-1 text-xs font-semibold ring-1', item.role === 'selected' ? 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/25' : 'bg-white/5 text-slate-300 ring-white/10')}>
                        {item.role === 'selected' ? '最终主推' : '对照候选'} · {item.score}/100
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-5">
                      {Object.entries(item.score_parts || {}).map(([k, v]) => (
                        <div key={k} className="rounded-lg bg-black/25 px-2 py-1.5 text-center">
                          <div className="text-[11px] text-slate-500">{k}</div>
                          <div className="text-sm font-bold text-slate-100">{String(v)}</div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 space-y-1 text-xs text-slate-300">
                      {(item.why || []).map((line: string) => <div key={line}>{line}</div>)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="text-sm font-semibold text-slate-200">选品 Pipeline 明细</div>
              <div className="mt-3 space-y-3">
                {(research.research_pipeline || []).map((step: any, i: number) => (
                  <div key={step.step || i} className="rounded-xl border border-white/10 bg-white/[0.035] p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="font-semibold text-cyan-100">{String(i + 1).padStart(2, '0')} · {step.name}</div>
                      <span className="text-xs text-slate-500">{step.step}</span>
                    </div>
                    <div className="mt-2 text-slate-200">要回答的问题：{step.question}</div>
                    <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
                      <div className="rounded-lg bg-black/25 px-3 py-2">
                        <div className="text-xs text-slate-500">输入</div>
                        <div className="mt-1 text-slate-300">{Array.isArray(step.inputs) ? step.inputs.join('、') : step.inputs}</div>
                      </div>
                      <div className="rounded-lg bg-black/25 px-3 py-2">
                        <div className="text-xs text-slate-500">计算/判断</div>
                        <div className="mt-1 text-slate-300">{step.calculation}</div>
                      </div>
                      <div className="rounded-lg bg-black/25 px-3 py-2">
                        <div className="text-xs text-slate-500">输出</div>
                        <div className="mt-1 text-slate-300">{Array.isArray(step.output) ? step.output.join('；') : step.output}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-3">
              {competitors.map((item: any) => (
                <div key={item.asin || item.title} className="rounded-xl border border-white/10 bg-black/30 p-3 text-sm">
                  <div className="font-semibold text-white"><Bilingual value={item.title} /></div>
                  <div className="mt-1 text-slate-400">ASIN {item.asin || '—'} · 价格 {money(item.price)} · 评分 {item.rating ?? '—'} · 评论 {item.review_count ?? '—'} · 预估月销 {item.estimated_monthly_sales ?? '—'}</div>
                  {item.weaknesses?.length > 0 && <div className="mt-2 text-amber-200">弱点：{item.weaknesses.map((x: string) => `${x}（${cnText(x)}）`).join('、')}</div>}
                </div>
              ))}
            </div>
          </div>
        )}

        {active === 'listing' && (
          <div className="space-y-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">Listing 生成明细 Listing Draft</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <InfoRow label="生成对象" value={<Bilingual value={product.title} />} />
              <InfoRow label="候选池关系" value={`候选池 ${competitors.length} 条，当前 Listing 只为最终主推商品生成`} />
              <InfoRow label="业务目标" value="把这个候选品包装成 Amazon 可审核的初稿：先覆盖核心词 cable organizer，再表达 3 个安全卖点，不承诺解决 adhesive 等质量痛点。" />
              <InfoRow label="平台约束" value={`Amazon US：标题长度 ${listing.title?.length ?? 0}/180，五点 ${listing.bullets?.length ?? 0}/5，搜索词 ${listing.search_terms?.length ?? 0} 个`} />
            </div>

            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-4">
              <div className="text-sm font-semibold text-emerald-100">这一步具体要达成什么</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-lg bg-black/25 p-3 text-sm text-slate-200">
                  <div className="font-semibold text-white">1. 让平台知道卖什么</div>
                  <div className="mt-1 text-slate-400">标题必须包含 Cable Organizer / Clips / Desk 这类核心识别词。</div>
                </div>
                <div className="rounded-lg bg-black/25 p-3 text-sm text-slate-200">
                  <div className="font-semibold text-white">2. 让买家知道为什么买</div>
                  <div className="mt-1 text-slate-400">先表达 compact、reusable、easy setup 三个确定卖点。</div>
                </div>
                <div className="rounded-lg bg-black/25 p-3 text-sm text-slate-200">
                  <div className="font-semibold text-white">3. 不把痛点写成假承诺</div>
                  <div className="mt-1 text-slate-400">adhesive/too bulky/size mismatch 是风险信号，不能直接写“永不掉落/适配所有尺寸”。</div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-black/30 p-4">
              <div className="text-sm font-semibold text-slate-200">关键词与卖点来源</div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-lg bg-white/[0.04] p-3">
                  <div className="text-xs text-slate-400">基础关键词</div>
                  <div className="mt-1 text-sm font-semibold text-cyan-100">{input.keyword || '—'}</div>
                </div>
                <div className="rounded-lg bg-white/[0.04] p-3">
                  <div className="text-xs text-slate-400">商品特征</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(product.features || []).map((item: string) => (
                      <span key={item} className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-slate-200 ring-1 ring-white/10">
                        {item} / {cnText(item)}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-lg bg-white/[0.04] p-3">
                  <div className="text-xs text-slate-400">评论痛点</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {painPoints.map((point: any) => (
                      <span key={point.topic} className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-100 ring-1 ring-amber-500/20">
                        {point.topic} / {cnText(point.topic)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/[0.06] p-4">
              <div className="text-sm font-semibold text-cyan-100">痛点覆盖检查</div>
              <div className="mt-3 space-y-2">
                {painPoints.map((point: any) => {
                  const searchHit = (listing.search_terms || []).some((term: string) => term.toLowerCase().includes(point.topic.toLowerCase()))
                  const copyHit = [listing.title, ...(listing.bullets || []), listing.description].join(' ').toLowerCase().includes(point.topic.toLowerCase())
                  return (
                    <div key={point.topic} className="rounded-lg bg-black/25 px-3 py-2 text-sm text-slate-200">
                      <span className="font-semibold text-amber-100">{point.topic}（{cnText(point.topic)}）</span>
                      <span className="ml-2 text-slate-400">评论出现 {point.frequency} 次，严重度 {point.severity}/5。</span>
                      <span className="ml-2 text-cyan-100">
                        {searchHit || copyHit ? '已进入关键词/文案关注范围' : '当前未充分覆盖，后续应转为产品改良或卖点补充'}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            <InfoRow label="标题 Title" value={<Bilingual value={listing.title} />} />
            <div className="space-y-2">
              <div className="text-sm font-semibold text-slate-200">五点描述 Bullets</div>
              {(listing.bullets || []).map((item: string, i: number) => (
                <div key={item} className="rounded-lg bg-black/30 px-3 py-2 text-sm text-slate-100">
                  {i + 1}. <Bilingual value={item} />
                </div>
              ))}
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-200">搜索词 Search Terms</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {(listing.search_terms || []).map((term: string) => (
                  <span key={term} className="rounded-full bg-cyan-500/10 px-2.5 py-1 text-xs text-cyan-200 ring-1 ring-cyan-500/20">
                    {term}<span className="text-slate-400"> / {cnText(term)}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4 text-sm text-slate-200">
              <div className="font-semibold text-amber-100">业务上还缺什么</div>
              <div className="mt-2 space-y-1">
                <div>1. 五点现在只有 3 条，Amazon 通常要补到 5 条：尺寸兼容、安装表面、包装数量/适用场景。</div>
                <div>2. adhesive、too bulky、size mismatch 是差评痛点，不一定都应该写进卖点；其中 adhesive 更像产品质量改良项。</div>
                <div>3. 搜索词里出现 adhesive/too bulky/size mismatch 是研究提示，不是最终可直接发布的后台关键词。</div>
                <div>4. 后续接真实平台时，需要类目属性、变体、包装尺寸、FBA 费用、图片和合规证据一起进入发布包。</div>
              </div>
            </div>
          </div>
        )}

        {active === 'compliance' && (
          <div className="space-y-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">合规审核 Compliance</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <InfoRow label="审核结论" value={<DecisionBadge v={compliance.decision} />} />
              <InfoRow label="风险等级" value={cnText(compliance.risk_level)} />
              <InfoRow label="审核 ID" value={<span className="font-mono">{compliance.audit?.check_id || '—'}</span>} />
              <InfoRow label="运行模式" value={compliance.audit?.model === 'offline' ? '离线演示 stub' : compliance.audit?.model || '—'} />
            </div>
            {(compliance.evidence || []).map((item: any) => (
              <div key={item.title} className="rounded-xl bg-black/30 p-3 text-sm text-slate-200">
                <div className="font-semibold text-white">{item.title}</div>
                <div className="mt-1">{item.summary}</div>
              </div>
            ))}
          </div>
        )}

        {active === 'ops' && (
          <div className="space-y-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">运营与客服 Operations</div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <InfoRow label="ACOS" value={typeof ads.metrics?.acos === 'number' ? `${(ads.metrics.acos * 100).toFixed(1)}%` : '—'} />
              <InfoRow label="CVR" value={typeof ads.metrics?.cvr === 'number' ? `${(ads.metrics.cvr * 100).toFixed(1)}%` : '—'} />
              <InfoRow label="CPC" value={money(ads.metrics?.cpc)} />
              <InfoRow label="CPA" value={money(ads.metrics?.cpa)} />
            </div>
            {(ads.issues || []).map((issue: any) => (
              <div key={issue.category} className="rounded-xl border border-red-500/20 bg-red-500/[0.06] p-3 text-sm">
                <div className="font-semibold text-red-200">{cnText(issue.category)}</div>
                <div className="mt-1 text-slate-200">原因：{cnText(issue.reason)}</div>
                <div className="mt-1 text-slate-300">建议：{cnText(issue.suggestion)}</div>
              </div>
            ))}
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-3 text-sm">
              <div className="font-semibold text-amber-200">客服消息：{cnText(customer.intent)} / {cnText(customer.sentiment)} / {cnText(customer.urgency)}</div>
              <div className="mt-2 text-slate-200">英文回复草稿：{customer.draft_reply || '—'}</div>
              <div className="mt-2 text-slate-400">说明：当前只生成草稿，退款和承诺类动作进入 Gate。</div>
            </div>
          </div>
        )}

        {active === 'gate' && (
          <div className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">Action Gate 明细</div>
            {(report.gate_summary.blocked_or_human_review_actions || []).map((action: any, i: number) => (
              <div key={`${action.action_type}-${i}`} className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-lg font-bold text-amber-100">{cnText(action.action_type)} <span className="text-sm text-slate-400">/ {action.action_type}</span></div>
                  <DecisionBadge v={action.gate_decision} />
                </div>
                <div className="mt-3 space-y-1 text-sm text-slate-200">
                  {(action.reasons || []).map((reason: string) => (
                    <div key={reason}>原因：{cnText(reason)} <span className="text-slate-500">/ {reason}</span></div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
    </div>
  )
}

function CrossborderPipelineView() {
  const [report, setReport] = useState<CrossborderDemoReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [detailStep, setDetailStep] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const next = await api.crossborderDemo()
      if ((next as any).error) throw new Error((next as any).error)
      setReport(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  const runDemo = async () => {
    setRunning(true)
    setError('')
    try {
      const next = await api.runCrossborderDemo(false)
      if ((next as any).error) throw new Error((next as any).message || (next as any).error)
      setReport(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : '运行失败')
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const final = report?.final_summary
  const listing = report?.stages?.listing_generation?.listing
  const research = report?.stages?.product_research
  const input = report?.input_summary || {}
  const product = input.selected_product || {}
  const dataReport = report?.stages?.data_intake?.report || {}
  const competitors = input.competitors || []
  const painPoints = input.pain_points || []
  const sourceCategories = product.attributes?.source_categories || []
  const categoryPath = sourceCategories.length ? sourceCategories.join(' > ') : product.category

  if (report && final && detailStep) {
    return (
      <div className="mt-8">
        <StageExplorer report={report} initialActive={detailStep} onBack={() => setDetailStep(null)} />
      </div>
    )
  }

  return (
    <div className="mt-8 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white">跨境电商 Agent Pipeline</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-300">
            <span className="rounded-md bg-white/5 px-2 py-1 ring-1 ring-white/10">Amazon US</span>
            <span className="font-mono text-xs text-slate-400">{report?.demo.workflow_id ?? 'wf_demo_crossborder_pipeline'}</span>
          </div>
        </div>
        <button
          onClick={runDemo}
          disabled={running}
          className="rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 py-2.5 text-sm font-bold text-slate-950 shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60"
        >
          {running ? '运行中' : '重新运行'}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {error}
        </div>
      )}

      {loading && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-8 text-center text-slate-300">
          加载 Pipeline 结果
        </div>
      )}

      {report && final && (
        <>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 backdrop-blur-xl">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">当前候选商品</div>
                  <h3 className="mt-2 text-2xl font-bold leading-tight text-white">{product.title || listing?.title || '—'}</h3>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="rounded-md bg-white/5 px-2.5 py-1 text-xs text-slate-200 ring-1 ring-white/10">
                      目标平台：Amazon US
                    </span>
                    <span className="rounded-md bg-white/5 px-2.5 py-1 text-xs text-slate-200 ring-1 ring-white/10">
                      关键词：{input.keyword || '—'}
                    </span>
                    <span className="rounded-md bg-white/5 px-2.5 py-1 text-xs text-slate-200 ring-1 ring-white/10">
                      类目：{input.target_category || product.category || '—'}
                    </span>
                  </div>
                </div>
                <div className="min-w-[110px] text-right">
                  <div className="text-xs text-slate-400">机会分</div>
                  <div className="text-5xl font-black leading-none text-white">{research?.score ?? '—'}</div>
                  <div className="mt-1 text-sm text-emerald-300">高机会</div>
                </div>
              </div>
              <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3">
                <InfoRow label="公开数据命中" value={`${dataReport.matched_items ?? 0} 个商品 / ${dataReport.matched_reviews ?? 0} 条评论`} />
                <InfoRow label="候选池" value={`${competitors.length} 条候选/竞品，最终主推 1 条`} />
                <InfoRow label="差评痛点" value={`${painPoints.length} 类`} />
                <InfoRow label="目标售价" value={money(input.target_price)} />
                <InfoRow label="预估全成本" value={money(input.landed_cost)} />
                <InfoRow label="类目路径" value={<span className="break-words">{categoryPath || '—'}</span>} />
              </div>
              <div className="mt-4 rounded-xl bg-black/20 p-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">候选池 Candidate Pool</div>
                <div className="mt-2 space-y-2">
                  {competitors.map((item: any, i: number) => (
                    <div key={item.asin || item.title} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-white/[0.035] px-3 py-2 text-sm">
                      <span className="font-semibold text-slate-100">
                        {i === 0 ? '最终主推' : '候选/竞品'}：<Bilingual value={item.title} />
                      </span>
                      <span className="text-xs text-slate-400">ASIN {item.asin || '—'} · {money(item.price)} · 评分 {item.rating ?? '—'} · 评论 {item.review_count ?? '—'}</span>
                    </div>
                  ))}
                </div>
              </div>
              <button
                onClick={() => setDetailStep('product')}
                className="mt-5 rounded-xl bg-cyan-500/10 px-4 py-2 text-sm font-semibold text-cyan-100 ring-1 ring-cyan-400/25 transition hover:bg-cyan-500/15"
              >
                查看商品与评论痛点详情
              </button>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 backdrop-blur-xl">
              <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">为什么选择它</div>
              <div className="mt-4">
                <EvidenceList items={(research?.selection_rationale || selectedCandidateReason(input, research || {})).slice(0, 3)} />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">选品结果</div>
              <div className="mt-3 flex items-center justify-between gap-3">
                <DecisionBadge v={final.product_research_decision} />
                <span className="text-2xl font-bold tabular-nums text-white">{research?.score ?? '—'}</span>
              </div>
              <div className="mt-3 text-sm text-slate-300">机会等级：{research?.opportunity_level === 'high' ? '高' : cnText(research?.opportunity_level)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Listing 合规</div>
              <div className="mt-3"><DecisionBadge v={final.listing_compliance_decision} /></div>
              <div className="mt-3 text-sm text-slate-300">
                审核 ID：<span className="font-mono text-slate-200">{String(report.audit_summary.compliance_check_id || '—')}</span>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">运营诊断</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <DecisionBadge v={final.ads_decision} />
                <DecisionBadge v={final.customer_service_decision} />
              </div>
              <div className="mt-3 text-sm text-slate-300">拦截动作：{report.gate_summary.total_actions} 个</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">最终路由</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <DecisionBadge v={final.ready_for_publish ? 'ready_to_publish' : 'requires_revision'} />
                {final.human_review_required && <DecisionBadge v="requires_human_review" />}
              </div>
              <div className="mt-3 text-sm text-slate-300">发布生成物已就绪，高风险动作进人审</div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-7">
            {PIPELINE_STAGES.map(([key, label], i) => (
              <button
                key={key}
                onClick={() => setDetailStep(STAGE_TO_DETAIL[key] || 'product')}
                className="rounded-xl border border-white/10 bg-white/[0.025] p-4 text-left transition hover:border-cyan-400/40 hover:bg-cyan-500/[0.06] focus:outline-none focus:ring-2 focus:ring-cyan-400/40"
              >
                <div className="flex items-center justify-between gap-2 lg:block">
                  <div className="text-xs font-mono text-slate-500">{String(i + 1).padStart(2, '0')}</div>
                  <div className="mt-1 text-sm font-semibold text-slate-100">{label}</div>
                </div>
                <div className="mt-3"><DecisionBadge v={stageDecision(report, key)} /></div>
                <div className="mt-3 text-xs text-slate-400">点击查看详情</div>
              </button>
            ))}
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
            <h3 className="text-sm font-semibold text-slate-100">审计 ID</h3>
            <div className="mt-3 grid grid-cols-1 gap-2 text-xs md:grid-cols-2">
              {Object.entries(report.audit_summary).map(([k, v]) => (
                <div key={k} className="flex items-start justify-between gap-3 rounded-lg bg-black/20 px-3 py-2">
                  <span className="text-slate-400">{k}</span>
                  <span className="max-w-[360px] break-words text-right font-mono text-slate-200">
                    {Array.isArray(v) ? v.join(', ') : String(v || '—')}
                  </span>
                </div>
              ))}
            </div>
          </div>

        </>
      )}
    </div>
  )
}

const PROVENANCE: Record<string, { label: string; cls: string }> = {
  live: { label: '实时', cls: 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/25' },
  cached: { label: '缓存', cls: 'bg-cyan-500/10 text-cyan-200 ring-cyan-500/25' },
  manual: { label: '手动', cls: 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/25' },
  stub: { label: '占位估算', cls: 'bg-white/5 text-slate-400 ring-white/10' },
  proxy: { label: '代理估算', cls: 'bg-amber-500/10 text-amber-200 ring-amber-500/25' },
  snapshot: { label: '快照', cls: 'bg-fuchsia-500/10 text-fuchsia-200 ring-fuchsia-500/25' },
  unavailable: { label: '无数据', cls: 'bg-white/5 text-slate-400 ring-white/10' },
}

const SIGNAL_KIND: Record<string, string> = {
  trend_momentum: '趋势动量',
  demand_growth: '评论增速',
  surge: '排名飙升',
  absolute_demand: '绝对需求',
  differentiation: '差异化空间',
}

function OpportunityView() {
  const [report, setReport] = useState<import('./api').OpportunityReport | null>(null)
  const [seed, setSeed] = useState('neck massager')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The currently displayed deep-dive (defaults to the #1 niche; clicking another
  // niche fetches its deep-dive on demand).
  const [detail, setDetail] = useState<Partial<import('./api').OpportunityReport> | null>(null)
  const [activeKeyword, setActiveKeyword] = useState<string | null>(null)
  const [diveLoading, setDiveLoading] = useState(false)
  const [priceResult, setPriceResult] = useState<import('./api').InjectPricesResult | null>(null)
  const [priceLoading, setPriceLoading] = useState(false)
  const [unitCost, setUnitCost] = useState('')
  const [workflow, setWorkflow] = useState<import('./api').WorkflowResult | null>(null)
  const [wfLoading, setWfLoading] = useState(false)
  const [compareSel, setCompareSel] = useState<string[]>([])
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null)
  const [compareLoading, setCompareLoading] = useState(false)
  const [profitInputs, setProfitInputs] = useState<ProfitInputs>({
    sale_price: 40,
    unit_cost: 8,
    inbound_shipping_per_unit: 2,
    referral_fee_pct: 0.15,
    fba_fee: 5,
    ads_acos: 0.15,
    return_rate: 0.03,
    storage_fee_per_unit: 0,
    other_per_unit: 0,
  })
  const [profit, setProfit] = useState<ProfitResult | null>(null)
  const [sweepVar, setSweepVar] = useState<'sale_price' | 'unit_cost' | 'ads_acos' | 'return_rate'>('sale_price')
  const [sweepData, setSweepData] = useState<SweepPoint[]>([])

  const adopt = (r: import('./api').OpportunityReport) => {
    setReport(r)
    setSeed(r.seed_keyword || 'neck massager')
    setActiveKeyword(r.selected_keyword)
    setDetail({ research: r.research, intake_report: r.intake_report, selected_keyword: r.selected_keyword, competitors: r.competitors, improvement_spec: r.improvement_spec })
    setPriceResult(null)
    setWorkflow(null)
    setCompareSel((r.opportunities || []).slice(0, 2).map((o) => o.keyword))
    setCompareResult(null)
  }

  useEffect(() => {
    api.opportunityResult().then((r) => {
      if (!('error' in (r as any))) adopt(r)
    }).catch(() => {})
  }, [])

  const run = async () => {
    setLoading(true); setError(null)
    try {
      const r = await api.runOpportunity(seed)
      if ((r as any).error) setError((r as any).message || '运行失败')
      else adopt(r)
    } catch (e: any) { setError(String(e)) }
    setLoading(false)
  }

  const selectNiche = async (keyword: string) => {
    if (keyword === activeKeyword || diveLoading) return
    setDiveLoading(true); setActiveKeyword(keyword); setPriceResult(null)
    try {
      const d = await api.deepDive(keyword)
      if (!(d as any).error) setDetail(d)
    } catch { /* keep previous detail */ }
    setDiveLoading(false)
  }

  const toggleCompare = (keyword: string) => {
    setCompareSel((prev) => {
      if (prev.includes(keyword)) return prev.filter((item) => item !== keyword)
      if (prev.length >= 4) return prev
      return [...prev, keyword]
    })
  }

  const runCompare = async () => {
    if (compareSel.length < 2 || compareLoading) return
    setCompareLoading(true)
    try {
      setCompareResult(await api.compare(compareSel))
    } catch {
      setCompareResult(null)
    } finally {
      setCompareLoading(false)
    }
  }

  useEffect(() => {
    const competitors = (detail?.competitors || []) as Array<Record<string, any>>
    const prices = competitors.map((c) => Number(c.price)).filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b)
    const seededPrice = priceResult?.target_price_after || (prices.length ? prices[Math.floor(prices.length / 2)] : null)
    if (!seededPrice) return
    setProfitInputs((prev) => ({ ...prev, sale_price: Number(seededPrice.toFixed(2)) }))
  }, [activeKeyword, detail?.competitors, priceResult?.target_price_after])

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const nextProfit = await api.simulate(profitInputs)
        if (cancelled) return
        setProfit(nextProfit)
        const [start, stop] = sweepRange(profitInputs, sweepVar)
        const nextSweep = await api.sweep(profitInputs, sweepVar, start, stop, 20)
        if (!cancelled) setSweepData(nextSweep)
      } catch {
        if (!cancelled) {
          setProfit(null)
          setSweepData([])
        }
      }
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [profitInputs, sweepVar])

  const injectPrices = async () => {
    if (!activeNicheKeyword || priceLoading) return
    setPriceLoading(true)
    try {
      const cost = unitCost.trim() ? Number(unitCost) : undefined
      setPriceResult(await api.injectPrices(activeNicheKeyword, Number.isFinite(cost) ? cost : undefined))
    } catch {
      setPriceResult(null)
    } finally {
      setPriceLoading(false)
    }
  }

  const runWorkflow = async () => {
    if (!report || wfLoading) return
    setWfLoading(true)
    try {
      setWorkflow(await api.toWorkflow(report.seed_keyword))
    } catch {
      setWorkflow(null)
    } finally {
      setWfLoading(false)
    }
  }

  const research = detail?.research
  const intake = detail?.intake_report
  const coverage = intake?.price_coverage ?? 0
  const activeNicheKeyword = detail?.selected_keyword ?? report?.selected_keyword
  const improvementSpec = detail?.improvement_spec

  return (
    <div className="mt-8 space-y-5">
      {/* 控制条：种子词 + 重新发现 */}
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 backdrop-blur-xl">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">Mode 2 → Mode 1</div>
            <h2 className="mt-1 text-xl font-bold text-white">机会发现 → 选品深挖</h2>
            <p className="mt-1 text-sm text-slate-300">种子词自动发现赛道 → 多信号排序 → 第一名交给五维深度分析</p>
          </div>
          <div className="flex items-end gap-2">
            <div>
              <div className="mb-1 text-xs text-slate-400">种子关键词</div>
              <input
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                className="w-56 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/50"
              />
            </div>
            <button
              onClick={run}
              disabled={loading}
              className="rounded-lg bg-cyan-500/15 px-4 py-2 text-sm font-semibold text-cyan-100 ring-1 ring-cyan-400/35 transition hover:bg-cyan-500/25 disabled:opacity-50"
            >
              {loading ? '运行中（约30s）…' : '重新发现'}
            </button>
          </div>
        </div>
        {error && <div className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300 ring-1 ring-red-500/25">{error}</div>}
      </div>

      {!report ? (
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-8 text-center text-slate-400">
          暂无缓存结果。在上方输入种子词后点「重新发现」。
        </div>
      ) : (
        <>
          {/* mode2→mode1 衔接说明 */}
          <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/[0.05] p-5 backdrop-blur-xl">
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">衔接逻辑 Handoff</div>
            <div className="mt-3 space-y-2">
              {(report.handoff || []).map((line, i) => (
                <div key={i} className={cn('text-sm leading-relaxed', line.startsWith('⚠') ? 'text-amber-200' : 'text-slate-200')}>
                  {line}
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1fr]">
            {/* Mode 2: 机会赛道排名 */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-5 backdrop-blur-xl">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-200">① 机会赛道排名</h3>
                  <span className="text-xs text-slate-400">种子「{report.seed_keyword}」→ {report.opportunities.length} 个赛道 · 点击深挖 / 勾选横评</span>
                </div>
                <button
                  type="button"
                  onClick={runCompare}
                  disabled={compareSel.length < 2 || compareLoading}
                  className="rounded-lg bg-cyan-500/15 px-3 py-2 text-xs font-semibold text-cyan-100 ring-1 ring-cyan-400/30 transition hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {compareLoading ? '对比中…' : `对比选中 (${compareSel.length})`}
                </button>
              </div>
              <div className="mt-4 space-y-3">
                {report.opportunities.map((o) => {
                  const active = o.keyword === activeNicheKeyword
                  const checked = compareSel.includes(o.keyword)
                  const disabledCheck = !checked && compareSel.length >= 4
                  return (
                    <div
                      key={o.keyword}
                      className={cn('w-full rounded-xl border p-3 text-left transition', active ? 'border-cyan-400/40 bg-cyan-500/[0.07]' : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]')}
                    >
                      <div className="flex items-start gap-3">
                        <label className={cn('mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-black/25 transition', disabledCheck ? 'cursor-not-allowed opacity-40' : 'cursor-pointer hover:border-cyan-400/40')}>
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={disabledCheck}
                            onChange={() => toggleCompare(o.keyword)}
                            className="h-4 w-4 accent-cyan-400"
                            aria-label={`对比 ${o.keyword}`}
                          />
                        </label>
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={() => selectNiche(o.keyword)}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectNiche(o.keyword) }}
                          className="min-w-0 flex-1 cursor-pointer rounded-lg outline-none focus:ring-2 focus:ring-cyan-400/40"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex min-w-0 items-center gap-2">
                              <span className={cn('flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold', active ? 'bg-cyan-400 text-slate-950' : 'bg-white/10 text-slate-300')}>{o.rank}</span>
                              <span className="truncate font-semibold text-white">{o.keyword}</span>
                            </div>
                            <span className="text-lg font-bold text-white">{o.score.toFixed(1)}</span>
                          </div>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-slate-400 ring-1 ring-white/10">
                              来源：{o.discovery_source === 'manual' ? '种子词' : 'Trends 发现'}
                            </span>
                            {o.signals.filter((s) => s.provenance !== 'unavailable').map((s) => {
                              const p = PROVENANCE[s.provenance] ?? PROVENANCE.unavailable
                              return (
                                <span key={s.kind} className={cn('rounded-full px-2 py-0.5 text-[11px] ring-1', p.cls)}>
                                  {SIGNAL_KIND[s.kind] ?? s.kind} {s.score.toFixed(0)} · {p.label}
                                </span>
                              )
                            })}
                          </div>
                          {active && (
                            <div className="mt-2 space-y-1 border-t border-white/10 pt-2 text-[11px] text-slate-300">
                              {(o.rationale || []).map((r, i) => <div key={i}>{r}</div>)}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Mode 1: 选品深挖 */}
            <div className="space-y-5">
              <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-5 backdrop-blur-xl">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-200">
                    ② 选品深度分析：{activeNicheKeyword}
                    {diveLoading && <span className="ml-2 text-xs text-cyan-300">深挖中…</span>}
                  </h3>
                  {research && <DecisionBadge v={research.decision} />}
                </div>
                {research && (
                  <>
                    <div className="mt-4 grid grid-cols-5 gap-2">
                      {Object.entries(research.score_breakdown).map(([k, v]) => {
                        const degraded = (k === 'profitability' && coverage < 0.25) || (k === 'compliance' && (v as number) < 50)
                        return (
                          <div key={k} className={cn('rounded-xl p-2.5 text-center ring-1', degraded ? 'bg-amber-500/[0.08] ring-amber-500/25' : 'bg-black/30 ring-white/10')}>
                            <div className="text-[11px] text-slate-400">{cnText(k)}</div>
                            <div className={cn('mt-1 text-xl font-bold', degraded ? 'text-amber-200' : 'text-white')}>{v as number}</div>
                            {degraded && <div className="mt-0.5 text-[9px] text-amber-300/80">{k === 'profitability' ? '数据不足' : '需核实'}</div>}
                          </div>
                        )
                      })}
                    </div>
                    <div className="mt-4 flex items-center gap-4 text-sm">
                      <div><span className="text-slate-400">机会分</span> <span className="font-bold text-white">{research.score}/100</span></div>
                      <div><span className="text-slate-400">置信度</span> <span className={cn('font-bold', research.confidence < 0.6 ? 'text-amber-200' : 'text-white')}>{(research.confidence * 100).toFixed(0)}%</span></div>
                      <div><span className="text-slate-400">机会等级</span> <span className="font-bold text-white">{cnText(research.opportunity_level)}</span></div>
                    </div>
                  </>
                )}
              </div>

              {/* 诚实标注面板 */}
              <div className="rounded-2xl border border-amber-500/20 bg-amber-500/[0.04] p-5 backdrop-blur-xl">
                <div className="text-xs font-semibold uppercase tracking-wider text-amber-200">数据诚实标注 Data Honesty</div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-black/30 p-3">
                    <div className="text-xs text-slate-400">竞品价格覆盖</div>
                    <div className={cn('mt-1 text-2xl font-bold', coverage < 0.25 ? 'text-amber-200' : 'text-white')}>{(coverage * 100).toFixed(0)}%</div>
                    <div className="mt-1 text-[11px] text-slate-400">{coverage < 0.25 ? '利润维度已降级转人工' : '价格充足'}</div>
                  </div>
                  <div className="rounded-lg bg-black/30 p-3">
                    <div className="text-xs text-slate-400">真实数据规模</div>
                    <div className="mt-1 text-sm text-slate-200">{(intake?.raw_meta_rows ?? 0).toLocaleString()} 商品</div>
                    <div className="text-sm text-slate-200">{(intake?.generated_competitors ?? 0)} 个竞品入池</div>
                    <div className="text-sm text-slate-200">{(intake?.generated_pain_points ?? 0)} 类评论痛点</div>
                  </div>
                </div>
                {(intake?.warnings || []).length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    {intake!.warnings.map((w, i) => (
                      <div key={i} className="rounded-lg bg-black/20 px-3 py-1.5 text-[11px] text-amber-200/90">⚠ {w}</div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.045] p-5 backdrop-blur-xl">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-emerald-200">③ 真实价格注入</div>
                    <h3 className="mt-1 text-sm font-semibold text-slate-100">Keepa/手动价格 · before / after</h3>
                    <p className="mt-1 text-xs text-slate-400">只给入围 ASIN 补价，然后重跑选品分数。</p>
                  </div>
                  <div className="flex flex-wrap items-end gap-2">
                    <div>
                      <div className="mb-1 text-[11px] text-slate-400">采购成本 unit_cost</div>
                      <input
                        value={unitCost}
                        onChange={(e) => setUnitCost(e.target.value)}
                        placeholder="可选，如 8"
                        inputMode="decimal"
                        className="w-32 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-emerald-400/50"
                      />
                    </div>
                    <button
                      onClick={injectPrices}
                      disabled={priceLoading || !activeNicheKeyword}
                      className="rounded-lg bg-emerald-500/15 px-4 py-2 text-sm font-semibold text-emerald-100 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/25 disabled:cursor-wait disabled:opacity-50"
                    >
                      {priceLoading ? '注入中…' : '注入真实价格'}
                    </button>
                  </div>
                </div>

                {priceResult && (
                  <div className="mt-4 space-y-4">
                    <div className="grid grid-cols-[1fr_1fr_1fr] gap-2 text-sm">
                      <div className="rounded-lg bg-black/25 px-3 py-2 text-xs font-semibold text-slate-400">指标</div>
                      <div className="rounded-lg bg-black/25 px-3 py-2 text-xs font-semibold text-slate-400">注入前</div>
                      <div className="rounded-lg bg-black/25 px-3 py-2 text-xs font-semibold text-slate-400">注入后</div>
                      <div className="rounded-lg bg-black/20 px-3 py-2 text-slate-300">利润分</div>
                      <div className="rounded-lg bg-black/20 px-3 py-2 font-bold text-slate-100">{priceResult.before.profitability}</div>
                      <div className={cn('rounded-lg bg-black/20 px-3 py-2 font-bold', priceResult.after.profitability >= priceResult.before.profitability ? 'text-emerald-200' : 'text-slate-100')}>
                        {priceResult.after.profitability}
                      </div>
                      <div className="rounded-lg bg-black/20 px-3 py-2 text-slate-300">决策</div>
                      <div className="rounded-lg bg-black/20 px-3 py-2"><DecisionBadge v={priceResult.before.decision} /></div>
                      <div className="rounded-lg bg-black/20 px-3 py-2"><DecisionBadge v={priceResult.after.decision} /></div>
                      <div className="rounded-lg bg-black/20 px-3 py-2 text-slate-300">价格覆盖</div>
                      <div className="rounded-lg bg-black/20 px-3 py-2 font-bold text-slate-100">{pct(priceResult.coverage_before)}</div>
                      <div className={cn('rounded-lg bg-black/20 px-3 py-2 font-bold', priceResult.coverage_after >= priceResult.coverage_before ? 'text-emerald-200' : 'text-slate-100')}>
                        {pct(priceResult.coverage_after)}
                      </div>
                      <div className="rounded-lg bg-black/20 px-3 py-2 text-slate-300">转人工</div>
                      <div className="rounded-lg bg-black/20 px-3 py-2"><DecisionBadge v={priceResult.before.human_review_required} /></div>
                      <div className="rounded-lg bg-black/20 px-3 py-2"><DecisionBadge v={priceResult.after.human_review_required} /></div>
                    </div>

                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">补价记录 Price Quotes</div>
                      <div className="mt-2 space-y-2">
                        {priceResult.price_quotes.map((quote) => {
                          const p = PROVENANCE[quote.provenance] ?? PROVENANCE.unavailable
                          return (
                            <div key={quote.asin} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-black/25 px-3 py-2 text-xs">
                              <span className="font-mono text-slate-200">{quote.asin}</span>
                              <span className="text-slate-100">{quote.price === null ? '无价格' : `${quote.currency} ${money(quote.price)}`}</span>
                              <span className={cn('rounded-full px-2 py-0.5 font-semibold ring-1', p.cls)}>{p.label}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    {!unitCost.trim() && (
                      <div className="rounded-lg bg-amber-500/[0.08] px-3 py-2 text-xs text-amber-100 ring-1 ring-amber-500/20">
                        未填采购成本：价格覆盖可以解除降级，但真实毛利还需要 unit_cost 才能算准。
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 关键 issues */}
              {research && research.issues.length > 0 && (
                <div className="rounded-2xl border border-white/10 bg-white/[0.025] p-5 backdrop-blur-xl">
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-300">决策依据 Issues</div>
                  <div className="mt-3 space-y-2">
                    {research.issues.map((iss, i) => (
                      <div key={i} className="rounded-lg bg-black/25 p-2.5 text-[11px]">
                        <span className={cn('font-semibold', iss.severity === 'high' ? 'text-red-300' : 'text-amber-200')}>{iss.category}</span>
                        <span className="ml-2 text-slate-300">{iss.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <ImprovementPanel spec={improvementSpec} />
              <ProfitSimulatorPanel
                inputs={profitInputs}
                profit={profit}
                sweepVar={sweepVar}
                sweepData={sweepData}
                onInputsChange={setProfitInputs}
                onSweepVarChange={setSweepVar}
              />
            </div>
          </div>

          {compareResult && <CompareScorecard result={compareResult} />}

          <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/[0.04] p-5 backdrop-blur-xl">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">④ 运营流程</div>
                <h3 className="mt-1 text-base font-bold text-white">Listing → 合规 → 发布闸门</h3>
                <p className="mt-1 text-xs text-slate-400">在排名第一的赛道上跑完整运营 workflow。</p>
              </div>
              <button
                onClick={runWorkflow}
                disabled={wfLoading || !report}
                className="rounded-lg bg-cyan-500/15 px-4 py-2 text-sm font-semibold text-cyan-100 ring-1 ring-cyan-400/35 transition hover:bg-cyan-500/25 disabled:cursor-wait disabled:opacity-50"
              >
                {wfLoading ? '运行中…' : '把 #1 赛道送入运营流程'}
              </button>
            </div>

            {workflow && (
              <div className="mt-5 space-y-5">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm text-slate-400">workflow_status</span>
                  <DecisionBadge v={workflow.workflow_status} />
                  {workflow.workflow?.compliance?.decision && (
                    <>
                      <span className="text-sm text-slate-500">合规</span>
                      <DecisionBadge v={workflow.workflow.compliance.decision} />
                    </>
                  )}
                </div>

                {(workflow.workflow?.stage_results || []).length > 0 && (
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Stage 链</div>
                    <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-4">
                      {(workflow.workflow?.stage_results || []).map((stage, i) => (
                        <div key={`${stage.name}-${i}`} className="rounded-xl border border-white/10 bg-black/25 p-3">
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <div className="font-mono text-[11px] text-slate-500">{String(i + 1).padStart(2, '0')}</div>
                              <div className="mt-1 text-sm font-semibold text-white">{stage.name}</div>
                            </div>
                            <DecisionBadge v={stage.decision || stage.status || 'pass'} />
                          </div>
                          <div className="mt-2 text-[11px] text-slate-500">{stage.mode}</div>
                          {stage.summary && <div className="mt-2 text-xs leading-relaxed text-slate-300">{stage.summary}</div>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {workflow.workflow?.listing && (
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div className="rounded-xl border border-white/10 bg-black/25 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">Listing 预览</div>
                      <div className="mt-2 text-sm font-semibold leading-relaxed text-white">{workflow.workflow.listing.title || '—'}</div>
                      <div className="mt-3 space-y-2">
                        {(workflow.workflow.listing.bullets || []).slice(0, 2).map((bullet, i) => (
                          <div key={bullet} className="rounded-lg bg-white/[0.04] px-3 py-2 text-xs text-slate-300">
                            {i + 1}. {bullet}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-black/25 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">合规与发布</div>
                      <div className="mt-3 grid grid-cols-1 gap-2 text-sm">
                        <InfoRow label="合规结论" value={<DecisionBadge v={workflow.workflow.compliance?.decision || '—'} />} />
                        <InfoRow label="风险等级" value={cnText(workflow.workflow.compliance?.risk_level)} />
                        <InfoRow label="发布状态" value={<DecisionBadge v={workflow.workflow.status || workflow.workflow_status} />} />
                      </div>
                    </div>
                  </div>
                )}

                {((workflow.workflow?.notes || []).length > 0 || workflow.workflow_status === 'compliance_runtime_unavailable' || workflow.workflow?.compliance?.decision === 'requires_human_review') && (
                  <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4 text-sm text-amber-100">
                    <div className="font-semibold">诚实提示</div>
                    <div className="mt-2 space-y-1 text-slate-200">
                      <div>真实数据的 ProductBrief 可能偏薄，Listing 或合规转人工是预期行为。</div>
                      {(workflow.workflow?.notes || []).map((note) => <div key={note}>{note}</div>)}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function ReviewDetailPage({
  record,
  onBack,
  onFeedback,
}: {
  record: ReviewRecord
  onBack: () => void
  onFeedback: (id: string, decision: 'APPROVE' | 'REJECT') => void
}) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-8 space-y-5">
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">Review Detail</div>
            <h2 className="mt-1 text-2xl font-bold text-white">详情 / 审计</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge v={record.final_verdict} />
              <span className="font-mono text-xs text-slate-300">{record.id}</span>
              <span className="text-xs text-slate-400">{record.tokens.toLocaleString()} tok · {record.latency_ms} ms</span>
            </div>
          </div>
          <button
            onClick={onBack}
            className="rounded-xl bg-white/[0.06] px-4 py-2.5 text-sm font-semibold text-cyan-100 ring-1 ring-white/10 transition hover:bg-white/[0.1]"
          >
            返回主页
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-5">
          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 backdrop-blur-xl">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-300">审核素材</div>
            <div className="mt-3 rounded-xl border border-white/5 bg-white/[0.02] p-3 text-sm text-slate-200">
              {record.material_text || '（无文案）'}
            </div>
          </div>

          {record.image_paths.length > 0 && (
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 backdrop-blur-xl">
              <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-300">原图 · 人工核对</div>
              <div className="grid gap-3">
                {record.image_paths.map((_, i) => (
                  <img
                    key={i}
                    src={`/api/records/${record.id}/image?idx=${i}`}
                    alt={`素材图 ${i + 1}`}
                    className="max-h-[420px] w-full rounded-xl border border-white/10 bg-white object-contain"
                  />
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-5">
          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 backdrop-blur-xl">
            <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-300">违规明细</div>
            {record.violations.length > 0 ? record.violations.map((v, i) => (
              <div key={i} className="mb-3 rounded-xl border border-red-500/20 bg-red-500/[0.06] p-4 text-sm">
                <div className="font-semibold text-red-300">⚠️ {v.rule_name}
                  <span className="ml-1 text-xs font-normal text-slate-300">[{v.expert}]</span></div>
                <div className="mt-2 text-slate-200">证据：{v.evidence}</div>
                <div className="mt-2 text-xs leading-relaxed text-slate-300">法条：{v.law_article || '—'}</div>
                <div className="mt-2 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.06] px-3 py-2 text-emerald-100">
                  建议：{v.suggestion || '—'}
                </div>
              </div>
            )) : (
              <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-4 text-sm text-emerald-100">
                未发现明确违规点。
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 backdrop-blur-xl">
            <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-300">推理链 · 审计</div>
            <div className="space-y-1.5 rounded-xl border border-white/5 bg-black/30 p-3 font-mono text-xs">
              {record.reasoning_chain.map((s, i) => {
                const hot = s.includes('辩论') || s.includes('冲突')
                return (
                  <div key={i} className={cn('flex gap-2', hot ? 'text-amber-300' : 'text-slate-200')}>
                    <span className="text-slate-400">{String(i + 1).padStart(2, '0')}</span>
                    <span>{s}</span>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 backdrop-blur-xl">
            <div className="mb-3 text-xs text-slate-300">
              人工裁决：<span className="text-slate-100">{record.human_decision ?? '未裁决'}</span>
            </div>
            <div className="flex gap-2">
              <button onClick={() => onFeedback(record.id, 'APPROVE')}
                className="flex-1 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 px-4 py-2.5 text-sm font-medium shadow-lg shadow-indigo-500/20 transition hover:brightness-110">
                确认违规
              </button>
              <button onClick={() => onFeedback(record.id, 'REJECT')}
                className="flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/10">
                误报放行
              </button>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

export default function App() {
  const [view, setView] = useState<'compliance' | 'crossborder' | 'opportunity'>('compliance')
  const [stats, setStats] = useState<Stats | null>(null)
  const [records, setRecords] = useState<ReviewRecord[]>([])
  const [sel, setSel] = useState<ReviewRecord | null>(null)
  const [detailPage, setDetailPage] = useState(false)
  const [reviewText, setReviewText] = useState('智能扫地机器人 全国销量第一 限时特惠')
  const [reviewImage, setReviewImage] = useState('')
  const reviewCase = 'abs_plain_01'
  const [reviewRunning, setReviewRunning] = useState(false)
  const [reviewError, setReviewError] = useState('')
  const [lastReview, setLastReview] = useState<ReviewRunResult | null>(null)
  const [uploadedImage, setUploadedImage] = useState<ReviewUploadResult | null>(null)
  const [reviewUploading, setReviewUploading] = useState(false)

  const load = async () => {
    setStats(await api.stats())
    setRecords(await api.records())
  }
  useEffect(() => {
    let ignore = false
    Promise.all([api.stats(), api.records()]).then(([nextStats, nextRecords]) => {
      if (ignore) return
      setStats(nextStats)
      setRecords(nextRecords)
    })
    return () => { ignore = true }
  }, [])

  const open = async (id: string) => {
    setSel(await api.record(id))
    setDetailPage(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const backToReviewHome = () => {
    setDetailPage(false)
    setSel(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const fb = async (id: string, d: 'APPROVE' | 'REJECT') => {
    await api.feedback(id, d); await open(id); load()
  }
  const uploadReviewImage = async (file?: File) => {
    if (!file) return
    setReviewUploading(true)
    setReviewError('')
    try {
      const out = await api.uploadReviewImage(file)
      if ((out as any).error) throw new Error((out as any).message || (out as any).error)
      setUploadedImage(out)
      setReviewImage(out.file_path)
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : '上传失败')
    } finally {
      setReviewUploading(false)
    }
  }
  const runReview = async (payload?: { case_id?: string }) => {
    setReviewRunning(true)
    setReviewError('')
    setSel(null)
    setDetailPage(false)
    try {
      const body = payload?.case_id
        ? { case_id: payload.case_id, offline_fallback: true }
        : { text: reviewText, image_path: reviewImage || undefined, offline_fallback: true }
      const out = await api.runReview(body)
      if ((out as any).error) throw new Error((out as any).message || (out as any).error)
      setLastReview(out)
      await load()
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : '审核失败')
    } finally {
      setReviewRunning(false)
    }
  }

  return (
    <div className="min-h-full w-full">
      <AuroraBackground />
      <div className="mx-auto max-w-6xl px-6 py-10">
        <motion.div initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }}>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300 backdrop-blur">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Agent-as-Tool · Cross-border Operations
            </div>
            <div className="flex gap-2">
              <NavButton active={view === 'compliance'} onClick={() => setView('compliance')}>合规 Agent</NavButton>
              <NavButton active={view === 'opportunity'} onClick={() => setView('opportunity')}>机会发现</NavButton>
              <NavButton active={view === 'crossborder'} onClick={() => setView('crossborder')}>跨境 Pipeline</NavButton>
            </div>
          </div>
          <h1 className="mt-4 text-4xl font-bold tracking-tight text-white">
            {view === 'opportunity' ? '选品机会发现引擎'
              : view === 'crossborder' ? '跨境电商 Agent 控制台' : '广告法/证照合规 Agent'}
          </h1>
          <p className="mt-2 text-slate-200">
            {view === 'opportunity'
              ? <>Google Trends 发现赛道 → 评论痛点挖差异化 → <span className="text-cyan-300/90">多信号融合排序</span> → 第一名五维深挖（基于 6 万真实 Amazon 商品）</>
              : view === 'crossborder'
              ? '公开 Amazon 数据 → 选品 → Listing → 合规 → 广告诊断 → 客服处理 → Action Gate'
              : <>文字/图片素材 → 多专家审核 → <span className="text-amber-300/90">违规证据定位</span> → 可直接替换的整改建议 → 审计落库</>}
          </p>
        </motion.div>

        {view === 'opportunity' ? <OpportunityView /> :
        view === 'crossborder' ? <CrossborderPipelineView /> :
        detailPage && sel ? (
          <ReviewDetailPage record={sel} onBack={backToReviewHome} onFeedback={fb} />
        ) : (
        <>
        <div className="mt-8 rounded-2xl border border-cyan-500/20 bg-cyan-500/[0.035] p-5 backdrop-blur-xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">Compliance Agent Pipeline</div>
              <h2 className="mt-1 text-xl font-bold text-white">新建素材审核</h2>
              <p className="mt-1 text-sm text-slate-300">
                输入文案/图片 → 初筛 → 视觉提取 → 多专家审核 → PASS / VIOLATION / NEEDS_HUMAN → 审计记录与人工复核
              </p>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="space-y-3">
              <label className="block">
                <div className="mb-1 text-xs font-semibold text-slate-400">审核文案</div>
                <textarea
                  value={reviewText}
                  onChange={(e) => setReviewText(e.target.value)}
                  rows={4}
                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm leading-relaxed text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400/50"
                  placeholder="例如：智能扫地机器人 全国销量第一 限时特惠"
                />
              </label>
              <label className="block">
                <div className="mb-1 text-xs font-semibold text-slate-400">上传图片（可选）</div>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => uploadReviewImage(e.target.files?.[0])}
                  disabled={reviewUploading || reviewRunning}
                  className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-200 file:mr-3 file:rounded-lg file:border-0 file:bg-cyan-400/10 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-cyan-100 hover:file:bg-cyan-400/15 disabled:opacity-50"
                />
                <div className="mt-1 text-xs leading-relaxed text-slate-500">
                  {reviewUploading
                    ? '图片上传中...'
                    : uploadedImage
                    ? `已上传并入库：${uploadedImage.filename} · ${Math.round(uploadedImage.size / 1024)}KB`
                    : '真实部署推荐上传图片：后端保存临时资产并写入审核记录，不依赖用户填写服务器本机路径。当前 fallback 演示需配合文案审核；Vision 模型可用时读取图片文字。'}
                </div>
                {uploadedImage && (
                  <div className="mt-3 overflow-hidden rounded-xl border border-white/10 bg-black/25">
                    <img src={uploadedImage.image_url} alt="已上传待审核图片" className="max-h-40 w-full bg-white object-contain" />
                  </div>
                )}
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={() => runReview()}
                  disabled={reviewRunning || (!reviewText.trim() && !reviewImage.trim())}
                  className="rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 py-2.5 text-sm font-bold text-slate-950 shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {reviewRunning ? '审核中…' : '开始审核并落库'}
                </button>
                {reviewError && <span className="text-sm text-red-300">{reviewError}</span>}
              </div>
              {lastReview?.record && (
                <div className="rounded-xl border border-cyan-400/20 bg-cyan-400/[0.06] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wider text-cyan-200">最近一次审核结果</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <Badge v={lastReview.record.final_verdict} />
                        <span className="font-mono text-xs text-slate-300">{lastReview.record_id}</span>
                        <span className="rounded-full bg-white/[0.06] px-2 py-1 text-xs text-slate-300">{lastReview.mode}</span>
                      </div>
                    </div>
                    <button
                      onClick={() => lastReview.record_id && open(lastReview.record_id)}
                      className="rounded-lg bg-white/[0.06] px-3 py-2 text-xs font-semibold text-cyan-100 ring-1 ring-white/10 transition hover:bg-white/[0.1]"
                    >
                      查看详情
                    </button>
                  </div>
                  {lastReview.record.violations?.[0] ? (
                    <div className="mt-3 space-y-2 text-sm leading-relaxed">
                      <div className="text-slate-200">
                        <span className="text-slate-400">证据：</span>{lastReview.record.violations[0].evidence}
                      </div>
                      <div className="rounded-lg border border-emerald-400/20 bg-emerald-400/[0.06] px-3 py-2 text-emerald-100">
                        <span className="text-emerald-300">整改：</span>{lastReview.record.violations[0].suggestion}
                      </div>
                    </div>
                  ) : (
                    <div className="mt-3 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.06] px-3 py-2 text-sm text-emerald-100">
                      未发现明确违规点，可以进入人工抽检或发布前复核。
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-4">
            <div className="overflow-hidden rounded-xl border border-red-400/20 bg-black/25">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
                <div>
                  <div className="text-sm font-semibold text-slate-100">素材小图预览</div>
                  <div className="mt-0.5 text-xs text-slate-400">和左侧文案匹配：图内包含“全国销量第一”</div>
                </div>
                <button
                  onClick={() => runReview({ case_id: reviewCase })}
                  disabled={reviewRunning}
                  className="rounded-lg bg-red-400/10 px-3 py-2 text-xs font-semibold text-red-100 ring-1 ring-red-300/20 transition hover:bg-red-400/15 disabled:opacity-50"
                >
                  用这张图审核
                </button>
              </div>
              <div className="bg-slate-950/60 p-3">
                <img
                  src={`/api/review/cases/${reviewCase}/image`}
                  alt="不合规广告素材样例"
                  className="max-h-48 w-full rounded-lg border border-white/10 bg-white object-contain"
                />
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-black/25 p-4">
              <div className="text-sm font-semibold text-slate-100">这条链路展示什么</div>
              <div className="mt-3 space-y-2 text-xs leading-relaxed text-slate-300">
                <div><span className="text-cyan-200">结构化输入：</span>文案、本机图片路径或右侧演示素材。</div>
                <div><span className="text-cyan-200">Agent 审核：</span>真实模型可用时走 Vision + 多专家 + 辩论；模型不可用时自动用本地规则 fallback，保证 demo 可跑。</div>
                <div><span className="text-cyan-200">结构化输出：</span>判定、证据、法条、可替换整改建议、置信度、推理链。</div>
                <div><span className="text-cyan-200">Workflow Gate：</span>低置信/高风险进入人工复核，人工裁决回写形成反馈闭环。</div>
              </div>
            </div>
            </div>
          </div>
        </div>

        {/* 统计 */}
        <div className="mt-8 flex flex-wrap gap-4">
          <StatCard i={0} n={stats?.total ?? 0} label="总审核" accent="bg-indigo-500" />
          <StatCard i={1} n={stats?.by_verdict.VIOLATION ?? 0} label="违规" accent="bg-red-500" />
          <StatCard i={2} n={stats?.by_verdict.PASS ?? 0} label="通过" accent="bg-emerald-500" />
          <StatCard i={3} n={stats?.needs_human ?? 0} label="待人工" accent="bg-amber-500" />
          <StatCard i={4} n={stats?.total_tokens ?? 0} label="累计 Tokens" accent="bg-cyan-500" />
        </div>

        <div className="mt-8">
          {/* 记录表 */}
          <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] backdrop-blur-xl">
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-3.5">
              <h3 className="text-sm font-semibold text-slate-200">审核记录</h3>
              <span className="text-xs text-slate-300">{records.length} 条</span>
            </div>
            <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-slate-300">
                <tr className="text-left">
                  {['素材', '场景', '判定', '置信', '成本', '人工', '时间', '操作'].map((h) => (
                    <th key={h} className="whitespace-nowrap px-4 py-2.5 text-xs font-medium uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map((r, i) => (
                  <motion.tr
                    key={r.id}
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }}
                    onClick={() => open(r.id)}
                    className={cn(
                      'group cursor-pointer border-t border-white/5 transition-colors hover:bg-white/[0.04]',
                      sel?.id === r.id && 'bg-indigo-500/10',
                    )}
                  >
                    <td className="px-4 py-3.5 max-w-[320px]">
                      <div className="flex min-w-0 items-center gap-3">
                        <RecordThumbs record={r} />
                        <div className="min-w-0">
                          <div className="truncate text-slate-100">{r.material_text || '（无文案）'}</div>
                          <div className="font-mono text-[11px] text-slate-400">{r.id}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="inline-block whitespace-nowrap rounded-md bg-white/5 px-2 py-1 text-xs text-slate-200 ring-1 ring-white/10">
                        {SCENE_NAME[r.scene_id] ?? r.scene_id}
                      </span>
                    </td>
                    <td className="px-4 py-3.5"><Badge v={r.final_verdict} /></td>
                    <td className="px-4 py-3.5 tabular-nums text-slate-300">{r.confidence}</td>
                    <td className="px-4 py-3.5 tabular-nums text-slate-300">{r.tokens.toLocaleString()}</td>
                    <td className="px-4 py-3.5 text-slate-200">
                      {r.human_decision
                        ? <span className="text-xs">{r.human_decision}</span>
                        : r.needs_human ? <span className="text-amber-300">⏳</span> : '—'}
                    </td>
                    <td className="px-4 py-3.5 whitespace-nowrap text-xs text-slate-300 tabular-nums">
                      {fmtTime(r.created_at)}
                    </td>
                    <td className="px-4 py-3.5">
                      <button
                        onClick={(e) => { e.stopPropagation(); open(r.id) }}
                        className="rounded-lg bg-white/[0.06] px-3 py-1.5 text-xs font-semibold text-cyan-100 ring-1 ring-white/10 transition hover:bg-cyan-400/10 hover:text-cyan-50"
                      >
                        查看
                      </button>
                    </td>
                  </motion.tr>
                ))}
                {records.length === 0 && (
                  <tr><td colSpan={8} className="px-5 py-10 text-center text-slate-300">暂无记录</td></tr>
                )}
              </tbody>
            </table>
            </div>
          </div>

        </div>
        </>
        )}
      </div>
    </div>
  )
}
