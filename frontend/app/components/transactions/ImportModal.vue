<script setup lang="ts">
import type { components } from '~/types/api'

type Inspect = components['schemas']['ImportInspectOut']
type Result = components['schemas']['MappedImportOut']

// Import transactions from any .xlsx/.csv: 1) file  2) map columns -> fields  3) review + import.
// Stateless backend: the file goes with every request. The mapping is remembered per set of
// column headers (localStorage), so the same bank statement comes pre-filled next time.
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ imported: [] }>()

const { raw, notifyError, notifySuccess } = useApi()
const lookups = useLookups()

const step = ref<1 | 2 | 3>(1)
const file = ref<File | null>(null)
const sheet = ref<string | undefined>()
const headerRow = ref<number | null>(null)
const inspect = ref<Inspect | null>(null)
const result = ref<Result | null>(null)
const busy = ref(false)

// One choice per field: 'c:<column>' | 'f:<fixed value>' | 'm:sign' | 'm:subgroup' | 'none'
type FieldKey = 'date' | 'amount' | 'type' | 'subgroup' | 'status' | 'company' | 'account' | 'contact' | 'reference' | 'notes'
const choice = reactive<Record<FieldKey, string>>({} as any)
const valueMaps = reactive<Record<string, Record<string, string | number | undefined>>>({})
// Every unknown value seen in this import (kept after mapping, so the choice can be changed)
const unknownSeen = reactive<Record<string, { value: string; count: number }[]>>({})
const createContacts = ref(true)
const skipDuplicates = ref(true)

const FIELDS: { key: FieldKey; label: string; required?: boolean; fixed?: boolean; hint?: string }[] = [
  { key: 'date', label: 'Data', required: true },
  { key: 'amount', label: 'Valor', required: true },
  { key: 'type', label: 'Tipo', required: true },
  { key: 'subgroup', label: 'Subgrupo', required: true, fixed: true },
  { key: 'status', label: 'Status', fixed: true },
  { key: 'company', label: 'Empresa', required: true, fixed: true },
  { key: 'account', label: 'Conta', fixed: true },
  { key: 'contact', label: 'Cliente/Fornecedor' },
  { key: 'reference', label: 'Produto / Nº boleto' },
  { key: 'notes', label: 'Observações' },
]
const FIELD_LABEL = Object.fromEntries(FIELDS.map(f => [f.key, f.label])) as Record<string, string>

// Header words -> field (first match wins, in this order)
const GUESS: [FieldKey, string[]][] = [
  ['date', ['data', 'date', 'vencimento', 'dt ']],
  ['amount', ['valor', 'value', 'montante', 'quantia', 'amount']],
  ['type', ['tipo', 'natureza', 'd/c', 'c/d', 'entrada/saida']],
  ['subgroup', ['subgrupo', 'categoria', 'classificacao', 'plano de contas', 'conta contabil']],
  ['status', ['status', 'situacao']],
  ['company', ['empresa', 'cnpj']],
  ['account', ['conta', 'banco']],
  ['contact', ['cliente', 'fornecedor', 'favorecido', 'historico', 'nome', 'contato', 'pagador', 'beneficiario']],
  ['reference', ['boleto', 'produto', 'referencia', 'documento', 'doc']],
  ['notes', ['observ', 'descricao', 'obs', 'memo', 'complemento']],
]
const plain = (s: string) => s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()

onMounted(() => lookups.ensure('companies', 'subgroups', 'groups', 'accounts').catch(notifyError))

watch(open, (isOpen) => {
  if (!isOpen) return
  step.value = 1
  file.value = null
  inspect.value = null
  result.value = null
  sheet.value = undefined
  headerRow.value = null
})

// Step 1: read the file's columns
async function runInspect() {
  if (!file.value) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    if (sheet.value) form.append('sheet', sheet.value)
    if (headerRow.value) form.append('header_row', String(headerRow.value))
    inspect.value = await (await raw('/api/transaction-import/inspect', { method: 'POST', body: form })).json()
    sheet.value = inspect.value!.sheet ?? undefined
    headerRow.value = inspect.value!.header_row
    applySavedOrGuess()
  } catch (e) {
    notifyError(e)
    inspect.value = null
  } finally {
    busy.value = false
  }
}
watch(file, () => { sheet.value = undefined; headerRow.value = null; runInspect() })

