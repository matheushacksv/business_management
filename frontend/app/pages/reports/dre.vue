<script setup lang="ts">
import type { components } from '~/types/api'

type DreTable = components['schemas']['DRETableOut']
type Line = components['schemas']['DRETableLine']
definePageMeta({ permission: ['reports', 'view'] })

const { api, unwrap, notifyError, download } = useApi()
const lookups = useLookups()
lookups.ensure('companies').catch(notifyError)
const filters = useReportFilters()

// Two ways to read it: "Resumo" (key numbers, chart, short table) and the full spreadsheet-like table
const mode = ref<'summary' | 'table'>('summary')  // remembered per browser
const modes = [
  { label: 'Resumo', value: 'summary', icon: 'i-lucide-layout-dashboard' },
  { label: 'Tabela completa', value: 'table', icon: 'i-lucide-table' },
]
onMounted(() => { if (localStorage.getItem('dre-mode') === 'table') mode.value = 'table' })
watch(mode, v => localStorage.setItem('dre-mode', v))

const now = new Date()
const currentYear = now.getFullYear()
const view = ref<'monthly' | 'years' | 'month'>('monthly')
const views = [
  { label: 'Mensal', value: 'monthly' },
  { label: 'Comparar anos', value: 'years' },
  { label: 'Comparar mês', value: 'month' },
]
const year = ref(currentYear)
const years = Array.from({ length: 6 }, (_, i) => ({ label: String(currentYear - i), value: currentYear - i }))
const month = ref(now.getMonth() + 1)
const months = MONTHS.map((label, i) => ({ label, value: i + 1 }))
const showPercent = ref(false)
const hideEmpty = ref(true)
const collapsed = ref<Set<string>>(new Set())

const table = ref<DreTable | null>(null)
const loading = ref(false)

const query = computed(() => ({
  view: view.value, year: year.value, ...(view.value === 'month' ? { month: month.value } : {}), ...filters.query.value,
}))

