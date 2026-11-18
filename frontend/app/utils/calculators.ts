// Calculators of the "Ferramentas" section. Pure functions: the defaults live here and every
// value can be changed on screen for a simulation (nothing is saved).

export interface CostLine { label: string; detail: string; value: number }

// Contract net profit

export const PROFIT_DEFAULTS = {
  gross: 0,
  taxPct: 10,
  scheduling: { on: false, value: 300 },
  advisor: { on: true, pct: 10, name: '' },
  closer: { on: true, pct: 10, name: '' },
  crm: { on: false, value: 750 },
  traffic: { on: false, months: 1, monthly: 500 },
  success: { on: false, value: 200 },
  referral: { on: false, kind: 'pct' as 'pct' | 'fixed', pct: 10, base: 'gross' as 'gross' | 'net', value: 0, name: '', description: '' },
  cac: { on: true, value: 3000 },
  // 26,46% = average fixed cost / average revenue, Jan-Oct 2026 (R$ 87.681,77 / R$ 331.314,94)
  overhead: { on: true, kind: 'pct' as 'pct' | 'fixed', pct: 26.46, value: 0 },
  others: [] as { description: string; value: number }[],
}
export type ProfitInput = typeof PROFIT_DEFAULTS

export function calcProfit(i: ProfitInput) {
  const pct = (n: number) => `${n.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`
  const gross = i.gross || 0
  const tax = gross * i.taxPct / 100
  const afterTax = gross - tax
  const lines: CostLine[] = [{ label: 'Imposto', detail: `${pct(i.taxPct)} sobre o bruto`, value: tax }]
  const add = (label: string, detail: string, value: number) => lines.push({ label, detail, value })
  const who = (name: string) => (name.trim() ? ` — ${name.trim()}` : '')

  if (i.scheduling.on) add('Comissão de agendamento', 'Valor fixo', i.scheduling.value)
  for (const [key, label] of [['advisor', 'Comissão do assessor'], ['closer', 'Comissão do closer']] as const) {
    const p = i[key]
    if (p.on) add(label + who(p.name), `${pct(p.pct)} sobre ${formatMoney(afterTax)}`, afterTax * p.pct / 100)
  }
  if (i.crm.on) add('Implementação de CRM', 'Valor fixo', i.crm.value)
  if (i.traffic.on) {
    const months = Math.max(1, Math.round(i.traffic.months))
    add('Tráfego pago', `${months} ${months === 1 ? 'mês' : 'meses'} × ${formatMoney(i.traffic.monthly)}`, months * i.traffic.monthly)
  }
  if (i.success.on) add('Sucesso do Cliente', 'Valor fixo', i.success.value)
  if (i.referral.on) {
    const r = i.referral
    if (r.kind === 'pct') {
      const base = r.base === 'gross' ? gross : afterTax
      add('Bonificação de indicação' + who(r.name), `${pct(r.pct)} sobre ${formatMoney(base)}`, base * r.pct / 100)
    } else {
      add('Bonificação de indicação' + who(r.name), r.description.trim() || 'Valor fixo', r.value)
    }
  }
  if (i.cac.on) add('CAC', 'Custo de aquisição por cliente', i.cac.value)
  if (i.overhead.on) {
    const o = i.overhead
    add('Custo operacional (estrutura)', o.kind === 'pct' ? `${pct(o.pct)} sobre o bruto` : 'Valor fixo',
      o.kind === 'pct' ? gross * o.pct / 100 : o.value)
  }
  for (const o of i.others) {
    if (o.value || o.description.trim()) add('Outro custo' + who(o.description), 'Custo avulso', o.value || 0)
  }

  const costs = lines.reduce((s, l) => s + l.value, 0)
  const net = gross - costs
  return { gross, afterTax, lines, costs, net, margin: gross > 0 ? net / gross : 0 }
}

// Contract termination

export interface Scope {
  advisory: number; success: number; booklets: number; trafficMonths: number
  onboarding: boolean; scripts: boolean; group: boolean; community: boolean; lives: boolean
  adp: boolean; crm: boolean; landing: boolean
}
const EMPTY_SCOPE: Scope = {
  advisory: 0, success: 0, booklets: 0, trafficMonths: 0,
  onboarding: false, scripts: false, group: false, community: false, lives: false, adp: false, crm: false, landing: false,
}
const plan = (s: Partial<Scope>): Scope => ({ ...EMPTY_SCOPE, onboarding: true, scripts: true, ...s })

export const PLANS: Record<string, { label: string; scope: Scope }> = {
  fast: { label: 'Fast Start', scope: plan({ advisory: 4, booklets: 4 }) },
  growth: { label: 'Growth', scope: plan({ advisory: 3, success: 3, booklets: 8, group: true, community: true, lives: true, adp: true }) },
  pro: { label: 'PRO', scope: plan({ advisory: 4, success: 4, booklets: 12, group: true, community: true, lives: true, adp: true }) },
  custom: { label: 'Personalizado', scope: { ...EMPTY_SCOPE } },
}

