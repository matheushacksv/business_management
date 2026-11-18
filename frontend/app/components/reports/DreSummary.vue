<script setup lang="ts">
import type { components } from '~/types/api'

// "Resumo" view of the DRE: key numbers, the year in a chart and a short table that reads
// top-down like a sum. Same API as the full table (views "monthly" and "years").
type Table = components['schemas']['DRETableOut']
type Line = components['schemas']['DRETableLine']
const props = defineProps<{ year: number; filters: Record<string, unknown> }>()

const { api, unwrap, notifyError } = useApi()
const monthly = ref<Table | null>(null)
const years = ref<Table | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const base = { year: props.year, ...props.filters }
    ;[monthly.value, years.value] = await Promise.all([
      unwrap(api.GET('/api/reports/dre/table', { params: { query: { ...base, view: 'monthly' } as any } })),
      unwrap(api.GET('/api/reports/dre/table', { params: { query: { ...base, view: 'years' } as any } })),
    ])
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(() => [props.year, props.filters], load, { immediate: true, deep: true })

const num = (v: unknown) => Number(v ?? 0)
const find = (t: Table | null, key: string) => t?.lines.find(l => l.key === key)
const COSTS = ['group:variable_costs', 'group:fixed_costs', 'group:non_operating_expenses']

// Cards: this year x last year
interface Card { label: string; value: number; previous: number; share?: number | null; better: 'up' | 'down' }
const cards = computed<Card[]>(() => {
  const y = years.value
  if (!y) return []
  const pick = (key: string) => {
    const l = find(y, key)
    return { value: num(l?.values[1]), previous: num(l?.values[0]), share: l?.percents[1] != null ? num(l.percents[1]) : null }
  }
  const costs = COSTS.map(pick).reduce((a, c) => ({ value: a.value + c.value, previous: a.previous + c.previous }), { value: 0, previous: 0 })
  const revenue = pick('group:operating_revenue')
  return [
    { label: 'Receita operacional', ...revenue, share: null, better: 'up' },
    { label: 'Custos e despesas', ...costs, share: revenue.value ? costs.value / revenue.value : null, better: 'down' },
    { label: 'Margem de contribuição', ...pick('contribution_margin'), better: 'up' },
    { label: 'Margem de lucro', ...pick('profit_margin'), better: 'up' },
    { label: 'Resultado líquido', ...pick('net_result'), better: 'up' },
  ]
})
function variation(card: Card) {
  if (!card.previous) return null
  const pct = (card.value - card.previous) / Math.abs(card.previous)
  const good = pct === 0 ? null : (pct > 0) === (card.better === 'up')
  return { text: `${pct > 0 ? '▲' : pct < 0 ? '▼' : ''} ${formatPercent(Math.abs(pct))}`, good }
}

// Chart: revenue x costs per month + net result
const chart = computed(() => {
  const m = monthly.value
  const months = (key: string) => (find(m, key)?.values ?? []).slice(0, 12).map(num)
  const costs = MONTHS.map((_, i) => COSTS.reduce((s, key) => s + (months(key)[i] ?? 0), 0))
  return {
    labels: MONTHS,
    series: [
      { label: 'Receita operacional', data: months('group:operating_revenue'), color: '#38bdf8', type: 'bar' as const },
      { label: 'Custos e despesas', data: costs, color: '#f87171', type: 'bar' as const },
      { label: 'Resultado líquido', data: months('net_result'), color: '#34d399', type: 'line' as const },
    ],
  }
})

// Short table: groups and results only, subgroups on demand
const LAYOUT: { key: string; sign: string; explain?: string }[] = [
  { key: 'group:operating_revenue', sign: '' },
  { key: 'group:variable_costs', sign: '(−)' },
  { key: 'contribution_margin', sign: '=', explain: 'Receita operacional − custos variáveis: quanto sobra das vendas para pagar a estrutura.' },
  { key: 'group:fixed_costs', sign: '(−)' },
  { key: 'profit_margin', sign: '=', explain: 'Margem de contribuição − custos fixos: o resultado da operação.' },
  { key: 'group:non_operating_revenue', sign: '(+)' },
  { key: 'group:non_operating_expenses', sign: '(−)' },
  { key: 'net_result', sign: '=', explain: 'Margem de lucro + receitas − despesas não operacionais: o que sobrou no fim.' },
]
const open = ref<Set<string>>(new Set())
function toggle(key: string) {
  const next = new Set(open.value)
  next.has(key) ? next.delete(key) : next.add(key)
  open.value = next
}
const expandAll = computed(() => open.value.size > 0)

interface Row { line: Line; sign: string; explain?: string; child: boolean; group: string }
const rows = computed<Row[]>(() => {
  const lines = monthly.value?.lines ?? []
  const out: Row[] = []
  for (const item of LAYOUT) {
    const index = lines.findIndex(l => l.key === item.key)
    if (index < 0) continue
    out.push({ line: lines[index]!, sign: item.sign, explain: item.explain, child: false, group: item.key })
    if (!open.value.has(item.key)) continue
    for (const sub of lines.slice(index + 1)) {
      if (sub.kind !== 'subgroup') break
      if (sub.values.some(v => num(v) !== 0)) out.push({ line: sub, sign: '', child: true, group: item.key })
    }
  }
  return out
})
const groupKeys = LAYOUT.filter(l => l.key.startsWith('group:')).map(l => l.key)

// Columns: Jan..Dez + Total; current month highlighted, future months marked as forecast
const now = new Date()
const isCurrentYear = computed(() => props.year === now.getFullYear())
const column = (i: number) => ({
  current: isCurrentYear.value && i === now.getMonth(),
  future: (isCurrentYear.value && i > now.getMonth() && i < 12) || props.year > now.getFullYear(),
})
const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', style: 'currency', currency: 'BRL', maximumFractionDigits: 1 })
const short = (v: unknown) => (num(v) === 0 ? '—' : compact.format(num(v)))

