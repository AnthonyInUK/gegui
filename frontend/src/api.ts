export interface Violation {
  expert?: string
  rule_id?: string
  rule_name?: string
  law_article?: string
  law_quote?: string
  evidence?: string
  location?: string
  suggestion?: string
}

export interface ReviewRecord {
  id: string
  scene_id: string
  material_text: string
  image_paths: string[]
  final_verdict: 'VIOLATION' | 'PASS' | 'NEEDS_HUMAN'
  confidence: number
  needs_human: boolean
  violations: Violation[]
  reasoning_chain: string[]
  human_decision: string | null
  human_notes: string | null
  tokens: number
  latency_ms: number
  created_at: string
}

export interface Stats {
  total: number
  by_verdict: Record<string, number>
  needs_human: number
  total_tokens: number
}

export interface CrossborderDemoReport {
  demo: {
    name: string
    platform: string
    market: string
    workflow_id: string
    seller_id: string
  }
  input_summary?: Record<string, any>
  stages: Record<string, any>
  gate_summary: {
    total_actions: number
    decision_counts: Record<string, number>
    blocked_or_human_review_actions: Array<{
      action_type?: string
      gate_decision?: string
      reasons?: string[]
    }>
  }
  audit_summary: Record<string, string | string[]>
  final_summary: {
    product_research_decision: string
    listing_compliance_decision: string
    ads_decision: string
    customer_service_decision: string
    ready_for_publish: boolean
    human_review_required: boolean
  }
}

export interface DemandSignal {
  kind: string
  provider: string
  score: number
  provenance: string
  confidence: number
  evidence: string
  detail: Record<string, any>
}

export interface OpportunityScore {
  keyword: string
  score: number
  rank: number
  signals: DemandSignal[]
  discovery_source: string
  contribution: Record<string, number>
  missing_signals: string[]
  rationale: string[]
}

export interface OpportunityReport {
  seed_keyword: string
  opportunities: OpportunityScore[]
  selected_keyword: string | null
  selected_opportunity?: OpportunityScore
  intake_report: {
    raw_meta_rows: number
    raw_review_rows: number
    matched_items: number
    generated_competitors: number
    generated_pain_points: number
    price_coverage: number
    inferred_fields: string[]
    warnings: string[]
  } | null
  product?: Record<string, any>
  competitors?: Array<Record<string, any>>
  pain_points?: Array<Record<string, any>>
  improvement_spec?: ImprovementSpec
  research: {
    decision: string
    opportunity_level: string
    score: number
    confidence: number
    score_breakdown: Record<string, number>
    candidate_ranking: Array<Record<string, any>>
    issues: Array<Record<string, any>>
    suggestions: string[]
    human_review_required: boolean
  } | null
  handoff: string[]
}

export interface ImprovementRequirement {
  pain_topic: string
  requirement: string
  priority: string
  frequency: number
  severity: number
  evidence_quote: string
  source_asins: string[]
}

export interface ImprovementSpec {
  product_title: string
  keyword: string
  requirements: ImprovementRequirement[]
  differentiation_bullets: string[]
  emphasis_keywords: string[]
  honesty_note: string
}

export interface CompareNiche {
  keyword: string
  decision: string | null
  score: number | null
  confidence: number | null
  score_breakdown: Record<string, number>
  price_coverage: number | null
  human_review_required: boolean | null
  top_pains: string[]
  competitors: number
  error: string | null
}

export interface CompareResult {
  keywords: string[]
  niches: CompareNiche[]
  comparison: {
    dimensions: string[]
    best_per_dim: Record<string, string | null>
    winner: string | null
    radar: { dimensions: string[]; series: Array<{ keyword: string; values: number[] }> }
    notes: string[]
  }
}

export interface ProfitInputs {
  sale_price: number
  unit_cost: number
  inbound_shipping_per_unit?: number
  referral_fee_pct?: number
  fba_fee?: number
  storage_fee_per_unit?: number
  ads_acos?: number
  return_rate?: number
  other_per_unit?: number
}

export interface ProfitResult {
  inputs: ProfitInputs
  landed_cost: number
  breakdown: Record<string, number>
  net_profit: number
  net_margin: number
  roi: number | null
  breakeven_price: number | null
  breakeven_acos: number | null
  verdict: string
  note: string
}

