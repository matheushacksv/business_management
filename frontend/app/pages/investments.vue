<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { components } from '~/types/api'

type Investment = components['schemas']['InvestmentOut']
definePageMeta({ permission: ['investments', 'view'] })

const { api, unwrap, download, notifyError } = useApi()
const lookups = useLookups()
await lookups.ensure('companies').catch(notifyError)
const UButton = resolveComponent('UButton')
const UBadge = resolveComponent('UBadge')

const crud = ref<{ reload: () => Promise<void> } | null>(null)
const filters = reactive({ holder: undefined as string | undefined, company_id: [] as number[], inactive: false })
const rowFilter = (r: Investment) => (!filters.holder || r.holder === filters.holder)
  && (!filters.company_id.length || filters.company_id.includes(r.company_id)) && (filters.inactive || r.active)

const options = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ label, value }))
const percent = (v: unknown) => v == null ? '—' : `${Number(v).toLocaleString('pt-BR')}%`
const sum = (rows: Investment[], key: 'balance' | 'yield_amount' | 'applied' | 'redeemed') => rows.reduce((s, r) => s + Number(r[key]), 0)
const byInstitution = (rows: Investment[]) => Object.entries(rows.reduce<Record<string, number>>((acc, r) => {
  acc[r.institution] = (acc[r.institution] ?? 0) + Number(r.balance)
  return acc
}, {})).sort((a, b) => b[1] - a[1])

const viewing = ref<Investment | null>(null)
async function refreshViewing() {
  await crud.value?.reload()
  if (viewing.value) viewing.value = await unwrap(api.GET('/api/investment/{investment_id}', { params: { path: { investment_id: viewing.value.id! } } }))
}

const right = (label: string) => () => h('span', { class: 'block text-right' }, label)
const money = (key: keyof Investment) => ({ row }: any) => h('p', { class: 'text-right tabular' }, formatMoney(row.original[key]))
const columns = [
  { accessorKey: 'institution', header: 'Instituição', cell: ({ row }: any) => h('div', [
    h('p', { class: 'text-highlighted' }, row.original.institution),
    h('p', { class: 'text-xs text-dimmed' }, [LABELS.investmentKind[row.original.kind], row.original.description].filter(Boolean).join(' · ')),
  ]) },
  { accessorKey: 'holder', header: 'Titularidade', cell: ({ row }: any) => h('div', [
    h(UBadge, { label: LABELS.holder[row.original.holder], color: row.original.holder === 'company' ? 'primary' : 'neutral', variant: 'subtle' }),
    h('p', { class: 'text-xs text-dimmed mt-0.5' }, row.original.company_name),
  ]) },
  { accessorKey: 'applied', header: right('Aplicado líquido'),
    cell: ({ row }: any) => h('p', { class: 'text-right tabular' }, formatMoney(Number(row.original.applied) - Number(row.original.redeemed))) },
  { accessorKey: 'balance', header: right('Saldo'), cell: ({ row }: any) => h('div', { class: 'text-right' }, [
    h('p', { class: 'tabular text-highlighted' }, formatMoney(row.original.balance)),
    row.original.balance_date ? h('p', { class: 'text-xs text-dimmed' }, `extrato ${formatDate(row.original.balance_date)}`) : null,
  ]) },
  { accessorKey: 'yield_amount', header: right('Rendimento'), cell: ({ row }: any) => h('div', { class: 'text-right tabular' }, [
    h('p', { class: Number(row.original.yield_amount) < 0 ? 'text-error' : 'text-success' }, formatMoney(row.original.yield_amount)),
    h('p', { class: 'text-xs text-dimmed' }, percent(row.original.yield_percent)),
  ]) },
  { id: 'movements', header: '', cell: ({ row }: any) => h('div', { class: 'flex justify-end' }, h(UButton, {
    label: 'Movimentos', icon: 'i-lucide-arrow-down-up', size: 'xs', color: 'neutral', variant: 'outline',
    onClick: (e: Event) => { e.stopPropagation(); viewing.value = row.original },
  })) },
]
const fields = computed(() => [
  { key: 'institution', label: 'Instituição', required: true },
  { key: 'kind', label: 'Tipo', type: 'select' as const, options: options(LABELS.investmentKind), required: true, default: 'cdb' },
  { key: 'holder', label: 'Titularidade', type: 'select' as const, options: options(LABELS.holder), required: true, default: 'company' },
  { key: 'company_id', label: 'Empresa', type: 'select' as const, options: lookups.options.companies.value, required: true },
  { key: 'description', label: 'Descrição', span: 2 as const },
  { key: 'notes', label: 'Observações', type: 'textarea' as const },
  { key: 'active', label: 'Ativo', type: 'switch' as const, default: true },
])
</script>

<template>
  <AppCrud
    ref="crud" title="Investimentos" module="investments" singular="Investimento"
    :columns="columns" :fields="fields" :search-keys="['institution', 'description', 'company_name']" :row-filter="rowFilter"
    :load="() => unwrap(api.GET('/api/investment', { params: { query: {} } }))"
    :create="(d) => unwrap(api.POST('/api/investment', { body: d as any }))"
    :update="(id, d) => unwrap(api.PATCH('/api/investment/{investment_id}', { params: { path: { investment_id: id } }, body: d }))"
    :remove="(id) => unwrap(api.DELETE('/api/investment/{investment_id}', { params: { path: { investment_id: id } } }))"
  >
    <template #actions>
      <UButton label="Exportar" icon="i-lucide-file-down" color="neutral" variant="outline"
               @click="download('/api/investment/export', 'investimentos.xlsx').catch(notifyError)" />
    </template>
    <template #toolbar>
      <USelect v-model="filters.holder" :items="options(LABELS.holder)" placeholder="Titularidade" class="w-36" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Empresas" class="w-44" />
      <UButton v-if="filters.holder || filters.company_id.length" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Limpar filtros"
               @click="Object.assign(filters, { holder: undefined, company_id: [] })" />
      <USwitch v-model="filters.inactive" label="Inativos" class="ms-auto" />
    </template>
    <template #summary="{ rows }">
      <div class="grid gap-3 sm:grid-cols-3">
        <SStat label="Saldo" :value="formatMoney(sum(rows, 'balance'))" tone="primary" icon="i-lucide-piggy-bank" />
        <SStat label="Aplicado líquido" :value="formatMoney(sum(rows, 'applied') - sum(rows, 'redeemed'))" icon="i-lucide-arrow-down-to-line" />
        <SStat label="Rendimento" :value="formatMoney(sum(rows, 'yield_amount'))" tone="success" icon="i-lucide-trending-up" />
      </div>
      <div v-if="byInstitution(rows).length > 1" class="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
        <span v-for="[name, total] in byInstitution(rows)" :key="name">{{ name }} <strong class="text-highlighted tabular">{{ formatMoney(total) }}</strong></span>
      </div>
    </template>
  </AppCrud>

  <UModal :open="!!viewing" :title="viewing ? `${viewing.institution}${viewing.description ? ` · ${viewing.description}` : ''}` : ''"
          :ui="{ content: 'sm:max-w-4xl' }" @update:open="(v: boolean) => { if (!v) viewing = null }">
    <template #body>
      <InvestmentsMovements v-if="viewing" :investment="viewing" @changed="refreshViewing" />
    </template>
  </UModal>
</template>