// Click a value -> the transactions behind it
function drill(row: Row, i: number) {
  if (row.line.kind === 'result' || num(row.line.values[i]) === 0) return
  const [kind, id] = row.line.key.split(':')
  const y = props.year
  const range = i < 12
    ? { date_from: `${y}-${String(i + 1).padStart(2, '0')}-01`, date_to: new Date(y, i + 1, 0).toLocaleDateString('sv-SE') }
    : { date_from: `${y}-01-01`, date_to: `${y}-12-31` }
  navigateTo({ path: '/transactions', query: {
    ...range, ...(kind === 'group' ? { group: id } : { subgroup_id: id }),
    ...(props.filters.company_id ? { company_id: props.filters.company_id as any } : {}),
    ...(props.filters.status ? { status: props.filters.status as any } : {}),
  } })
}
</script>

<template>
  <div class="flex flex-col gap-4 sm:gap-6" :class="{ 'opacity-60': loading }">
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <template v-if="!cards.length">
        <USkeleton v-for="i in 5" :key="i" class="h-32" />
      </template>
      <div v-for="card in cards" :key="card.label" class="s-panel p-4">
        <p class="text-sm text-muted">{{ card.label }}</p>
        <p class="mt-1 font-display text-2xl font-semibold tracking-tight tabular"
           :class="card.label === 'Resultado líquido' && card.value < 0 ? 'text-error' : 'text-highlighted'">
          {{ formatMoney(card.value) }}
        </p>
        <div class="mt-1 flex flex-wrap items-center gap-x-2 text-xs">
          <span v-if="card.share != null" class="text-toned">{{ formatPercent(card.share) }} da receita</span>
          <span v-if="variation(card)" :class="variation(card)!.good === null ? 'text-dimmed' : variation(card)!.good ? 'text-success' : 'text-error'">
            {{ variation(card)!.text }} vs {{ year - 1 }}
          </span>
        </div>
      </div>
    </div>

    <SPanel title="O ano mês a mês" description="Barras: receita × custos e despesas. Linha: resultado líquido.">
      <SChart type="bar" :labels="chart.labels" :series="chart.series" money :height="280" />
    </SPanel>

    <div class="s-panel overflow-auto">
      <div class="flex items-center justify-between gap-2 px-4 pt-3">
        <p class="text-xs text-dimmed">Clique num grupo para abrir os subgrupos; clique num valor para ver os lançamentos.</p>
        <UButton :label="expandAll ? 'Recolher tudo' : 'Expandir tudo'" size="xs" color="neutral" variant="ghost"
                 :icon="expandAll ? 'i-lucide-chevrons-down-up' : 'i-lucide-chevrons-up-down'"
                 @click="open = expandAll ? new Set() : new Set(groupKeys)" />
      </div>
      <table class="w-full text-sm tabular">
        <thead>
          <tr class="text-xs text-muted">
            <th class="sticky left-0 bg-(--s-solid) px-4 py-2 text-left font-medium min-w-60">{{ year }}</th>
            <th v-for="(m, i) in [...MONTHS, 'Total']" :key="m" class="px-2 py-2 text-right font-medium whitespace-nowrap"
                :class="{ 'text-primary': column(i).current, 'text-dimmed': column(i).future, 'border-l border-default': i === 12 }">
              {{ m }}<span v-if="column(i).future" class="block text-[10px] font-normal">previsto</span>
            </th>
            <th class="px-3 py-2 text-right font-medium whitespace-nowrap">% receita</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.line.key" class="border-t border-muted"
              :class="row.line.kind === 'result' ? 'font-semibold bg-(--s-result)' : row.child ? 'text-toned' : 'text-highlighted'">
            <td class="sticky left-0 px-4 py-2 whitespace-nowrap" :class="[row.child ? 'ps-10 text-xs' : '', row.line.kind === 'result' ? 'bg-(--s-result)' : 'bg-(--s-solid)']">
              <button v-if="row.line.kind === 'group'" class="inline-flex items-center gap-1.5 cursor-pointer" @click="toggle(row.line.key)">
                <UIcon :name="open.has(row.line.key) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'" class="size-4 text-dimmed" />
                <span v-if="row.sign" class="w-6 text-dimmed">{{ row.sign }}</span>{{ row.line.label }}
              </button>
              <span v-else class="inline-flex items-center gap-1.5">
                <span v-if="row.sign" class="w-6 text-primary">{{ row.sign }}</span>{{ row.line.label }}
                <UTooltip v-if="row.explain" :text="row.explain">
                  <UIcon name="i-lucide-info" class="size-3.5 text-dimmed" />
                </UTooltip>
              </span>
            </td>
            <td v-for="(value, i) in row.line.values" :key="i" :title="formatMoney(value)"
                class="px-2 py-2 text-right whitespace-nowrap"
                :class="[num(value) < 0 ? 'text-error' : num(value) === 0 ? 'text-dimmed' : '',
                         column(i).current ? 'bg-primary/5' : '', column(i).future ? 'opacity-60' : '',
                         i === 12 ? 'border-l border-default font-medium' : '',
                         row.line.kind !== 'result' && num(value) !== 0 ? 'cursor-pointer hover:text-primary hover:underline' : '']"
                @click="drill(row, i)">
              {{ short(value) }}
            </td>
            <td class="px-3 py-2 text-right text-xs text-muted whitespace-nowrap">
              {{ row.line.percents[12] != null ? formatPercent(row.line.percents[12]) : '' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