const presetKey = computed(() => `ge-import-mapping:${inspect.value?.columns.map(c => plain(c.header)).join('|')}`)

function applySavedOrGuess() {
  for (const f of FIELDS) choice[f.key] = 'none'
  for (const key of Object.keys(valueMaps)) delete valueMaps[key]
  for (const key of Object.keys(unknownSeen)) delete unknownSeen[key]
  const saved = localStorage.getItem(presetKey.value)
  if (saved) {
    const preset = JSON.parse(saved)
    Object.assign(choice, preset.choice)
    Object.assign(valueMaps, preset.valueMaps ?? {})
    createContacts.value = preset.createContacts ?? true
    skipDuplicates.value = preset.skipDuplicates ?? true
    return
  }
  const used = new Set<FieldKey>()
  for (const column of inspect.value?.columns ?? []) {
    const header = plain(column.header)
    const match = GUESS.find(([key, words]) => !used.has(key) && words.some(w => header.includes(w.trim())))
    if (match) {
      used.add(match[0])
      choice[match[0]] = `c:${column.index}`
    }
  }
  if (choice.type === 'none') choice.type = 'm:sign'
  if (choice.status === 'none') choice.status = 'f:realized'
  if (choice.company === 'none' && lookups.options.companies.value.length === 1) {
    choice.company = `f:${lookups.options.companies.value[0]!.value}`
  }
}

// Step 2: mapping options
const columnItems = computed(() => (inspect.value?.columns ?? []).map(c => ({
  label: c.header, value: `c:${c.index}`, description: c.samples.filter(Boolean)[0] ?? '',
})))
const subgroupItems = computed(() => (lookups.cache.value.subgroups ?? [])
  .filter(s => s.group !== 'transfer')
  .map(s => ({ label: s.name, value: s.id!, description: lookups.groupLabel(s.group) })))
const companyName = (id?: number | null) => lookups.cache.value.companies?.find(c => c.id === id)?.name ?? ''
const fixedCompany = computed(() => choice.company?.startsWith('f:') ? Number(choice.company.slice(2)) : null)
const accountItems = computed(() => (lookups.cache.value.accounts ?? [])
  .filter(a => !fixedCompany.value || a.company === fixedCompany.value)
  .map(a => ({ label: a.name, value: a.id!, description: companyName(a.company) })))

// Mixed lists (labels, columns, fixed options): typed loosely for USelectMenu
function itemsFor(key: FieldKey): any[] {
  const none = { label: '— não importar —', value: 'none' }
  const columns = [{ type: 'label' as const, label: 'Colunas do arquivo' }, ...columnItems.value]
  const fixed = (label: string, options: { label: string; value: string | number; description?: string }[]) =>
    [{ type: 'label' as const, label }, ...options.map(o => ({ ...o, value: `f:${o.value}` }))]
  switch (key) {
    case 'type': return [
      { type: 'label' as const, label: 'Regra' },
      { label: 'Pelo sinal do valor', value: 'm:sign', description: 'negativo = saída' },
      { label: 'Pelo subgrupo', value: 'm:subgroup', description: 'receita = entrada, custo = saída' },
      ...columns, ...fixed('Fixo para todas', TYPE_OPTIONS),
    ]
    case 'subgroup': return [...columns, ...fixed('Fixo para todas', subgroupItems.value)]
    case 'status': return [...columns, ...fixed('Fixo para todas', STATUS_OPTIONS)]
    case 'company': return [...columns, ...fixed('Fixo para todas', lookups.options.companies.value as any)]
    case 'account': return [none, ...columns, ...fixed('Fixo para todas', accountItems.value)]
    case 'date': case 'amount': return columns
    default: return [none, ...columns]
  }
}

