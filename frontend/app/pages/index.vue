<script setup lang="ts">
import type { components } from '~/types/api'

type Dre = components['schemas']['DREOut']
const { api, unwrap, notifyError } = useApi()
const auth = useAuth()

const now = new Date()
const year = now.getFullYear()
const month = now.getMonth() // 0-based, index into DRE months
const monthStart = `${year}-${String(month + 1).padStart(2, '0')}-01`

const dre = ref<Dre | null>(null)          // current year: the month cards
const chartDre = ref<Dre | null>(null)     // year picked on the chart (defaults to the current one)
const chartYear = ref(year)
const chartLoading = ref(false)
const yearOptions = Array.from({ length: 5 }, (_, i) => ({ label: String(year - i), value: year - i }))
const cash = ref<{ opening: string; closing: string } | null>(null)
const pendingInvoices = ref<number | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    await Promise.all([
      auth.can('reports') && unwrap(api.GET('/api/reports/dre', { params: { query: { year } } }))
        .then(d => (dre.value = chartDre.value = d)),
      auth.can('reports') && unwrap(api.GET('/api/reports/cash-flow', {
        params: { query: { start: monthStart, end: today(), granularity: 'month', status: ['realized'] } as any },
      })).then(c => (cash.value = c)),
      auth.can('transactions') && unwrap(api.GET('/api/invoice/pending', { params: { query: { date_to: today() } as any } }))
        .then(p => (pendingInvoices.value = p.count)),
    ])
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
})

// Other years are fetched on demand; the current one is already loaded for the cards
watch(chartYear, async (value) => {
  if (value === year) {
    chartDre.value = dre.value
    return
  }
  chartLoading.value = true
  try {
    chartDre.value = await unwrap(api.GET('/api/reports/dre', { params: { query: { year: value } } }))
  } catch (e) {
    notifyError(e)
  } finally {
    chartLoading.value = false
  }
})

const line = (key: string) => dre.value?.lines.find(l => l.key === key)
const chartLine = (key: string) => chartDre.value?.lines.find(l => l.key === key)
const at = (key: string) => line(key)?.months[month]
const costs = computed(() => Number(at('group:variable_costs') ?? 0) + Number(at('group:fixed_costs') ?? 0))

const chart = computed(() => ({
  labels: MONTHS,
  series: [
    { label: 'Receitas operacionais', data: (chartLine('group:operating_revenue')?.months ?? []).map(Number), color: '#38bdf8', type: 'bar' as const },
    { label: 'Custos', data: MONTHS.map((_, i) => Number(chartLine('group:variable_costs')?.months[i] ?? 0) + Number(chartLine('group:fixed_costs')?.months[i] ?? 0)),
      color: '#f87171', type: 'bar' as const },
    { label: 'Resultado líquido', data: (chartLine('net_result')?.months ?? []).map(Number), color: '#34d399', type: 'line' as const },
  ],
}))
const greeting = computed(() => {
  const h = now.getHours()
  const name = auth.me.value?.name?.split(' ')[0]
  return `${h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite'}${name ? `, ${name}` : ''}`
})
</script>

<template>
  <AppPage title="Início">
    <div>
      <h1 class="font-display text-3xl font-semibold tracking-tight text-highlighted">{{ greeting }}</h1>
      <p class="mt-1 text-sm text-muted">{{ MONTHS[month] }}/{{ year }} · consolidado de todas as empresas que você acessa</p>
    </div>

    <template v-if="auth.can('reports')">
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SStat label="Receitas operacionais no mês" :value="formatMoney(at('group:operating_revenue'))" tone="primary"
               :loading="loading" icon="i-lucide-trending-up" hint="Previsto + realizado" />
        <SStat label="Custos no mês" :value="formatMoney(costs)" tone="error" :loading="loading" icon="i-lucide-trending-down"
               hint="Variáveis + fixos" />
        <SStat label="Resultado líquido no mês" :value="formatMoney(at('net_result'))"
               :tone="Number(at('net_result')) < 0 ? 'error' : 'success'" :loading="loading" icon="i-lucide-scale" />
        <SStat label="Saldo em caixa hoje" :value="formatMoney(cash?.closing)" :loading="loading" icon="i-lucide-landmark"
               hint="Somente realizado" />
      </div>

      <SPanel title="Evolução mensal" description="Receitas operacionais, custos e resultado líquido por mês">
        <template #actions>
          <div class="flex items-center gap-2">
            <USelect v-model="chartYear" :items="yearOptions" size="sm" class="w-24" aria-label="Ano do gráfico" />
            <UButton label="Ver DRE" to="/reports/dre" trailing-icon="i-lucide-arrow-right" color="neutral" variant="ghost" size="sm" />
          </div>
        </template>
        <SChart type="bar" :labels="chart.labels" :series="chart.series" money :height="300"
                :class="{ 'opacity-50 transition-opacity': chartLoading }" />
      </SPanel>
    </template>

    <div class="grid gap-4 sm:grid-cols-2">
      <NuxtLink v-if="auth.can('transactions')" to="/invoices" class="s-panel p-5 flex items-center gap-4 hover:ring-1 hover:ring-sky-500/30 transition">
        <span class="size-10 rounded-xl bg-amber-500/10 ring ring-amber-500/20 grid place-items-center">
          <UIcon name="i-lucide-receipt-text" class="size-5 text-amber-400" />
        </span>
        <div class="flex-1">
          <p class="text-sm text-muted">Notas fiscais pendentes até hoje</p>
          <p class="font-display text-2xl font-semibold">{{ pendingInvoices ?? '—' }}</p>
        </div>
        <UIcon name="i-lucide-chevron-right" class="size-5 text-dimmed" />
      </NuxtLink>
      <NuxtLink v-if="auth.can('transactions', 'create')" to="/transactions" class="s-panel p-5 flex items-center gap-4 hover:ring-1 hover:ring-sky-500/30 transition">
        <span class="size-10 rounded-xl bg-sky-500/10 ring ring-sky-500/20 grid place-items-center">
          <UIcon name="i-lucide-arrow-left-right" class="size-5 text-primary" />
        </span>
        <div class="flex-1">
          <p class="text-sm text-muted">Lançamentos</p>
          <p class="font-display text-lg font-semibold">Registrar entrada ou saída</p>
        </div>
        <UIcon name="i-lucide-chevron-right" class="size-5 text-dimmed" />
      </NuxtLink>
    </div>
  </AppPage>
</template>
