<script setup lang="ts">
import type { components } from '~/types/api'

type Report = components['schemas']['SalesReportOut']
definePageMeta({ permission: ['reports', 'view'] })

const { api, unwrap, notifyError } = useApi()
const lookups = useLookups()
lookups.ensure('companies', 'products', 'salespeople').catch(notifyError)

const year = new Date().getFullYear()
const start = ref(`${year}-01-01`)
const end = ref(`${year}-12-31`)
const company_id = ref<number[]>([])
const product_id = ref<number[]>([])
const salesperson_id = ref<number[]>([])
const report = ref<Report | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const query: Record<string, unknown> = { start: start.value, end: end.value }
    if (company_id.value.length) query.company_id = company_id.value
    if (product_id.value.length) query.product_id = product_id.value
    if (salesperson_id.value.length) query.salesperson_id = salesperson_id.value
    report.value = await unwrap(api.GET('/api/reports/sales', { params: { query: query as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch([start, end, company_id, product_id, salesperson_id], load, { immediate: true, deep: true })

const chart = computed(() => {
  const periods = report.value?.periods ?? []
  return {
    labels: periods.map(p => formatMonth(p.period)),
    series: [
      { label: 'Vendido', data: periods.map(p => Number(p.sold)), color: '#38bdf8' },
      { label: 'Recebido', data: periods.map(p => Number(p.received)), color: '#34d399' },
    ],
  }
})
const rate = computed(() => {
  const sold = Number(report.value?.total_sold ?? 0)
  return sold ? Number(report.value!.total_received) / sold : null
})
</script>

<template>
  <AppPage title="Vendido × recebido">
    <template #toolbar>
      <UInput v-model="start" type="date" class="w-40" aria-label="Início" />
      <UInput v-model="end" type="date" class="w-40" aria-label="Fim" />
      <USelectMenu v-model="company_id" :items="lookups.options.companies.value" value-key="value" multiple placeholder="Empresas" class="w-44" />
      <USelectMenu v-model="product_id" :items="lookups.options.products.value" value-key="value" multiple placeholder="Produtos" class="w-44" />
      <USelectMenu v-model="salesperson_id" :items="lookups.options.salespeople.value" value-key="value" multiple placeholder="Vendedores" class="w-44" />
    </template>

    <div class="grid gap-4 sm:grid-cols-4">
      <SStat label="Vendido" :value="formatMoney(report?.total_sold)" tone="primary" :loading="loading && !report" icon="i-lucide-handshake" />
      <SStat label="Recebido" :value="formatMoney(report?.total_received)" tone="success" :loading="loading && !report" icon="i-lucide-banknote" />
      <SStat label="Vendas" :value="String(report?.sales_count ?? 0)" :loading="loading && !report" icon="i-lucide-hash" />
      <SStat label="Recebido / vendido" :value="formatPercent(rate)" :loading="loading && !report" icon="i-lucide-percent"
             hint="Venda e recebimento caem em meses diferentes" />
    </div>

    <SPanel title="Por mês" description="Vendido pela data da venda; recebido pela data de pagamento das parcelas ligadas às vendas">
      <SChart type="bar" :labels="chart.labels" :series="chart.series" money :height="320" />
    </SPanel>
  </AppPage>
</template>