function sampleFor(key: FieldKey): string {
  const c = choice[key]
  if (!c || c === 'none') return ''
  if (c.startsWith('c:')) return inspect.value?.columns[Number(c.slice(2))]?.samples.filter(Boolean).slice(0, 2).join(' · ') ?? ''
  return ''
}

const missingRequired = computed(() => FIELDS.filter(f => f.required && (!choice[f.key] || choice[f.key] === 'none')))

function mappingPayload() {
  const columns: Record<string, number> = {}
  const fixed: Record<string, string | number> = {}
  let typeMode = 'column'
  for (const f of FIELDS) {
    const c = choice[f.key]
    if (!c || c === 'none') continue
    if (c.startsWith('c:')) columns[f.key] = Number(c.slice(2))
    else if (c.startsWith('f:')) {
      fixed[f.key] = c.slice(2)
      if (f.key === 'type') typeMode = 'fixed'
    } else if (c.startsWith('m:')) typeMode = c.slice(2)
  }
  const maps = Object.fromEntries(Object.entries(valueMaps).map(([field, m]) => [field,
    Object.fromEntries(Object.entries(m).filter(([, v]) => v !== undefined && v !== ''))]))
  return { columns, fixed, type_mode: typeMode, value_maps: maps, create_contacts: createContacts.value, skip_duplicates: skipDuplicates.value }
}

// Step 3: dry run / import
async function run(commit: boolean) {
  if (!file.value) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    if (sheet.value) form.append('sheet', sheet.value)
    if (headerRow.value) form.append('header_row', String(headerRow.value))
    form.append('mapping', JSON.stringify(mappingPayload()))
    form.append('commit', String(commit))
    const data: Result = await (await raw('/api/transaction-import', { method: 'POST', body: form })).json()
    if (commit) {
      localStorage.setItem(presetKey.value, JSON.stringify({
        choice: { ...choice }, valueMaps: JSON.parse(JSON.stringify(valueMaps)),
        createContacts: createContacts.value, skipDuplicates: skipDuplicates.value,
      }))
      notifySuccess(`${data.created} lançamento(s) importado(s)`)
      lookups.refresh('subgroups').catch(() => {})
      emit('imported')
      open.value = false
    } else {
      result.value = data
      for (const [field, values] of Object.entries(data.unknown)) {
        const seen = (unknownSeen[field] ??= [])
        for (const u of values) {
          const known = seen.find(x => x.value === u.value)
          if (known) known.count = u.count
          else seen.push({ ...u })
        }
      }
      step.value = 3
    }
  } catch (e) {
    notifyError(e)
  } finally {
    busy.value = false
  }
}

// Mapping an unknown value re-runs the preview
let timer: ReturnType<typeof setTimeout> | undefined
watch([() => JSON.stringify(valueMaps), createContacts, skipDuplicates], () => {
  if (step.value !== 3) return
  clearTimeout(timer)
  timer = setTimeout(() => run(false), 350)
})

function unknownItems(field: string) {
  switch (field) {
    case 'type': return TYPE_OPTIONS
    case 'status': return STATUS_OPTIONS
    case 'subgroup': return subgroupItems.value
    case 'company': return lookups.options.companies.value
    case 'account': return accountItems.value
    default: return []
  }
}
function mapValue(field: string, value: string, target: unknown) {
  valueMaps[field] ??= {}
  valueMaps[field]![plain(value).replace(/\s+/g, ' ').trim()] = target as string | number
}
function mappedValue(field: string, value: string) {
  return valueMaps[field]?.[plain(value).replace(/\s+/g, ' ').trim()]
}

const ERROR_LABELS: Record<string, string> = {
  missing: 'vazio', invalid_date: 'data inválida', invalid_amount: 'valor inválido', zero_amount: 'valor zero',
  unknown: 'não reconhecido (mapeie acima)', invalid_fixed: 'valor fixo inválido',
}
const steps = [{ title: 'Arquivo' }, { title: 'Colunas' }, { title: 'Revisar' }]
</script>