export const TERMINATION_DEFAULTS = {
  client: '', document: '', requester: '', requestDate: '',
  contractType: 'new' as 'new' | 'old',
  chargeFine: true, finePct: 100,
  total: 0, paid: 0,
  planKey: 'fast',
  contracted: { ...PLANS.fast!.scope },
  delivered: { ...EMPTY_SCOPE },
  prices: { adp: 997, crm: 4997, landing: 2000, trafficMonthly: 2000 },
  fines: { new: 5000, old: 4554 },  // old contract = 3 minimum wages
  weights: { advisory: 50, success: 30, scripts: 20, booklets: 0 },  // % of the variable part
}
export type TerminationInput = typeof TERMINATION_DEFAULTS

export const SCOPE_LABELS: Record<keyof Scope, string> = {
  advisory: 'Assessorias personalizadas (2h)', success: 'Reuniões Sucesso do Cliente (1h)', booklets: 'Apostilas',
  trafficMonths: 'Meses de tráfego pago', onboarding: 'Reunião de onboarding', scripts: 'Scripts e funis de vendas',
  group: 'Grupo dos Gestores no WhatsApp', community: 'Comunidade exclusiva', lives: 'Lives mensais',
  adp: 'Curso ADP (1 ano)', crm: 'Implementação de CRM', landing: 'Landing page / formulário',
}

export interface TerminationRow { label: string; delivered: boolean; value: number | null }  // null = included

export function calcTermination(i: TerminationInput) {
  const c = i.contracted
  const d = i.delivered
  const p = i.prices
  const fixed = (s: Pick<Scope, 'adp' | 'crm' | 'landing'>, months: number) =>
    (s.adp ? p.adp : 0) + (s.crm ? p.crm : 0) + (s.landing ? p.landing : 0) + months * p.trafficMonthly
  const variable = Math.max(0, i.total - fixed(c, c.trafficMonths))

  const got = {
    adp: c.adp && d.adp, crm: c.crm && d.crm, landing: c.landing && d.landing,
    trafficMonths: Math.min(d.trafficMonths, c.trafficMonths),
    advisory: Math.min(d.advisory, c.advisory), success: Math.min(d.success, c.success),
    booklets: Math.min(d.booklets, c.booklets), scripts: c.scripts && d.scripts,
  }
  const w = { advisory: i.weights.advisory / 100, success: i.weights.success / 100, scripts: i.weights.scripts / 100, booklets: i.weights.booklets / 100 }
  if (c.success === 0) {  // no customer success meetings: their weight goes to the advisories
    w.advisory += w.success
    w.success = 0
  }
  const share = (done: number, total: number) => (total > 0 ? done / total : 0)
  const part = {
    advisory: variable * w.advisory * share(got.advisory, c.advisory),
    success: variable * w.success * share(got.success, c.success),
    booklets: variable * w.booklets * share(got.booklets, c.booklets),
    scripts: got.scripts ? variable * w.scripts : 0,
  }
  const delivered = part.advisory + part.success + part.booklets + part.scripts + fixed(got, got.trafficMonths)
  const notDelivered = Math.max(0, i.total - delivered)
  const balance = Math.max(0, i.total - i.paid)
  const fine = i.chargeFine ? i.fines[i.contractType] * i.finePct / 100 : 0
  const due = Math.max(0, delivered + fine - i.paid)

  const rows: TerminationRow[] = []
  const row = (label: string, ok: boolean, value: number | null) => rows.push({ label, delivered: ok, value })
  const months = (n: number) => `${n} ${n === 1 ? 'mês' : 'meses'}`
  for (const key of ['onboarding', 'group', 'community', 'lives'] as const) if (c[key] && d[key]) row(SCOPE_LABELS[key], true, null)
  if (got.crm) row(SCOPE_LABELS.crm, true, p.crm)
  if (got.adp) row(SCOPE_LABELS.adp, true, p.adp)
  if (got.landing) row(SCOPE_LABELS.landing, true, p.landing)
  if (got.trafficMonths) row(`Tráfego pago (${months(got.trafficMonths)})`, true, got.trafficMonths * p.trafficMonthly)
  if (got.scripts) row(SCOPE_LABELS.scripts, true, part.scripts)
  if (got.advisory) row(`${SCOPE_LABELS.advisory} ${got.advisory}/${c.advisory}`, true, part.advisory)
  if (got.success) row(`${SCOPE_LABELS.success} ${got.success}/${c.success}`, true, part.success)
  if (got.booklets) row(`${SCOPE_LABELS.booklets} ${got.booklets}/${c.booklets}`, true, part.booklets)
  if (c.adp && !got.adp) row(SCOPE_LABELS.adp, false, p.adp)
  if (c.crm && !got.crm) row(SCOPE_LABELS.crm, false, p.crm)
  if (c.landing && !got.landing) row(SCOPE_LABELS.landing, false, p.landing)
  const left = (label: string, missing: number, value: number) => {
    if (missing > 0) row(`${label} (${missing} restante${missing > 1 ? 's' : ''})`, false, value)
  }
  if (c.trafficMonths > got.trafficMonths) {
    const n = c.trafficMonths - got.trafficMonths
    row(`Tráfego pago (${months(n)} restante${n > 1 ? 's' : ''})`, false, n * p.trafficMonthly)
  }
  left(SCOPE_LABELS.advisory, c.advisory - got.advisory, variable * w.advisory * share(c.advisory - got.advisory, c.advisory))
  left(SCOPE_LABELS.success, c.success - got.success, variable * w.success * share(c.success - got.success, c.success))
  if (c.scripts && !got.scripts) row(SCOPE_LABELS.scripts, false, variable * w.scripts)
  left(SCOPE_LABELS.booklets, c.booklets - got.booklets, variable * w.booklets * share(c.booklets - got.booklets, c.booklets))

  return { total: i.total, paid: i.paid, balance, variable, delivered, notDelivered, fine, due, rows }
}

