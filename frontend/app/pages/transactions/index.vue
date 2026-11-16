<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Transaction = components['schemas']['TransactionOut']
definePageMeta({ permission: ['transactions', 'view'] })

const { api, unwrap, download, notifyError } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('companies', 'subgroups', 'groups').catch(notifyError)

const SMoney = resolveComponent('SMoney')
const SStatusBadge = resolveComponent('SStatusBadge')

// Filters (all server-side, same names as the API)
const filters = reactive({
  search: '',
  date_from: '',
  date_to: '',
  company_id: [] as number[],
  group: [] as string[],
  subgroup_id: [] as number[],
  type: [] as string[],
  status: [] as string[],
  ordering: '-date',
})
const page = ref(1)
const PAGE_SIZE = 50

const query = computed(() => {
  const q: Record<string, unknown> = { page: page.value, ordering: filters.ordering }
  for (const [key, value] of Object.entries(filters)) {
    if (key === 'ordering') continue
    if (Array.isArray(value) ? value.length : value) q[key] = value
  }
  return q
})

const items = ref<Transaction[]>([])
const count = ref(0)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await unwrap(api.GET('/api/transaction', { params: { query: query.value as any } }))
    items.value = data.items
    count.value = data.count
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}

// Debounced reload on filter change; page resets
let timer: ReturnType<typeof setTimeout> | undefined
watch(filters, () => {
  clearTimeout(timer)
  timer = setTimeout(() => { page.value === 1 ? load() : (page.value = 1) }, 300)
}, { deep: true })
watch(page, load)
onMounted(load)

function clearFilters() {
  Object.assign(filters, { search: '', date_from: '', date_to: '', company_id: [], group: [], subgroup_id: [], type: [], status: [] })
}
const activeFilters = computed(() => Object.entries(filters).filter(([k, v]) => k !== 'ordering' && (Array.isArray(v) ? v.length : v)).length)

function exportXlsx() {
  const { page: _, ...filters } = query.value as Record<string, unknown>
  const params = toSearchParams(filters)
  download(`/api/transaction/export?${params}`, 'lancamentos.xlsx').catch(notifyError)
}

const columns: TableColumn<Transaction>[] = [
  { accessorKey: 'date', header: 'Data', cell: ({ row }) => formatDate(row.original.date) },
  {
    accessorKey: 'contact_name',
    header: 'Cliente/Fornecedor',
    cell: ({ row }) => h('div', { class: 'min-w-0' }, [
      h('p', { class: 'truncate text-highlighted' }, row.original.contact_name ?? '—'),
      row.original.reference ? h('p', { class: 'truncate text-xs text-dimmed' }, row.original.reference) : null,
    ]),
  },
  {
    accessorKey: 'subgroup_name',
    header: 'Subgrupo',
    cell: ({ row }) => h('div', [
      h('p', row.original.subgroup_name),
      h('p', { class: 'text-xs text-dimmed' }, lookups.groupLabel(row.original.group)),
    ]),
  },
  { accessorKey: 'company_name', header: 'Empresa', meta: { class: { td: 'text-muted' } } },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(SStatusBadge, { kind: 'status', value: row.original.status }) },
  {
    accessorKey: 'amount',
    header: () => h('span', { class: 'block text-right' }, 'Valor'),
    cell: ({ row }) => h('div', { class: 'text-right' }, [
      h(SMoney, { value: row.original.amount, type: row.original.type }),
      row.original.series_index ? h('p', { class: 'text-xs text-dimmed' }, `parcela ${row.original.series_index}`) : null,
    ]),
  },
]

const orderings = [
  { label: 'Mais recentes', value: '-date' },
  { label: 'Mais antigos', value: 'date' },
  { label: 'Maior valor', value: '-amount' },
  { label: 'Menor valor', value: 'amount' },
  { label: 'Criados por último', value: '-created_at' },
]

// Drawer / create modal
const selected = ref<number | null>(null)
const drawerOpen = ref(false)
const createOpen = ref(false)
const transferOpen = ref(false)
function onTransferred(transfer: { outflow_id: number }) {
  transferOpen.value = false
  load()
  selected.value = transfer.outflow_id
  drawerOpen.value = true
}
function onSelect(_: Event, row: { original: Transaction }) {
  selected.value = row.original.id!
  drawerOpen.value = true
}
function onCreated(id: number | null) {
  createOpen.value = false
  load()
  if (id) { selected.value = id; drawerOpen.value = true }
}
</script>

<template>
  <AppPage title="Lançamentos">
    <template #actions>
      <UButton label="Exportar" icon="i-lucide-file-down" color="neutral" variant="outline" @click="exportXlsx" />
      <UButton v-if="auth.can('transactions', 'create')" label="Transferência" icon="i-lucide-repeat"
               color="neutral" variant="outline" @click="transferOpen = true" />
      <UButton v-if="auth.can('transactions', 'create')" label="Novo lançamento" icon="i-lucide-plus"
               class="rounded-full" @click="createOpen = true" />
    </template>

    <template #toolbar>
      <UInput v-model="filters.search" icon="i-lucide-search" placeholder="Buscar referência, observação, contato…" class="w-64" />
      <UInput v-model="filters.date_from" type="date" class="w-40" aria-label="De" />
      <UInput v-model="filters.date_to" type="date" class="w-40" aria-label="Até" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Empresas" class="w-44" />
      <USelectMenu v-model="filters.group" :items="lookups.options.groups.value" value-key="value" multiple
                   placeholder="Grupos" class="w-44" />
      <USelectMenu v-model="filters.subgroup_id" :items="lookups.options.subgroups.value" value-key="value" multiple
                   placeholder="Subgrupos" class="w-44" />
      <USelectMenu v-model="filters.type" :items="TYPE_OPTIONS" value-key="value" multiple placeholder="Tipo" class="w-32" />
      <USelectMenu v-model="filters.status" :items="STATUS_OPTIONS" value-key="value" multiple placeholder="Status" class="w-36" />
      <USelect v-model="filters.ordering" :items="orderings" class="w-44" />
      <UButton v-if="activeFilters" :label="`Limpar (${activeFilters})`" icon="i-lucide-x" color="neutral" variant="ghost" @click="clearFilters" />
    </template>

    <div class="s-panel overflow-hidden" :class="{ 'opacity-70': loading }">
      <UTable :data="items" :columns="columns" :loading="loading" sticky empty="Nenhum lançamento encontrado"
              class="max-h-[calc(100dvh-16rem)]" @select="onSelect" />
    </div>

    <div class="flex items-center justify-between text-sm text-muted">
      <span>{{ count.toLocaleString('pt-BR') }} lançamento(s)</span>
      <UPagination v-if="count > PAGE_SIZE" v-model:page="page" :total="count" :items-per-page="PAGE_SIZE" />
    </div>

    <TransactionsDrawer v-model:open="drawerOpen" :transaction-id="selected" @changed="load" />

    <UModal v-model:open="createOpen" title="Novo lançamento" :ui="{ content: 'max-w-2xl' }">
      <template #body>
        <TransactionsForm @saved="onCreated" @cancel="createOpen = false" />
      </template>
    </UModal>

    <UModal v-model:open="transferOpen" title="Transferência entre empresas" :ui="{ content: 'max-w-2xl' }">
      <template #body>
        <TransactionsTransferForm @saved="onTransferred" @cancel="transferOpen = false" />
      </template>
    </UModal>
  </AppPage>
</template>