async function load() {
  loading.value = true
  try {
    table.value = await unwrap(api.GET('/api/reports/dre/table', { params: { query: query.value as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch([query, mode], () => { if (mode.value === 'table') load() }, { immediate: true })

function exportXlsx() {
  const params = toSearchParams({ ...query.value, percent: showPercent.value })
  download(`/api/reports/dre/export?${params}`, 'dre.xlsx').catch(notifyError)
}

// Subgroup rows belong to the group above them
const isEmpty = (line: Line) => line.values.every(v => v === null || Number(v) === 0)
const rows = computed(() => {
  let group = ''
  return (table.value?.lines ?? []).map((line) => {
    if (line.kind === 'group') group = line.key
    return { ...line, group: line.kind === 'subgroup' ? group : '' }
  }).filter(l => l.kind !== 'subgroup' || (!collapsed.value.has(l.group) && (!hideEmpty.value || !isEmpty(l))))
})

function toggle(key: string) {
  const next = new Set(collapsed.value)
  next.has(key) ? next.delete(key) : next.add(key)
  collapsed.value = next
}

const rowClass: Record<string, string> = {
  info: 'text-muted italic',
  group: 'font-medium text-highlighted bg-muted',
  subgroup: 'text-toned',
  result: 'font-semibold text-primary bg-sky-500/[0.06]',
}

const signed = (text: string, n: number) => (n > 0 ? `+${text}` : text)
function cellText(line: Line, i: number): string {
  const kind = table.value!.columns[i]!.kind
  const value = line.values[i]
  if (value === null || value === undefined) return '—'
  if (kind === 'delta') return signed(formatMoney(value), Number(value))
  if (kind === 'delta_percent') return signed(formatPercent(value), Number(value))
  return showPercent.value ? formatPercent(line.percents[i]) : formatMoney(value)
}
// Variations: green when it moves the good way for that line (costs down, revenue/results up)
function cellClass(line: Line, i: number): string {
  const kind = table.value!.columns[i]!.kind
  const n = Number(line.values[i] ?? 0)
  if (kind === 'value') return n < 0 ? 'text-error' : n === 0 ? 'text-dimmed' : ''
  if (n === 0 || !line.better) return 'text-dimmed'
  return (n > 0) === (line.better === 'up') ? 'text-success' : 'text-error'
}
</script>

<template>
  <AppPage title="DRE">
    <template #actions>
      <UButton label="Exportar" icon="i-lucide-file-down" color="neutral" variant="outline" @click="exportXlsx" />
    </template>

    <template #toolbar>
      <UTabs v-model="mode" :items="modes" :content="false" size="sm" />
      <USeparator orientation="vertical" class="h-6" />
      <UTabs v-if="mode === 'table'" v-model="view" :items="views" :content="false" size="sm" />
      <USelect v-model="year" :items="years" class="w-28" aria-label="Ano" />
      <USelect v-if="mode === 'table' && view === 'month'" v-model="month" :items="months" class="w-24" aria-label="Mês" />
      <USelectMenu v-model="filters.company_id.value" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Consolidado (todas)" class="w-56" />
      <USelect v-model="filters.status.value" :items="filters.statusOptions" class="w-52" />
      <template v-if="mode === 'table'">
        <USwitch v-model="showPercent" label="% da receita" />
        <USwitch v-model="hideEmpty" label="Ocultar zerados" />
      </template>
    </template>

    <ReportsDreSummary v-if="mode === 'summary'" :year="year" :filters="filters.query.value" />

    <div v-else class="s-panel overflow-auto" :class="{ 'opacity-60': loading }">
      <table class="w-full text-sm tabular">
        <thead class="sticky top-0 bg-(--s-solid) z-10">
          <tr class="text-xs text-muted uppercase tracking-wide">
            <th class="sticky left-0 bg-(--s-solid) px-4 py-3 text-left font-medium min-w-64">{{ table?.title ?? 'DRE' }}</th>
            <th v-for="(column, i) in table?.columns ?? []" :key="i" class="px-3 py-3 text-right font-medium whitespace-nowrap"
                :class="column.kind !== 'value' ? 'bg-muted/40' : ''">
              {{ column.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!table && loading"><td colspan="14" class="p-6"><USkeleton class="h-64 w-full" /></td></tr>
          <tr v-for="line in rows" :key="line.key" class="border-t border-muted" :class="rowClass[line.kind]">
            <td class="sticky left-0 px-4 py-2 whitespace-nowrap"
                :class="[line.kind === 'subgroup' ? 'ps-9' : '', line.kind === 'result' ? 'bg-(--s-result)' : 'bg-(--s-solid)']">
              <button v-if="line.kind === 'group'" class="inline-flex items-center gap-1.5 cursor-pointer" @click="toggle(line.key)">
                <UIcon :name="collapsed.has(line.key) ? 'i-lucide-chevron-right' : 'i-lucide-chevron-down'" class="size-4 text-dimmed" />
                {{ line.label }}
              </button>
              <span v-else>{{ line.kind === 'result' ? '= ' : '' }}{{ line.label }}</span>
            </td>
            <td v-for="(_, i) in line.values" :key="i" class="px-3 py-2 text-right whitespace-nowrap"
                :class="[cellClass(line, i), table!.columns[i]!.kind !== 'value' ? 'bg-muted/40' : '',
                         view === 'monthly' && i === line.values.length - 1 ? 'font-medium' : '']">
              {{ cellText(line, i) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="text-xs text-dimmed">
      <template v-if="mode === 'summary'">Variações comparam com o ano anterior inteiro. Com "Previsto + realizado", o ano atual inclui o que ainda está previsto. </template>
      Estornos (tipo oposto ao do grupo) subtraem do grupo. Faturamento Bruto vem das vendas e é informativo.
      <template v-if="mode === 'table' && view !== 'monthly'">Variações em verde: custo caindo ou receita/resultado subindo.</template>
    </p>
  </AppPage>
</template>
