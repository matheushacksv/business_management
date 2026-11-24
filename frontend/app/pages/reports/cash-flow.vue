<script setup lang="ts">
import type { components } from '~/types/api'

type CashFlow = components['schemas']['CashFlowOut']
definePageMeta({ permission: ['reports', 'view'] })

const { api, unwrap, notifyError, download } = useApi()
const lookups = useLookups()
lookups.ensure('companies').catch(notifyError)
const filters = useReportFilters()

const year = new Date().getFullYear()
const start = ref(`${year}-01-01`)
const end = ref(`${year}-12-31`)
const granularity = ref<'month' | 'day'>('month')
const flow = ref<CashFlow | null>(null)
const loading = ref(false)

async function load() {
  if (!start.value || !end.value) return
  loading.value = true
  try {
    flow.value = await unwrap(api.GET('/api/reports/cash-flow', {
      params: { query: { start: start.value, end: end.value, granularity: granularity.value, ...filters.query.value } as any },
    }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch([start, end, granularity, filters.query], load, { immediate: true })

function exportXlsx() {
  const params = toSearchParams({ start: start.value, end: end.value, granularity: granularity.value, ...filters.query.value })
  download(`/api/reports/cash-flow/export?${params}`, 'fluxo-de-caixa.xlsx').catch(notifyError)
}

const label = (p: string) => (granularity.value === 'month' ? formatMonth(p) : formatDate(p).slice(0, 5))
const chart = computed(() => {
  const periods = flow.value?.periods ?? []
  return {
    labels: periods.map(p => label(p.period)),
    series: [
      { label: 'Entradas', data: periods.map(p => Number(p.inflow)), color: '#34d399', type: 'bar' as const },
      { label: 'Saídas', data: periods.map(p => Number(p.outflow)), color: '#f87171', type: 'bar' as const },
      { label: 'Saldo final', data: periods.map(p => Number(p.closing)), color: '#2f9a53', type: 'line' as const },
    ],
  }
})
const totals = computed(() => (flow.value?.periods ?? []).reduce(
  (acc, p) => ({ inflow: acc.inflow + Number(p.inflow), outflow: acc.outflow + Number(p.outflow) }), { inflow: 0, outflow: 0 },
))
</script>

<template>
  <AppPage title="Fluxo de caixa">
    <template #actions>
      <UButton label="Exportar" icon="i-lucide-file-down" color="neutral" variant="outline" @click="exportXlsx" />
    </template>

    <template #toolbar>
      <UInput v-model="start" type="date" class="w-40" aria-label="Início" />
      <UInput v-model="end" type="date" class="w-40" aria-label="Fim" />
      <UTabs v-model="granularity" :items="[{ label: 'Mensal', value: 'month' }, { label: 'Diário', value: 'day' }]" :content="false" size="sm" />
      <USelectMenu v-model="filters.company_id.value" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Consolidado (todas)" class="w-56" />
      <USelect v-model="filters.status.value" :items="filters.statusOptions" class="w-52" />
    </template>

    <div class="grid gap-4 sm:grid-cols-4">
      <SStat label="Saldo inicial" :value="formatMoney(flow?.opening)" :loading="loading && !flow" icon="i-lucide-wallet" />
      <SStat label="Entradas" :value="formatMoney(totals.inflow)" tone="success" :loading="loading && !flow" icon="i-lucide-trending-up" />
      <SStat label="Saídas" :value="formatMoney(totals.outflow)" tone="error" :loading="loading && !flow" icon="i-lucide-trending-down" />
      <SStat label="Saldo final" :value="formatMoney(flow?.closing)" :tone="Number(flow?.closing) < 0 ? 'error' : 'primary'"
             :loading="loading && !flow" icon="i-lucide-landmark" />
    </div>

    <SPanel title="Entradas, saídas e saldo">
      <SChart type="bar" :labels="chart.labels" :series="chart.series" money :height="300" />
    </SPanel>

    <div class="s-panel overflow-auto max-h-[28rem]">
      <table class="w-full text-sm tabular">
        <thead class="sticky top-0 bg-(--s-solid)">
          <tr class="text-xs text-muted uppercase tracking-wide">
            <th class="px-4 py-3 text-left font-medium">{{ granularity === 'month' ? 'Mês' : 'Dia' }}</th>
            <th class="px-4 py-3 text-right font-medium">Saldo inicial</th>
            <th class="px-4 py-3 text-right font-medium">Entradas</th>
            <th class="px-4 py-3 text-right font-medium">Saídas</th>
            <th class="px-4 py-3 text-right font-medium">Saldo final</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in flow?.periods ?? []" :key="p.period" class="border-t border-muted">
            <td class="px-4 py-2">{{ label(p.period) }}</td>
            <td class="px-4 py-2 text-right"><SMoney :value="p.opening" signed /></td>
            <td class="px-4 py-2 text-right text-success">{{ formatMoney(p.inflow) }}</td>
            <td class="px-4 py-2 text-right text-error">{{ formatMoney(p.outflow) }}</td>
            <td class="px-4 py-2 text-right font-medium"><SMoney :value="p.closing" signed /></td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppPage>
</template>
