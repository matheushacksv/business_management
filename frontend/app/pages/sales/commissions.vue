<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Commission = components['schemas']['CommissionOut']
definePageMeta({ permission: ['sales', 'view'] })

const { api, unwrap, download, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('companies', 'salespeople', 'subgroups').catch(notifyError)
const UBadge = resolveComponent('UBadge')

// Month the commissions are due (sales of the previous month)
const filters = reactive({
  month: today().slice(0, 7),
  salesperson_id: [] as number[],
  company_id: [] as number[],
  status: undefined as 'planned' | 'pending' | 'paid' | undefined,
})
const monthItems = monthOptions()
const query = computed(() => {
  const q: Record<string, unknown> = {}
  if (filters.month) q.month = `${filters.month}-01`
  for (const key of ['salesperson_id', 'company_id', 'status'] as const) {
    const v = filters[key]
    if (Array.isArray(v) ? v.length : v) q[key] = v
  }
  return q
})

const items = ref<Commission[]>([])
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    items.value = await unwrap(api.GET('/api/commission', { params: { query: query.value as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(query, load, { immediate: true })

// Due month: after the customer's first payment (default) or after the sale
const due = ref<'payment' | 'sale'>('payment')
unwrap(api.GET('/api/commission/config')).then(c => (due.value = c.commission_due)).catch(notifyError)
async function setDue(value: 'payment' | 'sale') {
  try {
    due.value = (await unwrap(api.PUT('/api/commission/config', { body: { commission_due: value } }))).commission_due
    load()
  } catch (e) {
    notifyError(e)
  }
}

const sum = (list: Commission[]) => list.reduce((s, c) => s + Number(c.amount), 0)
const pending = computed(() => items.value.filter(c => !c.payment_id))
const paid = computed(() => items.value.filter(c => c.payment_id))
const salesMonth = computed(() => {
  if (!filters.month || filters.status === 'planned') return ''
  const [y, m] = filters.month.split('-').map(Number)
  const d = new Date(y!, m! - 2, 1)
  return `${MONTHS[d.getMonth()]}/${d.getFullYear()}`
})
const byPerson = computed(() => {
  const map = new Map<number, { id: number; name: string; pending: number; paid: number }>()
  for (const c of items.value) {
    const row = map.get(c.salesperson_id) ?? { id: c.salesperson_id, name: c.salesperson_name, pending: 0, paid: 0 }
    row[c.payment_id ? 'paid' : 'pending'] += Number(c.amount)
    map.set(c.salesperson_id, row)
  }
  return [...map.values()]
})

const selection = useSelection<Commission>(() => items.value)
const canPay = computed(() => auth.can('sales', 'change') && auth.can('transactions', 'create'))
const toPay = computed(() => selection.rows.value.filter(c => !c.payment_id && c.first_payment))

const columns = computed<TableColumn<Commission>[]>(() => [
  ...(canPay.value ? [selection.column] : []),
  { accessorKey: 'salesperson_name', header: 'Profissional' },
  { accessorKey: 'kind', header: 'Tipo', cell: ({ row }) => h('div', [
    h('p', LABELS.commissionKind[row.original.kind]),
    row.original.description ? h('p', { class: 'text-xs text-dimmed' }, row.original.description) : null,
  ]) },
  { accessorKey: 'contact_name', header: 'Cliente', cell: ({ row }) => h('div', [
    h('p', { class: 'truncate max-w-64 text-highlighted' }, row.original.contact_name ?? `Venda #${row.original.sale_id}`),
    h('p', { class: 'text-xs text-dimmed' }, [
      `${formatDate(row.original.sale_date)} · ${row.original.company_name}`,
      row.original.first_payment && ` · 1º pgto ${formatDate(row.original.first_payment)}`,
    ].filter(Boolean).join('')),
  ]) },
  { accessorKey: 'sale_amount', header: () => h('span', { class: 'block text-right' }, 'Venda'),
    cell: ({ row }) => h('p', { class: 'text-right tabular' }, formatMoney(row.original.sale_amount)) },
  { id: 'rule', header: () => h('span', { class: 'block text-right' }, 'Regra'),
    cell: ({ row }) => h('p', { class: 'text-right tabular text-muted' }, row.original.percent != null
      ? `${Number(row.original.percent).toLocaleString('pt-BR')}% (−${Number(row.original.tax_rate).toLocaleString('pt-BR')}% imp.)`
      : 'fixo') },
  { accessorKey: 'amount', header: () => h('span', { class: 'block text-right' }, 'Comissão'),
    cell: ({ row }) => h('p', { class: 'text-right tabular text-highlighted' }, formatMoney(row.original.amount)) },
  { id: 'status', header: 'Status', cell: ({ row }) => h(UBadge, {
    label: row.original.payment_id ? `Paga ${formatDate(row.original.paid_on)}` : row.original.first_payment ? 'A pagar' : 'Prevista',
    color: row.original.payment_id ? 'success' : row.original.first_payment ? 'warning' : 'neutral', variant: 'subtle',
  }) },
])

// Pay: one outflow per professional and company
const pay = reactive({ open: false, date: today(), subgroup_id: undefined as number | undefined, saving: false })
const costSubgroups = computed(() => (lookups.cache.value.subgroups ?? [])
  .filter(s => !INFLOW_GROUPS.includes(s.group) && s.group !== 'transfer')
  .map(s => ({ label: s.name, value: s.id!, description: lookups.groupLabel(s.group) })))
function openPay() {
  pay.date = today()
  pay.subgroup_id ??= (lookups.cache.value.subgroups ?? []).find(s => /comiss/i.test(s.name))?.id ?? undefined
  pay.open = true
}
async function confirmPay() {
  pay.saving = true
  try {
    const txs = await unwrap(api.POST('/api/commission/pay', {
      body: { ids: toPay.value.map(c => c.id), date: pay.date, subgroup_id: pay.subgroup_id! },
    }))
    notifySuccess(`${txs.length} pagamento(s) lançado(s)`)
    pay.open = false
    selection.clear()
    load()
  } catch (e) {
    notifyError(e)
  } finally {
    pay.saving = false
  }
}

// Tax of a sales month per company (empty = the company's default); changes the unpaid commissions
// Add commissions: pick a sale, then the same editor as in the sale drawer
const adding = reactive({ open: false, saleId: undefined as number | undefined, search: '', sales: [] as { label: string; value: number }[] })
let saleTimer: ReturnType<typeof setTimeout> | undefined
async function loadSales() {
  try {
    const query = { ...(adding.search ? { search: adding.search } : {}), ordering: '-date' }
    adding.sales = (await unwrap(api.GET('/api/sale', { params: { query: query as any } }))).items.map(s => ({
      label: `${s.contact_name ?? '—'} · ${s.product_name ?? '—'} · ${formatDate(s.date)} · ${formatMoney(s.amount)}`, value: s.id!,
    }))
  } catch (e) {
    notifyError(e)
  }
}
watch(() => adding.search, () => { clearTimeout(saleTimer); saleTimer = setTimeout(loadSales, 250) })
function openAdd() {
  Object.assign(adding, { open: true, saleId: undefined, search: '' })
  loadSales()
}
watch(() => adding.open, (v) => { if (!v) load() })

const tax = reactive({ open: false, month: '', rows: [] as components['schemas']['MonthTaxOut'][] })
async function loadTax() {
  try {
    tax.rows = await unwrap(api.GET('/api/commission/tax', { params: { query: { month: `${tax.month}-01` } } }))
  } catch (e) {
    notifyError(e)
  }
}
function openTax() {
  const [y, m] = filters.month.split('-').map(Number)
  const d = new Date(y!, m! - 2, 1)  // sales month of the commissions on screen
  tax.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  tax.open = true
}
watch(() => tax.open && tax.month, (v) => { if (v) loadTax() })
async function setTax(companyId: number, rate: number | null | undefined) {
  try {
    await unwrap(api.PUT('/api/commission/tax', {
      body: { company_id: companyId, month: `${tax.month}-01`, rate: rate == null ? null : rate.toFixed(2) },
    }))
    await loadTax()
    load()
  } catch (e) {
    notifyError(e)
  }
}

function exportXlsx() {
  download(`/api/commission/export?${toSearchParams(query.value)}`, 'comissoes.xlsx').catch(notifyError)
}
</script>

<template>
  <AppPage title="Comissões">
    <template #actions>
      <UButton v-if="auth.can('sales', 'change')" label="Adicionar" icon="i-lucide-plus" @click="openAdd" />
      <UButton label="Demonstrativo" icon="i-lucide-receipt-text" color="neutral" variant="outline"
               :to="{ path: '/sales/statement', query: { month: filters.month } }" />
      <UButton label="Exportar" icon="i-lucide-file-down" color="neutral" variant="outline" @click="exportXlsx" />
      <UButton v-if="auth.can('sales', 'change')" label="Imposto do mês" icon="i-lucide-percent" color="neutral" variant="outline"
               @click="openTax" />
      <USelect :model-value="due" :disabled="!auth.can('sales', 'change')" class="w-64" aria-label="Vencimento das comissões"
               :items="[{ label: 'Vence após o 1º pagamento', value: 'payment' }, { label: 'Vence após a venda', value: 'sale' }]"
               @update:model-value="(v: any) => setDue(v)" />
    </template>
    <template #toolbar>
      <USelect v-model="filters.month" :items="monthItems" :disabled="filters.status === 'planned'" class="w-32" aria-label="Mês de pagamento" />
      <USelectMenu v-model="filters.salesperson_id" :items="lookups.options.salespeople.value" value-key="value" multiple
                   placeholder="Profissionais" class="w-48" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Empresas" class="w-44" />
      <USelect v-model="filters.status" :items="[{ label: 'Previstas', value: 'planned' }, { label: 'A pagar', value: 'pending' }, { label: 'Pagas', value: 'paid' }]"
               placeholder="Status" class="w-32" />
      <UButton v-if="filters.status" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Limpar status"
               @click="filters.status = undefined" />
    </template>

    <div class="grid gap-3 sm:grid-cols-3">
      <SStat :label="salesMonth ? `Total · ${due === 'payment' ? '1º pagamento em' : 'vendas de'} ${salesMonth}` : 'Total'" :value="formatMoney(sum(items))" :loading="loading" icon="i-lucide-hand-coins" />
      <SStat label="A pagar" :value="formatMoney(sum(pending))" tone="primary" :loading="loading" icon="i-lucide-clock" />
      <SStat label="Pago" :value="formatMoney(sum(paid))" tone="success" :loading="loading" icon="i-lucide-check-check" />
    </div>

    <div class="grid items-start gap-4 xl:grid-cols-[1fr_20rem]">
      <div class="s-panel overflow-hidden" :class="{ 'opacity-70': loading }">
        <UTable :data="items" :columns="columns" :loading="loading" sticky empty="Nenhuma comissão"
                class="max-h-[calc(100dvh-20rem)]" />
      </div>
      <SPanel title="Por profissional">
        <table class="w-full text-sm tabular">
          <thead>
            <tr class="text-xs text-muted">
              <th class="pb-2 text-left font-medium">Profissional</th>
              <th class="pb-2 text-right font-medium">A pagar</th>
              <th class="pb-2 text-right font-medium">Pago</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in byPerson" :key="p.id" class="border-t border-muted">
              <td class="py-1.5">
                <NuxtLink :to="{ path: '/sales/statement', query: { salesperson: p.id, month: filters.month } }"
                          class="text-highlighted hover:text-primary">{{ p.name }}</NuxtLink>
              </td>
              <td class="py-1.5 text-right" :class="p.pending ? 'text-warning' : 'text-dimmed'">{{ formatMoney(p.pending) }}</td>
              <td class="py-1.5 text-right" :class="p.paid ? 'text-success' : 'text-dimmed'">{{ formatMoney(p.paid) }}</td>
            </tr>
          </tbody>
        </table>
      </SPanel>
    </div>

    <AppBulkBar :count="selection.ids.value.length" @clear="selection.clear">
      <span class="text-sm tabular text-warning whitespace-nowrap">{{ formatMoney(sum(toPay)) }}</span>
      <UButton label="Pagar" icon="i-lucide-banknote" size="sm" variant="soft" :disabled="!toPay.length" @click="openPay" />
    </AppBulkBar>

    <UModal v-model:open="pay.open" :title="`Pagar ${toPay.length} comissão(ões) · ${formatMoney(sum(toPay))}`">
      <template #body>
        <div class="grid gap-3 sm:grid-cols-2">
          <UFormField label="Data do pagamento">
            <UInput v-model="pay.date" type="date" class="w-full" />
          </UFormField>
          <UFormField label="Subgrupo">
            <USelectMenu v-model="pay.subgroup_id" :items="costSubgroups" value-key="value" class="w-full" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="pay.open = false" />
          <UButton label="Pagar" :loading="pay.saving" :disabled="!pay.subgroup_id || !pay.date" @click="confirmPay" />
        </div>
      </template>
    </UModal>
    <UModal v-model:open="tax.open" title="Imposto do mês">
      <template #body>
        <div class="flex flex-col gap-4">
          <UFormField label="Mês das vendas">
            <USelect v-model="tax.month" :items="monthItems" class="w-32" />
          </UFormField>
          <ul class="flex flex-col divide-y divide-muted">
            <li v-for="r in tax.rows" :key="r.company_id" class="flex items-center justify-between gap-3 py-2 text-sm">
              <span class="flex-1 truncate">{{ r.company_name }}</span>
              <UInputNumber :model-value="r.rate != null ? Number(r.rate) : undefined" :min="0" :max="100" :step="0.01"
                            :increment="false" :decrement="false" :placeholder="`${Number(r.default_rate).toLocaleString('pt-BR')}%`"
                            locale="pt-BR" class="w-24"
                            :aria-label="`Imposto ${r.company_name}`"
                            @update:model-value="(v: any) => setTax(r.company_id, v == null || Number.isNaN(v) ? null : v)" />
              <span class="-ms-2 text-muted">%</span>
            </li>
          </ul>
        </div>
      </template>
    </UModal>

    <UModal v-model:open="adding.open" title="Adicionar comissão" :ui="{ content: 'sm:max-w-3xl' }">
      <template #body>
        <div class="flex flex-col gap-4">
          <UFormField label="Venda" required>
            <USelectMenu v-model="adding.saleId" v-model:search-term="adding.search" :items="adding.sales" value-key="value"
                         ignore-filter placeholder="Buscar venda" class="w-full" />
          </UFormField>
          <SalesCommissions v-if="adding.saleId" :key="adding.saleId" :sale-id="adding.saleId" />
        </div>
      </template>
    </UModal>
  </AppPage>
</template>
