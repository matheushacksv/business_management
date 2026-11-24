<script setup lang="ts">
import type { components } from '~/types/api'

type Saved = components['schemas']['SavedReportOut']
type Sheet = { title: string; subtitle: string; columns: string[]; rows: { cells: string[]; strong?: boolean }[] }

const { api, unwrap, raw, download, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('companies', 'groups', 'subgroups', 'salespeople').catch(notifyError)

const KINDS = [
  { label: 'DRE', value: 'dre', module: 'reports' },
  { label: 'Fluxo de caixa', value: 'cash_flow', module: 'reports' },
  { label: 'Análise', value: 'analysis', module: 'reports' },
  { label: 'Lançamentos', value: 'transactions', module: 'transactions' },
  { label: 'Comissões', value: 'commissions', module: 'sales' },
  { label: 'Investimentos', value: 'investments', module: 'investments' },
].filter(k => auth.can(k.module))
const kindLabel = (v: string) => KINDS.find(k => k.value === v)?.label ?? v

const year = new Date().getFullYear()
const blank = () => ({
  kind: KINDS[0]?.value ?? 'dre',
  year, view: 'monthly', month: today().slice(0, 7),
  start: `${year}-01-01`, end: today(), granularity: 'month',
  company_id: [] as number[], status: 'all', picks: [] as string[], type: undefined as string | undefined,
  contact_id: null as number | null, salesperson_id: [] as number[], commission_status: undefined as string | undefined,
  holder: undefined as string | undefined, as_of: '',
})
const f = reactive(blank())
const monthItems = monthOptions()
const yearItems = Array.from({ length: 6 }, (_, i) => ({ label: String(year - i), value: year - i }))
const pickItems = computed(() => [
  ...lookups.options.groups.value.filter(g => g.value !== 'transfer').map(g => ({ label: g.label, value: `group:${g.value}`, description: 'Grupo' })),
  ...(lookups.cache.value.subgroups ?? []).filter(s => s.group !== 'transfer')
    .map(s => ({ label: s.name, value: `subgroup:${s.id}`, description: lookups.groupLabel(s.group) })),
])
const STATUS = [{ label: 'Previsto + realizado', value: 'all' }, { label: 'Somente realizado', value: 'realized' }, { label: 'Somente previsto', value: 'planned' }]
const has = (...kinds: string[]) => kinds.includes(f.kind)

// Query of each kind = the params of the existing screen endpoints
const picked = () => ({
  group: f.picks.filter(k => k.startsWith('group:')).map(k => k.slice(6)),
  subgroup_id: f.picks.filter(k => k.startsWith('subgroup:')).map(k => Number(k.slice(9))),
})
const common = () => ({ company_id: f.company_id, status: f.status === 'all' ? undefined : f.status })
const QUERIES: Record<string, () => Record<string, unknown>> = {
  dre: () => ({ view: f.view, year: f.year, month: f.view === 'month' ? Number(f.month.slice(5)) : undefined, ...common() }),
  cash_flow: () => ({ start: f.start, end: f.end, granularity: f.granularity, ...common() }),
  analysis: () => ({ month: `${f.month}-01`, ...picked(), ...common() }),
  transactions: () => ({ date_from: f.start, date_to: f.end, ...picked(), ...common(), type: f.type, contact_id: f.contact_id ?? undefined, ordering: 'date' }),
  commissions: () => ({ month: `${f.month}-01`, salesperson_id: f.salesperson_id, company_id: f.company_id, status: f.commission_status }),
  investments: () => ({ holder: f.holder, company_id: f.company_id, as_of: f.as_of || undefined }),
}
const EXCEL: Record<string, string> = {
  dre: '/api/reports/dre/export', cash_flow: '/api/reports/cash-flow/export', analysis: '/api/reports/analysis/export',
  transactions: '/api/transaction/export', commissions: '/api/commission/export', investments: '/api/investment/export',
}
const qs = () => toSearchParams(QUERIES[f.kind]!())
const get = async (path: string) => (await raw(`${path}?${qs()}`)).json()
const valid = computed(() => !has('analysis') || f.picks.length > 0)

// PDF = the browser's print of a plain table built from the same data the screens use
const m = formatMoney
const label = (d: string) => `${MONTHS[Number(d.slice(5, 7)) - 1]}/${d.slice(0, 4)}`
async function buildSheet(): Promise<Omit<Sheet, 'subtitle'>> {
  const kind = f.kind
  if (kind === 'dre') {
    const t = await get('/api/reports/dre/table')
    return {
      title: t.title, columns: ['', ...t.columns.map((c: any) => c.label)],
      rows: t.lines.map((l: any) => ({
        strong: l.kind !== 'subgroup',
        cells: [l.label, ...l.values.map((v: any, i: number) => t.columns[i].kind === 'delta_percent' ? formatPercent(v) : m(v))],
      })),
    }
  }
  if (kind === 'cash_flow') {
    const c = await get('/api/reports/cash-flow')
    return {
      title: `Fluxo de caixa ${c.granularity === 'day' ? 'diário' : 'mensal'}`, columns: ['Período', 'Saldo inicial', 'Entradas', 'Saídas', 'Saldo final'],
      rows: c.periods.map((p: any) => ({ cells: [c.granularity === 'day' ? formatDate(p.period) : label(p.period), m(p.opening), m(p.inflow), m(p.outflow), m(p.closing)] })),
    }
  }
  if (kind === 'analysis') {
    const a = await get('/api/reports/analysis')
    return {
      title: `Análise · ${f.picks.map(k => pickItems.value.find(i => i.value === k)?.label).join(' + ')}`,
      columns: ['Mês', 'Total', 'Ano anterior', 'Variação', ...a.companies.map((c: any) => c.name)],
      rows: a.months.map((d: string, i: number) => ({
        cells: [label(d), m(a.current[i]), m(a.previous[i]), m(Number(a.current[i]) - Number(a.previous[i])), ...a.companies.map((c: any) => m(c.months[i]))],
      })),
    }
  }
  if (kind === 'transactions') {
    // ponytail: up to 40 pages (2.000 rows) in the PDF; the Excel has no limit
    const items: any[] = []
    for (let page = 1; page <= 40; page++) {
      const r = await (await raw(`/api/transaction?${qs()}&page=${page}`)).json()
      items.push(...r.items)
      if (items.length >= r.count) break
    }
    const total = items.reduce((s, t) => s + (t.type === 'inflow' ? 1 : -1) * Number(t.amount), 0)
    return {
      title: `Lançamentos ${formatDate(f.start)} a ${formatDate(f.end)}`,
      columns: ['Data', 'Empresa', 'Cliente/Fornecedor', 'Subgrupo', 'Status', 'Valor'],
      rows: [
        ...items.map(t => ({ cells: [formatDate(t.date), t.company_name, t.contact_name ?? '—', t.subgroup_name,
          t.status === 'realized' ? 'Realizado' : 'Previsto', `${t.type === 'inflow' ? '' : '−'}${m(t.amount)}`] })),
        { strong: true, cells: ['Saldo', '', '', '', '', m(total)] },
      ],
    }
  }
  if (kind === 'commissions') {
    const list = await get('/api/commission')
    return {
      title: `Comissões · ${formatMonth(f.month)}`, columns: ['Profissional', 'Tipo', 'Cliente', 'Venda', 'Comissão', 'Status'],
      rows: [
        ...list.map((c: any) => ({ cells: [c.salesperson_name, LABELS.commissionKind[c.kind] ?? c.kind, c.contact_name ?? `Venda #${c.sale_id}`,
          m(c.sale_amount), m(c.amount), c.payment_id ? `Paga ${formatDate(c.paid_on)}` : c.first_payment ? 'A pagar' : 'Prevista'] })),
        { strong: true, cells: ['Total', '', '', '', m(list.reduce((s: number, c: any) => s + Number(c.amount), 0)), ''] },
      ],
    }
  }
  const list = await get('/api/investment')
  return {
    title: `Investimentos${f.as_of ? ` em ${formatDate(f.as_of)}` : ''}`,
    columns: ['Instituição', 'Tipo', 'Titularidade', 'Empresa', 'Aplicado líquido', 'Saldo', 'Rendimento'],
    rows: [
      ...list.map((i: any) => ({ cells: [i.institution + (i.description ? ` · ${i.description}` : ''), LABELS.investmentKind[i.kind] ?? i.kind,
        LABELS.holder[i.holder] ?? i.holder, i.company_name, m(Number(i.applied) - Number(i.redeemed)), m(i.balance), m(i.yield_amount)] })),
      { strong: true, cells: ['Total', '', '', '', '', m(list.reduce((s: number, i: any) => s + Number(i.balance), 0)), m(list.reduce((s: number, i: any) => s + Number(i.yield_amount), 0))] },
    ],
  }
}

function subtitle() {
  const names = f.company_id.length
    ? lookups.options.companies.value.filter(c => f.company_id.includes(c.value as number)).map(c => c.label).join(', ')
    : 'Consolidado (todas as empresas)'
  const status = has('dre', 'cash_flow', 'analysis', 'transactions') ? ` · ${STATUS.find(s => s.value === f.status)!.label}` : ''
  return `${names}${status} · gerado em ${formatDateTime(new Date().toISOString())}`
}

const busy = ref<'' | 'excel' | 'pdf'>('')
const sheet = ref<Sheet | null>(null)
async function excel() {
  busy.value = 'excel'
  try { await download(`${EXCEL[f.kind]}?${qs()}`, 'relatorio.xlsx') } catch (e) { notifyError(e) } finally { busy.value = '' }
}
async function pdf() {
  busy.value = 'pdf'
  try {
    sheet.value = { ...(await buildSheet()), subtitle: subtitle() }
    await nextTick()
    window.print()
  } catch (e) {
    notifyError(e)
  } finally {
    busy.value = ''
  }
}

// Saved setups (per user)
const saved = ref<Saved[]>([])
const loadSaved = () => unwrap(api.GET('/api/reports/saved')).then(s => (saved.value = s)).catch(notifyError)
loadSaved()
const saving = reactive({ open: false, name: '' })
async function save() {
  try {
    const { kind, ...params } = f
    await unwrap(api.POST('/api/reports/saved', { body: { name: saving.name, kind: kind as any, params } }))
    saving.open = false
    notifySuccess('Relatório salvo')
    loadSaved()
  } catch (e) {
    notifyError(e)
  }
}
function apply(s: Saved) {
  Object.assign(f, blank(), s.params, { kind: s.kind })
}
async function removeSaved(s: Saved) {
  try {
    await unwrap(api.DELETE('/api/reports/saved/{report_id}', { params: { path: { report_id: s.id } } }))
    loadSaved()
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <AppPage title="Gerar relatório">
    <div class="grid items-start gap-4 lg:grid-cols-[1fr_18rem]">
      <SPanel title="Relatório">
        <div class="grid gap-4 sm:grid-cols-2">
          <UFormField label="Tipo" class="sm:col-span-2">
            <UTabs v-model="f.kind" :items="KINDS" :content="false" />
          </UFormField>

          <template v-if="has('dre')">
            <UFormField label="Visão">
              <USelect v-model="f.view" :items="[{ label: 'Mensal', value: 'monthly' }, { label: 'Ano × ano anterior', value: 'years' }, { label: 'Mês × anterior e ano anterior', value: 'month' }]" class="w-full" />
            </UFormField>
            <UFormField label="Ano">
              <USelect v-model="f.year" :items="yearItems" class="w-full" />
            </UFormField>
          </template>
          <UFormField v-if="has('analysis', 'commissions') || (has('dre') && f.view === 'month')" :label="has('commissions') ? 'Mês de pagamento' : 'Mês de referência'">
            <USelect v-model="f.month" :items="monthItems" class="w-full" />
          </UFormField>
          <template v-if="has('cash_flow', 'transactions')">
            <UFormField label="De">
              <UInput v-model="f.start" type="date" class="w-full" />
            </UFormField>
            <UFormField label="Até">
              <UInput v-model="f.end" type="date" class="w-full" />
            </UFormField>
          </template>
          <UFormField v-if="has('cash_flow')" label="Granularidade">
            <USelect v-model="f.granularity" :items="[{ label: 'Mensal', value: 'month' }, { label: 'Diário', value: 'day' }]" class="w-full" />
          </UFormField>
          <UFormField v-if="has('analysis', 'transactions')" label="Grupos ou subgrupos" :required="has('analysis')" class="sm:col-span-2">
            <USelectMenu v-model="f.picks" :items="pickItems" value-key="value" multiple placeholder="Todos" class="w-full" />
          </UFormField>
          <UFormField label="Empresas">
            <USelectMenu v-model="f.company_id" :items="lookups.options.companies.value" value-key="value" multiple
                         placeholder="Consolidado (todas)" class="w-full" />
          </UFormField>
          <UFormField v-if="has('dre', 'cash_flow', 'analysis', 'transactions')" label="Status">
            <USelect v-model="f.status" :items="STATUS" class="w-full" />
          </UFormField>
          <template v-if="has('transactions')">
            <UFormField label="Tipo de lançamento">
              <USelect v-model="f.type" :items="TYPE_OPTIONS" placeholder="Entradas e saídas" class="w-full" />
            </UFormField>
            <UFormField label="Cliente/Fornecedor">
              <AppContactSelect v-model="f.contact_id" placeholder="Todos" />
            </UFormField>
          </template>
          <template v-if="has('commissions')">
            <UFormField label="Profissionais">
              <USelectMenu v-model="f.salesperson_id" :items="lookups.options.salespeople.value" value-key="value" multiple placeholder="Todos" class="w-full" />
            </UFormField>
            <UFormField label="Situação">
              <USelect v-model="f.commission_status" :items="[{ label: 'Previstas', value: 'planned' }, { label: 'A pagar', value: 'pending' }, { label: 'Pagas', value: 'paid' }]"
                       placeholder="Liberadas" class="w-full" />
            </UFormField>
          </template>
          <template v-if="has('investments')">
            <UFormField label="Titularidade">
              <USelect v-model="f.holder" :items="Object.entries(LABELS.holder).map(([value, label]) => ({ label, value }))" placeholder="Todas" class="w-full" />
            </UFormField>
            <UFormField label="Posição em">
              <UInput v-model="f.as_of" type="date" class="w-full" />
            </UFormField>
          </template>
        </div>
        <div class="mt-5 flex flex-wrap gap-2">
          <UButton label="Excel" icon="i-lucide-file-spreadsheet" :loading="busy === 'excel'" :disabled="!valid" @click="excel" />
          <UButton label="PDF" icon="i-lucide-printer" color="neutral" variant="outline" :loading="busy === 'pdf'" :disabled="!valid" @click="pdf" />
          <UButton label="Salvar filtros" icon="i-lucide-bookmark-plus" color="neutral" variant="ghost" class="ms-auto"
                   @click="Object.assign(saving, { open: true, name: '' })" />
        </div>
      </SPanel>

      <SPanel title="Salvos">
        <ul v-if="saved.length" class="flex flex-col gap-1">
          <li v-for="s in saved" :key="s.id" class="flex items-center gap-2">
            <button type="button" class="flex-1 min-w-0 text-left rounded-lg px-2 py-1.5 hover:bg-elevated cursor-pointer" @click="apply(s)">
              <p class="truncate text-sm text-highlighted">{{ s.name }}</p>
              <p class="text-xs text-dimmed">{{ kindLabel(s.kind) }}</p>
            </button>
            <UButton icon="i-lucide-trash-2" color="neutral" variant="ghost" size="xs" :aria-label="`Excluir ${s.name}`" @click="removeSaved(s)" />
          </li>
        </ul>
        <p v-else class="text-sm text-muted">Nenhum</p>
      </SPanel>
    </div>

    <UModal v-model:open="saving.open" title="Salvar filtros">
      <template #body>
        <form class="flex flex-col gap-4" @submit.prevent="save">
          <UFormField label="Nome" required>
            <UInput v-model="saving.name" autofocus class="w-full" />
          </UFormField>
          <UButton type="submit" label="Salvar" :disabled="!saving.name.trim()" class="self-end" />
        </form>
      </template>
    </UModal>

    <Teleport to="body">
      <div v-if="sheet" class="s-print hidden print:block">
        <h1>{{ sheet.title }}</h1>
        <p class="sub">{{ sheet.subtitle }}</p>
        <table class="grid">
          <thead>
            <tr><th v-for="(c, i) in sheet.columns" :key="i" :class="{ num: i > 0 && /R\$|%$/.test(sheet.rows[0]?.cells[i] ?? '') }">{{ c }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in sheet.rows" :key="i" :class="{ strong: r.strong }">
              <td v-for="(c, j) in r.cells" :key="j" :class="{ num: /R\$|%$/.test(c) }">{{ c }}</td>
            </tr>
          </tbody>
        </table>
        <footer>Grupo Enriquecedor</footer>
      </div>
    </Teleport>
  </AppPage>
</template>
