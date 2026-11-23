<script setup lang="ts">
import type { components } from '~/types/api'

type Analysis = components['schemas']['StatementAnalysisOut']
type Line = components['schemas']['StatementLineOut']

// Bank statement (OFX or C6 Bank PDF): 1) account + file  2) review the suggestion of every line  3) import.
// Subgroups chosen here are learned: the same description comes pre-filled next time.
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ imported: [] }>()

const { api, unwrap, raw, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('accounts', 'subgroups', 'companies').catch(notifyError)

const accountId = ref<number>()
const file = ref<File | null>(null)
const analysis = ref<Analysis | null>(null)
const lines = ref<Line[]>([])
const busy = ref(false)
watch(open, (v) => { if (v) { analysis.value = null; lines.value = []; file.value = null } })

const accounts = computed(() => (lookups.cache.value.accounts ?? []).map(a => ({
  label: a.name, value: a.id!, description: lookups.cache.value.companies?.find(c => c.id === a.company)?.name,
})))

async function analyze() {
  if (!accountId.value || !file.value) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('account_id', String(accountId.value))
    form.append('file', file.value)
    analysis.value = await (await raw('/api/statement-import/analyze', { method: 'POST', body: form })).json()
    lines.value = analysis.value!.lines
  } catch (e) {
    notifyError(e)
  } finally {
    busy.value = false
  }
}

const ACTIONS = [
  { label: 'Lançar', value: 'create' },
  { label: 'Baixar parcela', value: 'settle' },
  { label: 'Transferência', value: 'transfer' },
  { label: 'Ignorar', value: 'skip' },
]
const subgroupsFor = (type: string) => lookups.options.subgroups.value
  .filter(s => s.group !== 'transfer' && INFLOW_GROUPS.includes(s.group as string) === (type === 'inflow'))
const candidatesFor = (l: Line) => (analysis.value?.candidates ?? [])
  .filter(c => c.type === l.type && Number(c.amount) === Number(l.amount)
    && (c.id === l.match_id || !lines.value.some(o => o !== l && o.action === 'settle' && o.match_id === c.id)))
  .map(c => ({ label: c.label, value: c.id }))
const otherCompanies = computed(() => lookups.options.companies.value.filter(c => c.value !== analysis.value?.company_id))

const count = (action: string) => lines.value.filter(l => l.action === action).length
const pending = computed(() => lines.value.filter(l => (l.action === 'create' && !l.subgroup_id)
  || (l.action === 'settle' && !l.match_id) || (l.action === 'transfer' && !l.company_id)).length)

async function commit() {
  busy.value = true
  try {
    const r = await unwrap(api.POST('/api/statement-import', {
      body: { account_id: analysis.value!.account_id, lines: lines.value.map(l => ({ ...l, amount: String(l.amount) })) as any },
    }))
    notifySuccess(`${r.created} lançado(s), ${r.settled} parcela(s) baixada(s), ${r.transfers} transferência(s)`)
    open.value = false
    emit('imported')
  } catch (e) {
    notifyError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <UModal v-model:open="open" title="Importar extrato" :ui="{ content: analysis ? 'sm:max-w-7xl' : 'sm:max-w-lg' }">
    <template #body>
      <div v-if="!analysis" class="flex flex-col gap-4">
        <UFormField label="Conta" required>
          <USelectMenu v-model="accountId" :items="accounts" value-key="value" class="w-full" />
        </UFormField>
        <UFormField label="Extrato (OFX ou PDF do C6)" required>
          <UInput type="file" accept=".ofx,.pdf" class="w-full"
                  @change="(e: Event) => (file = (e.target as HTMLInputElement).files?.[0] ?? null)" />
        </UFormField>
        <UButton label="Ler extrato" icon="i-lucide-scan-text" :loading="busy" :disabled="!accountId || !file" class="self-end"
                 @click="analyze" />
      </div>

      <div v-else class="flex flex-col gap-3">
        <UAlert v-for="w in analysis.warnings" :key="w" color="warning" variant="subtle" icon="i-lucide-triangle-alert" :title="w" />
        <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
          <span>{{ analysis.company_name }}</span>
          <span>Lançar <strong class="text-highlighted">{{ count('create') }}</strong></span>
          <span>Baixar <strong class="text-highlighted">{{ count('settle') }}</strong></span>
          <span>Transferências <strong class="text-highlighted">{{ count('transfer') }}</strong></span>
          <span>Ignorar <strong class="text-highlighted">{{ count('skip') }}</strong></span>
          <span v-if="pending" class="text-warning">Faltam {{ pending }}</span>
        </div>
        <div class="max-h-[65dvh] overflow-auto rounded-xl ring ring-default">
          <table class="w-full text-sm">
            <thead class="sticky top-0 z-10 bg-default text-xs text-muted">
              <tr>
                <th class="px-3 py-2 text-left font-medium">Data</th>
                <th class="px-3 py-2 text-left font-medium">Descrição</th>
                <th class="px-3 py-2 text-right font-medium">Valor</th>
                <th class="px-3 py-2 text-left font-medium">Ação</th>
                <th class="px-3 py-2 text-left font-medium min-w-72">Detalhe</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-muted">
              <tr v-for="l in lines" :key="l.index" :class="l.action === 'skip' ? 'opacity-50' : ''">
                <td class="px-3 py-1.5 tabular whitespace-nowrap">{{ formatDate(l.date) }}</td>
                <td class="px-3 py-1.5">
                  <p class="truncate max-w-md">{{ l.description }}</p>
                  <UBadge v-if="l.duplicate" label="Já lançado" color="neutral" variant="subtle" size="sm" />
                </td>
                <td class="px-3 py-1.5 text-right tabular whitespace-nowrap" :class="l.type === 'inflow' ? 'text-success' : 'text-error'">
                  {{ l.type === 'inflow' ? '' : '−' }}{{ formatMoney(l.amount) }}
                </td>
                <td class="px-3 py-1.5">
                  <USelect v-model="l.action" :items="ACTIONS" size="sm" class="w-40" />
                </td>
                <td class="px-3 py-1.5">
                  <USelectMenu v-if="l.action === 'create'" :model-value="l.subgroup_id ?? undefined" @update:model-value="(v: any) => (l.subgroup_id = v ?? null)" :items="subgroupsFor(l.type)" value-key="value"
                               placeholder="Subgrupo" size="sm" class="w-full" :color="l.subgroup_id ? undefined : 'warning'" />
                  <USelect v-else-if="l.action === 'settle'" :model-value="l.match_id ?? undefined" @update:model-value="(v: any) => (l.match_id = v ?? null)" :items="candidatesFor(l)" placeholder="Parcela"
                           size="sm" class="w-full" />
                  <USelect v-else-if="l.action === 'transfer'" :model-value="l.company_id ?? undefined" @update:model-value="(v: any) => (l.company_id = v ?? null)" :items="otherCompanies" placeholder="Outra empresa"
                           size="sm" class="w-full" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex justify-between gap-2">
          <UButton label="Voltar" color="neutral" variant="ghost" @click="analysis = null" />
          <UButton label="Importar" icon="i-lucide-check" :loading="busy" :disabled="pending > 0" @click="commit" />
        </div>
      </div>
    </template>
  </UModal>
</template>