export function terminationMessage(r: { due: number }, i: TerminationInput, installments: number, firstDue: string) {
  const fineText = i.chargeFine
    ? ` e a multa compensatória${i.finePct < 100 ? ` (cobrada em ${i.finePct}% do previsto em contrato)` : ''}`
    : ''
  const each = r.due / installments
  return `O valor a ser pago pelo cliente, considerando os serviços entregues${fineText}, é de ${formatMoney(r.due)} (${amountInWords(r.due)}).

O pagamento pode ser realizado em até ${installments}x de ${formatMoney(each)} (${amountInWords(each)}), com primeiro vencimento em ${firstDue ? formatDate(firstDue) : '[vencimento]'} e os demais na mesma data nos meses subsequentes.

Lembrando que, conforme estabelecido no contrato, o valor deveria ser integralmente pago em até 10 dias, mas estamos oferecendo a possibilidade de parcelamento.

Atenciosamente,
Time O Henriquecedor`
}

// Amount in words (pt-BR), up to 999.999.999,99
const UNITS = ['', 'um', 'dois', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove', 'dez', 'onze', 'doze',
  'treze', 'quatorze', 'quinze', 'dezesseis', 'dezessete', 'dezoito', 'dezenove']
const TENS = ['', '', 'vinte', 'trinta', 'quarenta', 'cinquenta', 'sessenta', 'setenta', 'oitenta', 'noventa']
const HUNDREDS = ['', 'cento', 'duzentos', 'trezentos', 'quatrocentos', 'quinhentos', 'seiscentos', 'setecentos', 'oitocentos', 'novecentos']

function upTo999(n: number): string {
  if (n === 100) return 'cem'
  const h = Math.floor(n / 100)
  const rest = n % 100
  const parts = [HUNDREDS[h]]
  if (rest < 20) parts.push(UNITS[rest])
  else parts.push([TENS[Math.floor(rest / 10)], UNITS[rest % 10]].filter(Boolean).join(' e '))
  return parts.filter(Boolean).join(' e ')
}

function integerInWords(n: number): string {
  if (n === 0) return 'zero'
  const groups: [number, string, string][] = [
    [Math.floor(n / 1e6) % 1000, 'um milhão', 'milhões'],
    [Math.floor(n / 1e3) % 1000, 'mil', 'mil'],
    [n % 1000, '', ''],
  ]
  const parts: string[] = []
  for (const [value, one, many] of groups) {
    if (!value) continue
    if (one === 'mil') parts.push(value === 1 ? 'mil' : `${upTo999(value)} mil`)
    else if (one) parts.push(value === 1 ? one : `${upTo999(value)} ${many}`)
    else parts.push(upTo999(value))
  }
  // "mil e duzentos", "mil, trezentos e vinte"
  const last = n % 1000
  const joiner = last && (last < 100 || last % 100 === 0) ? ' e ' : ', '
  return parts.length > 1 ? parts.slice(0, -1).join(', ') + joiner + parts.at(-1) : parts[0]!
}

export function amountInWords(value: number): string {
  const cents = Math.round(value * 100)
  const reais = Math.floor(cents / 100)
  const rest = cents % 100
  const parts: string[] = []
  if (reais) parts.push(`${integerInWords(reais)}${reais >= 1e6 && reais % 1e6 === 0 ? ' de' : ''} ${reais === 1 ? 'real' : 'reais'}`)
  if (rest) parts.push(`${integerInWords(rest)} ${rest === 1 ? 'centavo' : 'centavos'}`)
  return parts.join(' e ') || 'zero reais'
}
