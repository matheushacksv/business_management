<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Case = components['schemas']['CaseOut']
definePageMeta({ permission: ['legal', 'view'] })

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('companies').catch(notifyError)
const UBadge = resolveComponent('UBadge')
const canChange = computed(() => auth.can('legal', 'change'))

const view = ref<'kanban' | 'list'>('kanban')  // remembered per browser
onMounted(() => { if (localStorage.getItem('legal-view') === 'list') view.value = 'list' })
watch(view, v => localStorage.setItem('legal-view', v))
const filters = reactive({ search: '', company_id: [] as number[] })
const items = ref<Case[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const query: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(filters)) if (Array.isArray(v) ? v.length : v) query[k] = v
    items.value = await unwrap(api.GET('/api/collection-case', { params: { query: query as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
let timer: ReturnType<typeof setTimeout> | undefined
watch(filters, () => { clearTimeout(timer); timer = setTimeout(load, 300) }, { deep: true })
onMounted(load)

// Like won/lost on Pipedrive: concluded actions leave the board, the filter brings them back
const status = ref<'open' | 'done'>('open')
const visible = computed(() => items.value.filter(c => (c.stage === 'done') === (status.value === 'done')))
const sum = (list: Case[]) => list.reduce((s, c) => s + Number(c.open_amount), 0)
const totalOpen = computed(() => sum(visible.value))
const stages = Object.entries(LABELS.caseStage).map(([value, label]) => ({ value, label }))
const columnsByStage = computed(() => stages.filter(s => s.value !== 'done').map(s => {
  const cards = visible.value.filter(c => c.stage === s.value)
  return { ...s, cards, total: sum(cards) }
}))
const isIncomplete = (c: Case) => !c.client_company || !c.contact_info || !c.delivered || !c.summary
  || !c.drive_link || c.proposal_amount == null || c.paid_amount == null

// Drag and drop (native HTML5: no library)
const dragging = ref<number | null>(null)
const over = ref<string | null>(null)
function onDrop(stage: string) {
  over.value = null
  const card = items.value.find(c => c.id === dragging.value)
  dragging.value = null
  if (!card || card.stage === stage) return
  if (stage === 'agreement' && !card.agreement?.trim()) {
    agreement.case = card
    agreement.text = ''
    agreement.open = true
    return
  }
  move(card, stage)
}

async function move(card: Case, stage: string, extra: Record<string, string> = {}) {
  const previous = card.stage
  card.stage = stage  // optimistic
  try {
    const saved = await unwrap(api.PATCH('/api/collection-case/{case_id}', {
      params: { path: { case_id: card.id! } }, body: { stage: stage as any, ...extra },
    }))
    Object.assign(card, saved)
  } catch (e) {
    card.stage = previous
    notifyError(e)
  }
}

// Moving to "Acordo ou Sentença" requires the agreement description
const agreement = reactive({ open: false, text: '', case: null as Case | null })
async function confirmAgreement() {
  if (!agreement.case || !agreement.text.trim()) return
  await move(agreement.case, 'agreement', { agreement: agreement.text })
  agreement.open = false
}

const listColumns: TableColumn<Case>[] = [
  { accessorKey: 'contact_name', header: 'Cliente', cell: ({ row }) => h('div', [
    h('p', { class: 'text-highlighted truncate max-w-64' }, row.original.contact_name),
    h('p', { class: 'text-xs text-dimmed' }, row.original.client_company || ''),
  ]) },
  { accessorKey: 'stage', header: 'Etapa', cell: ({ row }) => h(UBadge, {
    label: LABELS.caseStage[row.original.stage], color: row.original.stage === 'done' ? 'success' : 'primary', variant: 'subtle',
  }) },
  { accessorKey: 'company_name', header: 'Empresa do grupo' },
  { accessorKey: 'proposal_amount', header: () => h('span', { class: 'block text-right' }, 'Proposta'),
    cell: ({ row }) => h('p', { class: 'text-right tabular' }, row.original.proposal_amount != null ? formatMoney(row.original.proposal_amount) : '—') },
  { accessorKey: 'paid_amount', header: () => h('span', { class: 'block text-right' }, 'Pago'),
    cell: ({ row }) => h('p', { class: 'text-right tabular' }, row.original.paid_amount != null ? formatMoney(row.original.paid_amount) : '—') },
  { accessorKey: 'open_amount', header: () => h('span', { class: 'block text-right' }, 'Devido'),
    cell: ({ row }) => h('p', { class: 'text-right tabular text-error' }, formatMoney(row.original.open_amount)) },
  { accessorKey: 'updated_at', header: 'Atualizado', cell: ({ row }) => formatDate(row.original.updated_at!.slice(0, 10)) },
]

// List view: pick several cases and move them to one stage
const selection = useSelection<Case>(() => visible.value)
const tableColumns = computed(() => canChange.value ? [selection.column, ...listColumns] : listColumns)
const bulkStage = ref<string>()
watch(view, () => selection.clear())
async function moveSelected(stage: string) {
  const cards = selection.rows.value
  const results = await Promise.allSettled(cards.map(c => unwrap(api.PATCH('/api/collection-case/{case_id}', {
    params: { path: { case_id: c.id! } }, body: { stage: stage as any },
  }))))
  const failed = results.filter(r => r.status === 'rejected') as PromiseRejectedResult[]
  if (failed.length) notifyError(failed[0]!.reason, `${failed.length} de ${cards.length} não movido(s)`)
  bulkStage.value = undefined
  selection.clear()
  load()
}

const selected = ref<number | null>(null)
const drawerOpen = ref(false)
const createOpen = ref(false)
function openCase(id: number) {
  selected.value = id
  drawerOpen.value = true
}
function onCreated(id: number) {
  createOpen.value = false
  load()
  openCase(id)
}
</script>

<template>
  <AppPage title="Jurídico · Ações">
    <template #actions>
      <UButton v-if="auth.can('legal', 'create')" label="Nova ação" icon="i-lucide-plus" class="rounded-full" @click="createOpen = true" />
    </template>
    <template #toolbar>
      <UInput v-model="filters.search" icon="i-lucide-search" placeholder="Cliente, empresa, resumo…" class="w-64" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple placeholder="Empresas" class="w-44" />
      <USelect v-model="status" :items="[{ label: 'Em andamento', value: 'open' }, { label: 'Concluídas', value: 'done' }]" class="w-40"
               aria-label="Situação" />
      <div class="ms-auto flex items-center gap-3">
        <span class="text-sm text-muted">Total devido <strong class="text-error tabular">{{ formatMoney(totalOpen) }}</strong></span>
        <UFieldGroup>
          <UButton icon="i-lucide-columns-3" aria-label="Kanban" :color="view === 'kanban' ? 'primary' : 'neutral'" variant="subtle" @click="view = 'kanban'" />
          <UButton icon="i-lucide-list" aria-label="Lista" :color="view === 'list' ? 'primary' : 'neutral'" variant="subtle" @click="view = 'list'" />
        </UFieldGroup>
      </div>
    </template>

    <div v-if="view === 'kanban' && status === 'open'" class="grid auto-cols-[minmax(11rem,1fr)] grid-flow-col gap-2 overflow-x-auto pb-2" :class="{ 'opacity-70': loading }">
      <section v-for="col in columnsByStage" :key="col.value"
               class="flex min-w-0 flex-col rounded-xl bg-elevated/50 ring ring-default transition"
               :class="{ 'ring-primary bg-primary/5': over === col.value }"
               @dragover.prevent="over = col.value" @dragleave="over = over === col.value ? null : over"
               @drop.prevent="onDrop(col.value)">
        <header class="flex items-center justify-between gap-2 border-b border-default px-2.5 py-2">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-highlighted">{{ col.label }}</p>
            <p class="text-xs text-dimmed tabular">{{ formatMoney(col.total) }}</p>
          </div>
          <UBadge :label="String(col.cards.length)" color="neutral" variant="subtle" size="sm" />
        </header>
        <div class="flex max-h-[calc(100dvh-15rem)] min-h-24 flex-col gap-1.5 overflow-y-auto p-1.5">
          <article v-for="card in col.cards" :key="card.id!" :draggable="canChange"
                   class="cursor-pointer rounded-lg bg-default p-2.5 text-sm ring ring-default hover:ring-primary/60"
                   :class="{ 'opacity-40': dragging === card.id }"
                   @dragstart="(e: DragEvent) => { e.dataTransfer?.setData('text/plain', String(card.id)); dragging = card.id! }"
                   @dragend="dragging = null" @click="openCase(card.id!)">
            <div class="flex items-start justify-between gap-2">
              <p class="font-medium text-highlighted line-clamp-2">{{ card.contact_name }}</p>
              <UTooltip v-if="isIncomplete(card)" text="Campos obrigatórios pendentes">
                <UIcon name="i-lucide-triangle-alert" class="size-4 shrink-0 text-warning" />
              </UTooltip>
            </div>
            <p v-if="card.client_company" class="text-xs text-dimmed truncate">{{ card.client_company }}</p>
            <UBadge v-if="card.unrecoverable_at" label="Perda" icon="i-lucide-ban" color="neutral" variant="solid" size="sm" class="mt-1" />
            <div class="mt-2 flex flex-wrap items-end justify-between gap-x-2 text-xs">
              <span class="text-dimmed">{{ formatDate(card.updated_at!.slice(0, 10)) }}</span>
              <span class="tabular text-error">{{ formatMoney(card.open_amount) }}</span>
            </div>
          </article>
          <p v-if="!col.cards.length" class="py-4 text-center text-xs text-dimmed">Vazio</p>
        </div>
      </section>
    </div>

    <template v-else>
      <div class="s-panel overflow-hidden" :class="{ 'opacity-70': loading }">
        <UTable :data="visible" :columns="tableColumns" :loading="loading" sticky empty="Nenhuma ação"
                class="max-h-[calc(100dvh-16rem)]" @select="(_: Event, row: any) => openCase(row.original.id)" />
      </div>
      <p class="text-sm text-muted">{{ visible.length }} ação(ões)</p>
      <AppBulkBar :count="selection.ids.value.length" @clear="selection.clear">
        <USelect v-model="bulkStage" :items="stages" placeholder="Mover para…" size="sm" class="w-48"
                 @update:model-value="(v: any) => v && moveSelected(v)" />
      </AppBulkBar>
    </template>

    <LegalDrawer v-model:open="drawerOpen" :case-id="selected" @changed="load" />
    <UModal v-model:open="createOpen" title="Ação de cobrança por inadimplência" :ui="{ content: 'max-w-2xl' }">
      <template #body>
        <LegalForm @saved="onCreated" @cancel="createOpen = false" />
      </template>
    </UModal>
    <UModal v-model:open="agreement.open" title="Acordo ou sentença">
      <template #body>
        <UTextarea v-model="agreement.text" :rows="3" autoresize class="w-full"
                   placeholder="Ex.: R$ 20.000,00 em 10x de R$ 2.000,00, primeiro vencimento dia 10/12" />
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="agreement.open = false" />
          <UButton label="Mover" :disabled="!agreement.text.trim()" @click="confirmAgreement" />
        </div>
      </template>
    </UModal>
  </AppPage>
</template>
