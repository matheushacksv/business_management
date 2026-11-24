<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Pending = components['schemas']['PendingInvoiceOut']
definePageMeta({ permission: ['transactions', 'view'] })

const { api, unwrap, notifyError } = useApi()
const lookups = useLookups()
lookups.ensure('companies').catch(notifyError)
const SStatusBadge = resolveComponent('SStatusBadge')
const SMoney = resolveComponent('SMoney')

const filters = reactive({
  direction: undefined as string | undefined, kind: undefined as string | undefined, reason: 'all',
  company_id: [] as number[], date_from: '', date_to: today(),
})
useQueryFilters(filters)
const page = ref(1)
const items = ref<Pending[]>([])
const count = ref(0)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const query: Record<string, unknown> = { page: page.value }
    for (const [k, v] of Object.entries(filters)) if (Array.isArray(v) ? v.length : v) query[k] = v
    const data = await unwrap(api.GET('/api/invoice/pending', { params: { query: query as any } }))
    items.value = data.items
    count.value = data.count
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(filters, () => (page.value === 1 ? load() : (page.value = 1)), { deep: true })
watch(page, load)
onMounted(load)

const columns: TableColumn<Pending>[] = [
  { accessorKey: 'transaction_date', header: 'Data', cell: ({ row }) => formatDate(row.original.transaction_date) },
  { accessorKey: 'contact_name', header: 'Cliente/Fornecedor', cell: ({ row }) => row.original.contact_name ?? '—' },
  { accessorKey: 'company_name', header: 'Empresa', meta: { class: { td: 'text-muted' } } },
  { accessorKey: 'kind', header: 'Nota', cell: ({ row }) => h('div', [
    h('p', LABELS.invoiceKind[row.original.kind]),
    h('p', { class: 'text-xs text-dimmed' }, row.original.direction === 'receive' ? 'Receber do fornecedor' : 'Emitir ao cliente'),
  ]) },
  { accessorKey: 'number', header: 'Número', cell: ({ row }) => row.original.done ? h('div', [
    h('p', row.original.number || '—'),
    row.original.issue_date && h('p', { class: 'text-xs text-dimmed' }, formatDate(row.original.issue_date)),
  ]) : '—' },
  { accessorKey: 'pending_reason', header: 'Situação', cell: ({ row }) => h(SStatusBadge, { kind: 'invoice', value: row.original.pending_reason }) },
  { accessorKey: 'transaction_amount', header: () => h('span', { class: 'block text-right' }, 'Valor'),
    cell: ({ row }) => h('div', { class: 'text-right' }, h(SMoney, { value: row.original.transaction_amount })) },
]

const REASONS = [
  { label: 'Todas', value: 'all' }, { label: 'Pendentes', value: 'pending' }, { label: 'Sem nota', value: 'missing_invoice' },
  { label: 'Sem arquivo', value: 'missing_attachment' }, { label: 'Completas', value: 'done' },
]
const selected = ref<number | null>(null)
const drawerOpen = ref(false)
</script>

<template>
  <AppPage title="Notas fiscais">
    <template #toolbar>
      <USelect v-model="filters.direction" :items="[{ label: 'A receber', value: 'receive' }, { label: 'A emitir', value: 'issue' }]"
               placeholder="Receber e emitir" class="w-44" />
      <USelect v-model="filters.kind" :items="[{ label: 'Serviço', value: 'service' }, { label: 'Produto', value: 'product' }]"
               placeholder="Serviço e produto" class="w-44" />
      <USelect v-model="filters.reason" :items="REASONS" class="w-44" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple placeholder="Empresas" class="w-44" />
      <UInput v-model="filters.date_from" type="date" class="w-40" aria-label="De" />
      <UInput v-model="filters.date_to" type="date" class="w-40" aria-label="Até" />
    </template>

    <div class="s-panel overflow-hidden" :class="{ 'opacity-70': loading }">
      <UTable :data="items" :columns="columns" :loading="loading" sticky empty="Nenhuma nota"
              class="max-h-[calc(100dvh-16rem)]"
              @select="(_: Event, row: any) => { selected = row.original.transaction_id; drawerOpen = true }" />
    </div>
    <div class="flex items-center justify-between text-sm text-muted">
      <span>{{ count.toLocaleString('pt-BR') }} nota(s)</span>
      <UPagination v-if="count > 50" v-model:page="page" :total="count" :items-per-page="50" />
    </div>

    <TransactionsDrawer v-model:open="drawerOpen" :transaction-id="selected" @changed="load" />
  </AppPage>
</template>