<template>
  <UModal v-model:open="open" title="Importar lançamentos" :ui="{ content: 'max-w-5xl' }">
    <template #body>
      <UStepper :model-value="step - 1" :items="steps" size="sm" disabled class="mb-6" />

      <!-- 1. File -->
      <div v-if="step === 1" class="space-y-4">
        <UFileUpload v-model="file" accept=".xlsx,.csv" label="Solte o arquivo .xlsx ou .csv aqui"
                     icon="i-lucide-file-spreadsheet" class="min-h-36 w-full" />
        <div v-if="inspect" class="flex flex-wrap items-end gap-4">
          <UFormField v-if="inspect.sheets.length > 1" label="Aba">
            <USelect v-model="sheet" :items="inspect.sheets" class="w-56" @update:model-value="runInspect" />
          </UFormField>
          <UFormField label="Linha do cabeçalho" hint="Detectada">
            <UInputNumber v-model="headerRow" :min="1" class="w-32" @update:model-value="runInspect" />
          </UFormField>
          <p class="text-sm text-muted pb-2">
            {{ inspect.total_rows.toLocaleString('pt-BR') }} linha(s) ·
            colunas: {{ inspect.columns.map(c => c.header).join(', ') }}
          </p>
        </div>
      </div>

      <!-- 2. Mapping -->
      <div v-else-if="step === 2" class="space-y-3">
        <p class="text-sm text-muted">Para cada campo, escolha uma coluna do arquivo ou um valor fixo.</p>
        <div class="divide-y divide-muted">
          <div v-for="f in FIELDS" :key="f.key" class="grid items-center gap-3 py-2 sm:grid-cols-[12rem_20rem_1fr]">
            <span class="text-sm text-highlighted">
              {{ f.label }}<span v-if="f.required" class="text-error"> *</span>
            </span>
            <USelectMenu v-model="choice[f.key]" :items="itemsFor(f.key)" value-key="value" class="w-full"
                         :aria-label="f.label" :search-input="{ placeholder: 'Buscar…' }" />
            <span class="text-xs text-dimmed truncate">{{ sampleFor(f.key) }}</span>
          </div>
        </div>
        <div class="flex flex-wrap gap-6 pt-2">
          <USwitch v-model="createContacts" label="Cadastrar clientes/fornecedores que não existem" />
          <USwitch v-model="skipDuplicates" label="Pular possíveis duplicados" />
        </div>
      </div>

      <!-- 3. Review -->
      <div v-else-if="result" class="space-y-5" :class="{ 'opacity-60': busy }">
        <div class="grid gap-3 sm:grid-cols-5">
          <SStat label="Válidas" :value="String(result.valid_count)" tone="success" />
          <SStat label="Com erro" :value="String(result.error_count)" :tone="result.error_count ? 'error' : 'default'" />
          <SStat label="Duplicadas" :value="String(result.duplicate_count)" />
          <SStat label="Novos contatos" :value="String(result.new_contacts)" />
          <SStat label="Serão importadas" :value="String(result.to_create)" tone="primary" />
        </div>

        <SPanel v-if="Object.keys(unknownSeen).length" title="Valores não reconhecidos">
          <div class="space-y-4">
            <div v-for="(values, field) in unknownSeen" :key="field">
              <p class="mb-2 text-xs font-medium uppercase tracking-wide text-muted">{{ FIELD_LABEL[field] }}</p>
              <div v-for="u in values" :key="u.value" class="grid items-center gap-3 py-1 sm:grid-cols-[1fr_20rem]">
                <span class="text-sm">
                  <UIcon :name="mappedValue(String(field), u.value) ? 'i-lucide-circle-check' : 'i-lucide-circle-alert'"
                         class="size-4 align-[-3px]" :class="mappedValue(String(field), u.value) ? 'text-success' : 'text-warning'" />
                  "{{ u.value }}" <span class="text-dimmed">· {{ u.count }} linha(s)</span>
                </span>
                <USelectMenu :model-value="mappedValue(String(field), u.value) as any" :items="unknownItems(String(field)) as any"
                             value-key="value" placeholder="Escolher…" class="w-full"
                             @update:model-value="(v: unknown) => mapValue(String(field), u.value, v)" />
              </div>
            </div>
          </div>
        </SPanel>

        <details v-if="result.errors.length" class="s-panel p-4">
          <summary class="cursor-pointer text-sm text-highlighted">
            {{ result.error_count }} linha(s) com erro ficam de fora
            <span v-if="result.error_count > result.errors.length" class="text-dimmed">(mostrando {{ result.errors.length }})</span>
          </summary>
          <table class="mt-3 w-full text-sm">
            <thead class="text-xs text-muted"><tr><th class="text-left py-1">Linha</th><th class="text-left">Campo</th><th class="text-left">Problema</th><th class="text-left">Valor</th></tr></thead>
            <tbody>
              <tr v-for="e in result.errors" :key="`${e.row}-${e.field}`" class="border-t border-muted">
                <td class="py-1 tabular">{{ e.row }}</td><td>{{ FIELD_LABEL[e.field] }}</td>
                <td class="text-error">{{ ERROR_LABELS[e.code] }}</td><td class="text-dimmed">{{ e.value }}</td>
              </tr>
            </tbody>
          </table>
        </details>

        <div v-if="result.preview.length" class="s-panel overflow-auto max-h-80">
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-(--s-solid) text-xs text-muted uppercase">
              <tr>
                <th class="px-3 py-2 text-left">Data</th><th class="px-3 text-left">Subgrupo</th>
                <th class="px-3 text-left">Cliente/Fornecedor</th><th class="px-3 text-left">Empresa / conta</th>
                <th class="px-3 text-left">Status</th><th class="px-3 text-right">Valor</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in result.preview" :key="r.row" class="border-t border-muted" :class="{ 'opacity-50': r.duplicate && skipDuplicates }">
                <td class="px-3 py-1.5 whitespace-nowrap">{{ formatDate(r.date) }}</td>
                <td class="px-3">{{ r.subgroup_name }}</td>
                <td class="px-3 truncate max-w-56">{{ r.contact_name ?? '—' }}</td>
                <td class="px-3 text-muted">{{ r.company_name }}<template v-if="r.account_name"> · {{ r.account_name }}</template></td>
                <td class="px-3">
                  <SStatusBadge kind="status" :value="r.status" />
                  <UBadge v-if="r.duplicate" label="Duplicado" color="warning" variant="subtle" size="sm" class="ms-1" />
                </td>
                <td class="px-3 text-right whitespace-nowrap"><SMoney :value="r.amount" :type="r.type" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="result.valid_count > result.preview.length" class="text-xs text-dimmed">
          Mostrando as primeiras {{ result.preview.length }} de {{ result.valid_count }} linhas válidas.
        </p>
      </div>
    </template>

    <template #footer>
      <div class="flex w-full items-center justify-between gap-2">
        <UButton v-if="step > 1" label="Voltar" icon="i-lucide-arrow-left" color="neutral" variant="ghost"
                 @click="step = (step - 1) as 1 | 2" />
        <span v-else />
        <div class="flex items-center gap-3">
          <span v-if="step === 2 && missingRequired.length" class="text-xs text-error">
            Falta: {{ missingRequired.map(f => f.label).join(', ') }}
          </span>
          <UButton v-if="step === 1" label="Mapear colunas" trailing-icon="i-lucide-arrow-right"
                   :disabled="!inspect || !inspect.total_rows" :loading="busy" @click="step = 2" />
          <UButton v-else-if="step === 2" label="Revisar" trailing-icon="i-lucide-arrow-right"
                   :disabled="missingRequired.length > 0" :loading="busy" @click="run(false)" />
          <UButton v-else :label="`Importar ${result?.to_create ?? 0} lançamento(s)`" icon="i-lucide-file-down"
                   :disabled="!result?.to_create" :loading="busy" @click="run(true)" />
        </div>
      </div>
    </template>
  </UModal>
</template>
