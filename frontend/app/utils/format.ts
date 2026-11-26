// pt-BR formatting helpers (auto-imported by Nuxt)

const money = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
const percent = new Intl.NumberFormat('pt-BR', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })

export const MONTHS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

/** API decimals come as strings ("1234.50"); never use them in float math beyond display/charts. */
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return money.format(Number(value))
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return percent.format(Number(value))
}

/** "2026-01-31" -> "31/01/2026" without timezone shifts (dates are calendar dates). */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const [y, m, d] = value.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

/** Month select items: 3 ahead to ~2 years back, "11/2026" -> "2026-11" (native type="month" isn't supported everywhere) */
export function monthOptions() {
  const now = new Date()
  return Array.from({ length: 30 }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() + 3 - i, 1)
    const m = String(d.getMonth() + 1).padStart(2, '0')
    return { label: `${m}/${d.getFullYear()}`, value: `${d.getFullYear()}-${m}` }
  })
}

/** "2026-03-01" -> "Mar/2026" */
export function formatMonth(value: string): string {
  const [y, m] = value.split('-')
  return `${MONTHS[Number(m) - 1]}/${y}`
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export function today(): string {
  return iso(new Date())
}

export function addDays(date: string, days: number): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  return iso(new Date(y, m - 1, d + days))
}

// Same day next month, clamped to its last day (31/01 -> 28/02)
export function nextMonth(date: string): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  return iso(new Date(y, m, Math.min(d, new Date(y, m + 1, 0).getDate())))
}

export const LABELS = {
  type: { inflow: 'Entrada', outflow: 'Saída' } as Record<string, string>,
  status: { planned: 'Previsto', realized: 'Realizado' } as Record<string, string>,
  saleStatus: { active: 'Ativa', completed: 'Concluída', canceled: 'Cancelada' } as Record<string, string>,
  role: {
    admin: 'Administrador', finance: 'Financeiro', legal: 'Jurídico', accountant: 'Contador', manager: 'Gestor',
  } as Record<string, string>,
  invoiceKind: { service: 'NF de Serviço', product: 'NF de Produto' } as Record<string, string>,
  action: { insert: 'Criou', update: 'Alterou', delete: 'Excluiu' } as Record<string, string>,
  // Legal kanban columns, in order (mirrors apps.legal.models.CaseStage)
  commissionKind: {
    seller: 'Vendedor', advisor: 'Assessor', scheduling: 'Agendamento', crm: 'Implementação de CRM', other: 'Outro',
  } as Record<string, string>,
  investmentKind: {
    cdb: 'CDB', lci_lca: 'LCI/LCA', treasury: 'Tesouro Direto', fund: 'Fundo', stocks: 'Ações', savings: 'Poupança', other: 'Outro',
  } as Record<string, string>,
  holder: { company: 'Empresa', personal: 'Pessoal' } as Record<string, string>,
  movementKind: { application: 'Aplicação', redemption: 'Resgate', balance: 'Saldo atualizado' } as Record<string, string>,
}

export const DUNNING_LABELS = {
  activityKind: { message: 'Mensagem', call: 'Ligação', task: 'Tarefa' } as Record<string, string>,
  activityIcon: { message: 'i-lucide-message-circle', call: 'i-lucide-phone', task: 'i-lucide-square-check' } as Record<string, string>,
  outcome: { open: 'Em aberto', resolved: 'Resolvido', legal: 'Jurídico', dismissed: 'Excluído' } as Record<string, string>,
}

/** Days between a due date and today */
export function daysLate(date: string): number {
  return Math.round((Date.parse(today()) - Date.parse(date)) / 86_400_000)
}

/** Fills the cadence message placeholders with the card values */
export function fillTemplate(text: string, card: {
  contact_name: string; company_name: string; overdue_amount: string | number; overdue_count: number; overdue_since: string
}): string {
  const values: Record<string, string> = {
    cliente: card.contact_name, empresa: card.company_name, valor: formatMoney(card.overdue_amount),
    parcelas: String(card.overdue_count), vencimento: formatDate(card.overdue_since), dias: String(daysLate(card.overdue_since)),
  }
  return text.replace(/\{(\w+)\}/g, (m, key: string) => values[key] ?? m)
}

/** Sellers and advisors earn a % of the sale after tax; the other kinds a fixed value (same rule as the backend). */
export const LEGAL_FEE_RATE = 0.2  // lawyer fees: always 20% of what the customer pays on an agreement

export const PERCENT_COMMISSION_KINDS = ['seller', 'advisor']

export const TYPE_OPTIONS = [
  { label: 'Entrada', value: 'inflow' },
  { label: 'Saída', value: 'outflow' },
]
export const STATUS_OPTIONS = [
  { label: 'Previsto', value: 'planned' },
  { label: 'Realizado', value: 'realized' },
]
export const ROLE_OPTIONS = Object.entries(LABELS.role).map(([value, label]) => ({ value, label }))

/** Same rule as the backend NATURAL_TYPE: revenue groups are inflows, costs/expenses outflows. */
export const INFLOW_GROUPS = ['operating_revenue', 'non_operating_revenue']
export function naturalType(group?: string | null): 'inflow' | 'outflow' | null {
  if (!group) return null
  return INFLOW_GROUPS.includes(group) ? 'inflow' : 'outflow'
}


/** Query object (arrays = repeated keys, like the API filters) -> URLSearchParams. */
export function toSearchParams(query: Record<string, unknown>): URLSearchParams {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    for (const v of ([] as unknown[]).concat(value)) {
      if (v !== undefined && v !== null && v !== '') params.append(key, String(v))
    }
  }
  return params
}

/** "12345678000190" -> "12.345.678/0001-90"; "12345678901" -> "123.456.789-01"; anything else as is. */
export function formatDocument(value?: string | null): string {
  if (!value) return ''
  if (value.length === 14) return value.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5')
  if (value.length === 11) return value.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4')
  return value
}
