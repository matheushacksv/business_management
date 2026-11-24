<script setup lang="ts">
import type { components } from '~/types/api'

type Analysis = components['schemas']['AnalysisOut']
definePageMeta({ permission: ['reports', 'view'] })

const { api, unwrap, notifyError } = useApi()
const lookups = useLookups()
lookups.ensure('companies', 'groups', 'subgroups').catch(notifyError)
const filters = useReportFilters()
filters.status.value = 'realized'

// "group:<value>" or "subgroup:<id>", several summed together
const picked = ref<string[]>(['group:operating_revenue'])
const pickItems = computed(() => [
  ...lookups.options.groups.value.filter(g => g.value !== 'transfer').map(g => ({ label: g.label, value: `group:${g.value}`, description: 'Grupo' })),
  ...(lookups.cache.value.subgroups ?? []).filter(s => s.group !== 'transfer')
    .map(s => ({ label: s.name, value: `subgroup:${s.id}`, description: lookups.groupLabel(s.group) })),
])
const month = ref(today().slice(0, 7))
const monthItems = monthOptions()
const view = ref<'total' | 'company'>('total')
const byCompany = computed(() => view.value === 'company')

const data = ref<Analysis | null>(null)
const loading = ref(false)
const query = computed(() => ({
  month: `${month.value}-01`, ...filters.query.value,
  group: picked.value.filter(k => k.startsWith('group:')).map(k => k.slice(6)),
  subgroup_id: picked.value.filter(k => k.startsWith('subgroup:')).map(k => Number(k.slice(9))),
}))
async function load() {
  if (!picked.value.length) { data.value = null; return }
  loading.value = true
  try {
    data.value = await unwrap(api.GET('/api/reports/analysis', { params: { query: query.value as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(query, load, { immediate: true, deep: true })

const label = (d: string) => `${MONTHS[Number(d.slice(5, 7)) - 1]}/${d.slice(2, 4)}`
const n = (list?: (string | number)[]) => (list ?? []).map(Number)

// Comparison cards: value vs base, colored by better/worse (costs going up is worse)
function compare(value: number, base: number) {
  const delta = value - base
  const pct = base ? (delta / Math.abs(base)) * 100 : null
  const better = data.value?.kind === 'cost' ? delta < 0 : delta > 0
  return {
    value: formatMoney(value),
    hint: `${formatMoney(base)} · ${delta >= 0 ? '+' : ''}${formatMoney(delta)}${pct == null ? '' : ` (${pct >= 0 ? '+' : ''}${pct.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%)`}`,
    tone: (!delta || data.value?.kind === 'mixed' ? 'default' : better ? 'success' : 'error') as 'default' | 'success' | 'error',
  }
}
const cards = computed(() => {
  if (!data.value) return []
  const cur = n(data.value.current)
  const prev = n(data.value.previous)
  const ytdStart = 11 - (Number(month.value.slice(5, 7)) - 1)  // index of January in the 12 months
  const sum = (list: number[]) => list.slice(ytdStart).reduce((s, v) => s + v, 0)
  const ref = label(data.value.months[11]!)
  return [
    { label: `${ref} × mês anterior`, icon: 'i-lucide-calendar', ...compare(cur[11]!, cur[10]!) },
    { label: `${ref} × ano anterior`, icon: 'i-lucide-calendar-range', ...compare(cur[11]!, prev[11]!) },
    { label: `Acumulado ${month.value.slice(0, 4)} × ${Number(month.value.slice(0, 4)) - 1}`, icon: 'i-lucide-sigma', ...compare(sum(cur), sum(prev)) },
  ]
})

const PALETTE = ['#2f9a53', '#38bdf8', '#f59e0b', '#a78bfa', '#f87171', '#14b8a6']
const chart = computed(() => {
  const d = data.value
  if (!d) return { labels: [], series: [] }
  const labels = d.months.map(label)
  if (byCompany.value) {
    return { labels, series: d.companies.map((c, i) => ({ label: c.name, data: n(c.months), color: PALETTE[i % PALETTE.length]!, type: 'bar' as const })) }
  }
  return { labels, series: [
    { label: 'Últimos 12 meses', data: n(d.current), color: '#2f9a53', type: 'bar' as const },
    { label: 'Ano anterior', data: n(d.previous), color: '#94a3b8', type: 'line' as const },
  ] }
})
</script>

<template>
  <AppPage title="Análise">
    <template #toolbar>
      <USelectMenu v-model="picked" :items="pickItems" value-key="value" multiple placeholder="Grupos ou subgrupos" class="w-80" />
      <USelect v-model="month" :items="monthItems" class="w-32" aria-label="Mês de referência" />
      <USelectMenu v-model="filters.company_id.value" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Consolidado (todas)" class="w-56" />
      <USelect v-model="filters.status.value" :items="filters.statusOptions" class="w-52" />
    </template>

    <template v-if="data">
      <div class="grid gap-4 sm:grid-cols-3">
        <SStat v-for="c in cards" :key="c.label" :label="c.label" :value="c.value" :hint="c.hint" :tone="c.tone"
               :icon="c.icon" :loading="loading && !data" />
      </div>

      <SPanel title="Evolução">
        <template #actions>
          <UTabs v-model="view" :items="[{ label: 'Total', value: 'total' }, { label: 'Por empresa', value: 'company' }]" :content="false" size="sm" />
        </template>
        <SChart type="bar" :labels="chart.labels" :series="chart.series" money :stacked="byCompany" :height="320"
                :class="{ 'opacity-50 transition-opacity': loading }" />
      </SPanel>

      <div v-if="byCompany" class="s-panel overflow-auto">
        <table class="w-full text-sm">
          <thead class="text-xs text-muted">
            <tr>
              <th class="px-3 py-2 text-left font-medium">Empresa</th>
              <th v-for="m in data.months" :key="m" class="px-3 py-2 text-right font-medium whitespace-nowrap">{{ label(m) }}</th>
              <th class="px-3 py-2 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-muted">
            <tr v-for="c in data.companies" :key="c.id">
              <td class="px-3 py-1.5 text-highlighted whitespace-nowrap">{{ c.name }}</td>
              <td v-for="(v, i) in c.months" :key="i" class="px-3 py-1.5 text-right tabular whitespace-nowrap">{{ formatMoney(v) }}</td>
              <td class="px-3 py-1.5 text-right tabular font-semibold whitespace-nowrap">{{ formatMoney(n(c.months).reduce((s, v) => s + v, 0)) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </AppPage>
</template>
