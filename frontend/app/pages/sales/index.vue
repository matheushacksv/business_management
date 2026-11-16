<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Sale = components['schemas']['SaleOut']
definePageMeta({ permission: ['sales', 'view'] })

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('companies', 'products', 'salespeople').catch(notifyError)
const SStatusBadge = resolveComponent('SStatusBadge')
const UProgress = resolveComponent('UProgress')

const filters = reactive({
  search: '', date_from: '', date_to: '', company_id: [] as number[], product_id: [] as number[],
  salesperson_id: [] as number[], status: [] as string[], ordering: '-date',
})
const page = ref(1)
const items = ref<Sale[]>([])
const count = ref(0)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const query: Record<string, unknown> = { page: page.value }
    for (const [k, v] of Object.entries(filters)) if (Array.isArray(v) ? v.length : v) query[k] = v
    const data = await unwrap(api.GET('/api/sale', { params: { query: query as any } }))
    items.value = data.items
    count.value = data.count
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
let timer: ReturnType<typeof setTimeout> | undefined
watch(filters, () => { clearTimeout(timer); timer = setTimeout(() => (page.value === 1 ? load() : (page.value = 1)), 300) }, { deep: true })
watch(page, load)
onMounted(load)

const statusOptions = Object.entries(LABELS.saleStatus).map(([value, label]) => ({ value, label }))
const columns: TableColumn<Sale>[] = [
  { accessorKey: 'date', header: 'Data', cell: ({ row }) => formatDate(row.original.date) },
  { accessorKey: 'contact_name', header: 'Cliente', cell: ({ row }) => h('div', [
    h('p', { class: 'text-highlighted truncate max-w-64' }, row.original.contact_name ?? '—'),
    h('p', { class: 'text-xs text-dimmed' }, row.original.payment_terms || ''),
  ]) },
  { accessorKey: 'product_name', header: 'Produto', cell: ({ row }) => row.original.product_name ?? '—' },
  { accessorKey: 'salesperson_name', header: 'Vendedor', cell: ({ row }) => row.original.salesperson_name ?? '—' },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(SStatusBadge, { kind: 'sale', value: row.original.status }) },
  {
    accessorKey: 'amount',
    header: () => h('span', { class: 'block text-right' }, 'Valor / recebido'),
    cell: ({ row }) => {
      const s = row.original
      const pct = Math.min(100, (Number(s.received_amount) / Number(s.amount)) * 100)
      return h('div', { class: 'w-40 ms-auto text-right space-y-1' }, [
        h('p', { class: 'tabular text-highlighted' }, formatMoney(s.amount)),
        h(UProgress, { modelValue: pct, size: 'xs', color: 'success' }),
        h('p', { class: 'text-xs text-dimmed tabular' }, `${formatMoney(s.received_amount)} recebido`),
      ])
    },
  },
]

const selected = ref<number | null>(null)
const drawerOpen = ref(false)
const createOpen = ref(false)
function onCreated(id: number) {
  createOpen.value = false
  load()
  selected.value = id
  drawerOpen.value = true
}
</script>

<template>
  <AppPage title="Vendas e contratos">
    <template #actions>
      <UButton v-if="auth.can('sales', 'create')" label="Nova venda" icon="i-lucide-plus" class="rounded-full" @click="createOpen = true" />
    </template>
    <template #toolbar>
      <UInput v-model="filters.search" icon="i-lucide-search" placeholder="Cliente, condições, observação…" class="w-64" />
      <UInput v-model="filters.date_from" type="date" class="w-40" aria-label="De" />
      <UInput v-model="filters.date_to" type="date" class="w-40" aria-label="Até" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple placeholder="Empresas" class="w-44" />
      <USelectMenu v-model="filters.product_id" :items="lookups.options.products.value" value-key="value" multiple placeholder="Produtos" class="w-44" />
      <USelectMenu v-model="filters.salesperson_id" :items="lookups.options.salespeople.value" value-key="value" multiple placeholder="Vendedores" class="w-44" />
      <USelectMenu v-model="filters.status" :items="statusOptions" value-key="value" multiple placeholder="Status" class="w-36" />
    </template>

    <div class="s-panel overflow-hidden" :class="{ 'opacity-70': loading }">
      <UTable :data="items" :columns="columns" :loading="loading" sticky empty="Nenhuma venda encontrada"
              class="max-h-[calc(100dvh-16rem)]"
              @select="(_: Event, row: any) => { selected = row.original.id; drawerOpen = true }" />
    </div>
    <div class="flex items-center justify-between text-sm text-muted">
      <span>{{ count.toLocaleString('pt-BR') }} venda(s)</span>
      <UPagination v-if="count > 50" v-model:page="page" :total="count" :items-per-page="50" />
    </div>

    <SalesDrawer v-model:open="drawerOpen" :sale-id="selected" @changed="load" />
    <UModal v-model:open="createOpen" title="Nova venda" :ui="{ content: 'max-w-2xl' }">
      <template #body>
        <SalesForm @saved="onCreated" @cancel="createOpen = false" />
      </template>
    </UModal>
  </AppPage>
</template>
