<script setup lang="ts">
import type { components } from '~/types/api'

type Dre = components['schemas']['DREOut']
definePageMeta({ permission: ['reports', 'view'] })

const { api, unwrap, notifyError } = useApi()
const lookups = useLookups()
lookups.ensure('companies').catch(notifyError)
const filters = useReportFilters()

const currentYear = new Date().getFullYear()
const year = ref(currentYear)
const years = Array.from({ length: 6 }, (_, i) => ({ label: String(currentYear - i), value: currentYear - i }))
const showPercent = ref(false)
const hideEmpty = ref(true)
const collapsed = ref<Set<string>>(new Set())

const dre = ref<Dre | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    dre.value = await unwrap(api.GET('/api/reports/dre', { params: { query: { year: year.value, ...filters.query.value } as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch([year, filters.query], load, { immediate: true })

// Subgroup rows belong to the group above them
const rows = computed(() => {
  let group = ''
  return (dre.value?.lines ?? []).map((line) => {
    if (line.kind === 'group') group = line.key
    return { ...line, group: line.kind === 'subgroup' ? group : '' }
  }).filter(l => l.kind !== 'subgroup' || (!collapsed.value.has(l.group) && (!hideEmpty.value || Number(l.total) !== 0)))
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
const cell = (value: string | null | undefined, percent: string | null | undefined) =>
  showPercent.value ? formatPercent(percent) : formatMoney(value)
</script>

<template>
  <AppPage title="DRE">
    <template #toolbar>
      <USelect v-model="year" :items="years" class="w-28" />
      <USelectMenu v-model="filters.company_id.value" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Consolidado (todas)" class="w-56" />
      <USelect v-model="filters.status.value" :items="filters.statusOptions" class="w-52" />
      <USwitch v-model="showPercent" label="% da receita" />
      <USwitch v-model="hideEmpty" label="Ocultar zerados" />
    </template>

    <div class="s-panel overflow-auto" :class="{ 'opacity-60': loading }">
      <table class="w-full text-sm tabular">
        <thead class="sticky top-0 bg-(--s-solid) z-10">
          <tr class="text-xs text-muted uppercase tracking-wide">
            <th class="sticky left-0 bg-(--s-solid) px-4 py-3 text-left font-medium min-w-64">Resultado do exercício {{ year }}</th>
            <th v-for="m in MONTHS" :key="m" class="px-3 py-3 text-right font-medium">{{ m }}</th>
            <th class="px-4 py-3 text-right font-medium">Total</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!dre && loading"><td colspan="14" class="p-6"><USkeleton class="h-64 w-full" /></td></tr>
          <tr v-for="line in rows" :key="line.key" class="border-t border-muted" :class="rowClass[line.kind]">
            <td class="sticky left-0 px-4 py-2 whitespace-nowrap"
                :class="[line.kind === 'subgroup' ? 'ps-9' : '', line.kind === 'result' ? 'bg-(--s-result)' : 'bg-(--s-solid)']">
              <button v-if="line.kind === 'group'" class="inline-flex items-center gap-1.5 cursor-pointer" @click="toggle(line.key)">
                <UIcon :name="collapsed.has(line.key) ? 'i-lucide-chevron-right' : 'i-lucide-chevron-down'" class="size-4 text-dimmed" />
                {{ line.label }}
              </button>
              <span v-else>{{ line.kind === 'result' ? '= ' : '' }}{{ line.label }}</span>
            </td>
            <td v-for="(value, i) in line.months" :key="i" class="px-3 py-2 text-right whitespace-nowrap"
                :class="Number(value) < 0 ? 'text-error' : Number(value) === 0 ? 'text-dimmed' : ''">
              {{ cell(value, line.percents[i]) }}
            </td>
            <td class="px-4 py-2 text-right whitespace-nowrap font-medium" :class="Number(line.total) < 0 ? 'text-error' : ''">
              {{ cell(line.total, line.total_percent) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="text-xs text-dimmed">
      Estornos (tipo oposto ao do grupo) subtraem do grupo. Faturamento Bruto vem das vendas e é informativo.
    </p>
  </AppPage>
</template>