export interface SweepPoint {
  x: number
  variable: string
  net_profit: number
  net_margin: number
  verdict: string
}

export interface PriceQuote {
  asin: string
  price: number | null
  currency: string
  provenance: string
  source: string
  fetched_at: string
}

export interface InjectPricesResult {
  keyword: string
  price_quotes: PriceQuote[]
  coverage_before: number
  coverage_after: number
  target_price_before?: number | null
  target_price_after?: number | null
  unit_cost_used?: number | null
  before: {
    decision: string
    confidence: number
    profitability: number
    human_review_required: boolean
  }
  after: {
    decision: string
    confidence: number
    profitability: number
    human_review_required: boolean
  }
}

export interface WorkflowResult {
  workflow_status: string
  workflow: {
    status?: string
    listing?: {
      title?: string
      bullets?: string[]
      search_terms?: string[]
    } | null
    compliance?: {
      decision?: string
      risk_level?: string
      issues?: Array<Record<string, any>>
    }
    stage_results?: Array<{
      name: string
      mode: string
      status?: string
      decision: string
      summary?: string
      issues?: Array<Record<string, any>>
    }>
    notes?: string[]
  } | null
}

export interface ReviewRunResult {
  record_id: string
  mode: string
  record: ReviewRecord
  error?: string
  message?: string
}

export interface ReviewUploadResult {
  file_path: string
  image_url: string
  filename: string
  size: number
  error?: string
  message?: string
}

const j = (r: Response) => r.json()

export const api = {
  stats: (): Promise<Stats> => fetch('/api/stats').then(j),
  records: (): Promise<ReviewRecord[]> => fetch('/api/records').then(j),
  record: (id: string): Promise<ReviewRecord> => fetch(`/api/records/${id}`).then(j),
  feedback: (id: string, decision: 'APPROVE' | 'REJECT') =>
    fetch(`/api/records/${id}/feedback?decision=${decision}`, { method: 'POST' }).then(j),
  runReview: (payload: { text?: string; image_path?: string; case_id?: string; offline_fallback?: boolean }): Promise<ReviewRunResult> =>
    fetch('/api/review/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(j),
  uploadReviewImage: (file: File): Promise<ReviewUploadResult> => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/review/upload', { method: 'POST', body: form }).then(j)
  },
  crossborderDemo: (): Promise<CrossborderDemoReport> => fetch('/api/crossborder/demo-result').then(j),
  runCrossborderDemo: (runCompliance = false): Promise<CrossborderDemoReport> =>
    fetch('/api/crossborder/run-demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_compliance: runCompliance }),
    }).then(j),
  opportunityResult: (): Promise<OpportunityReport> => fetch('/api/opportunity/result').then(j),
  runOpportunity: (seed: string, targetPrice?: number): Promise<OpportunityReport> =>
    fetch('/api/opportunity/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed_keyword: seed, target_price: targetPrice }),
    }).then(j),
  deepDive: (keyword: string, targetPrice?: number): Promise<Partial<OpportunityReport>> =>
    fetch('/api/opportunity/deep-dive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword, target_price: targetPrice }),
    }).then(j),
  injectPrices: (keyword: string, unitCost?: number): Promise<InjectPricesResult> =>
    fetch('/api/opportunity/inject-prices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword, unit_cost: unitCost }),
    }).then(j),
  compare: (keywords: string[]): Promise<CompareResult> =>
    fetch('/api/opportunity/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keywords }),
    }).then(j),
  simulate: (inputs: ProfitInputs): Promise<ProfitResult> =>
    fetch('/api/pricing/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(inputs),
    }).then(j),
  sweep: (inputs: ProfitInputs, variable: string, start: number, stop: number, steps = 20): Promise<SweepPoint[]> =>
    fetch('/api/pricing/sweep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs, variable, start, stop, steps }),
    }).then(j),
  toWorkflow: (seed: string): Promise<WorkflowResult> =>
    fetch('/api/opportunity/to-workflow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed_keyword: seed }),
    }).then(j),
}
