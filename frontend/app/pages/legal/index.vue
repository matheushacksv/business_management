<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Case = components['schemas']['CaseOut']
definePageMeta({ permission: ['legal', 'view'] })

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const lookups = useLookups()
lookups.ensure('companies', 'legalStages').catch(notifyError)
const UBadge = resolveComponent('UBadge')
const canChange = computed(() => auth.can('legal', 'change'))

const view = ref<'kanban' | 'list'>('kanban')  // remembered per browser
onMounted(() => { if (localStorage.getItem('legal-view') === 'list') view.value = 'list' })
watch(view, v => localStorage.setItem('legal-view', v))
const filters = reactive({ search: '', company_id: [] as number[] })
useQueryFilters(filters)
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
// "Filtro" dropdown: situação and empresas above, plus responsible / agreement (client-side: the list is loaded whole)
const responsible = ref<number | 'none'>()
const agreementFilter = ref<'with' | 'without'>()
const hasAgreement = (c: Case) => !!c.agreement?.trim() || needsAgreement(c.stage_id)
const filtered = computed(() => items.value.filter(c =>
  (responsible.value === undefined || (responsible.value === 'none' ? !c.responsible_id : c.responsible_id === responsible.value))
  && (agreementFilter.value === undefined || hasAgreement(c) === (agreementFilter.value === 'with'))))
const visible = computed(() => filtered.value.filter(c => !!c.closed_at === (status.value === 'done')))
const activeFilters = computed(() => [filters.company_id.length, status.value === 'done', responsible.value !== undefined,
  agreementFilter.value !== undefined].filter(Boolean).length)
function clearFilters() {
  filters.company_id = []
  status.value = 'open'
  responsible.value = undefined
  agreementFilter.value = undefined
}
const people = ref<{ label: string; value: number | 'none' }[]>([])
unwrap(api.GET('/api/collection-case/responsibles'))
  .then(list => (people.value = [{ label: 'Sem responsável', value: 'none' }, ...list.map(p => ({ label: p.name, value: p.id }))]))
  .catch(notifyError)
const sum = (list: Case[]) => list.reduce((s, c) => s + Number(c.due_amount), 0)
const totalOpen = computed(() => sum(visible.value))
const totalReceived = computed(() => filtered.value.reduce((s, c) => s + Number(c.received_amount), 0))
const stages = lookups.options.legalStages
const needsAgreement = (id: number) => !!lookups.cache.value.legalStages?.find(s => s.id === id)?.requires_agreement
const columnsByStage = computed(() => stages.value.map(s => {
  const cards = visible.value.filter(c => c.stage_id === s.value)
  return { ...s, cards, total: sum(cards) }
}))
const isIncomplete = (c: Case) => !c.client_company || !c.contact_info || !c.delivered || !c.summary
  || !c.drive_link || c.proposal_amount == null || c.paid_amount == null

// Drag and drop (native HTML5: no library)
const dragging = ref<number | null>(null)
const over = ref<number | null>(null)
function onDrop(stage: number) {
  over.value = null
  const card = items.value.find(c => c.id === dragging.value)
  dragging.value = null
  if (!card || card.stage_id === stage) return
  if (needsAgreement(stage) && !card.agreement?.trim()) {
    Object.assign(agreement, { case: card, stage, open: true })
    return
  }
  if (lookups.cache.value.legalStages?.find(s => s.id === stage)?.breaks_agreement && hasAgreement(card)) {
    confirmBroken(card, stage)
    return
  }
  if (lookups.cache.value.legalStages?.find(s => s.id === stage)?.requires_process_number && !card.process_number) {
    Object.assign(protocol, { case: card, stage, number: '', open: true })
    return
  }
  move(card, stage)
}

// Stage marked "acordo descumprido": the unpaid agreement installments go back to the legal debt
async function confirmBroken(card: Case, stage: number) {
  if (await confirm({ title: 'Acordo descumprido?', description: 'As parcelas do acordo não pagas voltam para o jurídico.',
    confirmLabel: 'Mover', color: 'warning' })) move(card, stage)
}

// Stages marked "requires process number": asked when the card is dropped there
const protocol = reactive({ open: false, case: null as Case | null, stage: 0, number: '' })
async function confirmProtocol() {
  if (!protocol.number.trim()) return
  if (await move(protocol.case!, protocol.stage, { process_number: protocol.number.trim() })) protocol.open = false
}

async function move(card: Case, stage: number, extra: { process_number?: string } = {}) {
  const previous = card.stage_id
  card.stage_id = stage  // optimistic
  try {
    const saved = await unwrap(api.PATCH('/api/collection-case/{case_id}', {
      params: { path: { case_id: card.id! } }, body: { stage_id: stage, ...extra },
    }))
    Object.assign(card, saved)
    return true
  } catch (e) {
    card.stage_id = previous
    notifyError(e)
    return false
  }
}

// Stages marked "requires agreement": registering it creates its installments (replacing the open ones)
const agreement = reactive({ open: false, case: null as Case | null, stage: 0 })
function agreementSaved(saved: Case) {
  Object.assign(agreement.case!, saved)
  agreement.open = false
}

const listColumns: TableColumn<Case>[] = [
  { accessorKey: 'contact_name', header: 'Cliente', cell: ({ row }) => h('div', [
    h('p', { class: 'text-highlighted truncate max-w-64' }, row.original.contact_name),
    h('p', { class: 'text-xs text-dimmed' }, row.original.client_company || ''),
  ]) },
  { accessorKey: 'stage_name', header: 'Etapa', cell: ({ row }) => h(UBadge, {
    label: row.original.closed_at ? 'Concluída' : row.original.stage_name, color: row.original.closed_at ? 'success' : 'primary', variant: 'subtle',
  }) },
  { accessorKey: 'company_name', header: 'Empresa do grupo' },
  { accessorKey: 'proposal_amount', header: () => h('span', { class: 'block text-right' }, 'Proposta'),
    cell: ({ row }) => h('p', { class: 'text-right tabular' }, row.original.proposal_amount != null ? formatMoney(row.original.proposal_amount) : '—') },
  { accessorKey: 'paid_amount', header: () => h('span', { class: 'block text-right' }, 'Pago'),
    cell: ({ row }) => h('p', { class: 'text-right tabular' }, row.original.paid_amount != null ? formatMoney(row.original.paid_amount) : '—') },
  { accessorKey: 'due_amount', header: () => h('span', { class: 'block text-right' }, 'Devido'),
    cell: ({ row }) => h('p', { class: 'text-right tabular text-error' }, formatMoney(row.original.due_amount)) },
  { accessorKey: 'updated_at', header: 'Atualizado', cell: ({ row }) => formatDate(row.original.updated_at!.slice(0, 10)) },
]

// List view: pick several cases and move them to one stage
const selection = useSelection<Case>(() => visible.value)
const tableColumns = computed(() => canChange.value ? [selection.column, ...listColumns] : listColumns)
const bulkStage = ref<number>()
watch(view, () => selection.clear())
async function moveSelected(stage: number) {
  const cards = selection.rows.value
  const results = await Promise.allSettled(cards.map(c => unwrap(api.PATCH('/api/collection-case/{case_id}', {
    params: { path: { case_id: c.id! } }, body: { stage_id: stage },
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
useQueryOpen('case', openCase, drawerOpen)
function onCreated(id: number) {
  createOpen.value = false
  load()
  openCase(id)
}
</script>

<template>
  <AppPage title="Jurídico">
    <template #actions>
      <UButton v-if="auth.can('legal', 'change')" icon="i-lucide-settings" color="neutral" variant="ghost" to="/legal/stages" aria-label="Configurar" />
      <UButton v-if="auth.can('legal', 'create')" label="Nova ação" icon="i-lucide-plus" class="rounded-full" @click="createOpen = true" />
    </template>
    <template #toolbar>
      <UInput v-model="filters.search" icon="i-lucide-search" placeholder="Cliente, empresa, resumo…" class="w-64" />
      <UPopover :content="{ align: 'start' }">
        <UButton label="Filtro" icon="i-lucide-list-filter" color="neutral" variant="outline" trailing-icon="i-lucide-chevron-down">
          <template v-if="activeFilters" #trailing>
            <UBadge :label="String(activeFilters)" size="sm" variant="subtle" />
          </template>
        </UButton>
        <template #content>
          <div class="flex w-72 flex-col gap-3 p-3">
            <UFormField label="Situação">
              <USelect v-model="status" :items="[{ label: 'Em andamento', value: 'open' }, { label: 'Concluídas', value: 'done' }]" class="w-full" />
            </UFormField>
            <UFormField label="Acordo">
              <USelect v-model="agreementFilter" :items="[{ label: 'Com acordo', value: 'with' }, { label: 'Sem acordo', value: 'without' }]"
                       placeholder="Todos" class="w-full" />
            </UFormField>
            <UFormField label="Responsável jurídico">
              <USelect v-model="responsible" :items="people" placeholder="Todos" class="w-full" />
            </UFormField>
            <UFormField label="Empresas">
              <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple placeholder="Todas" class="w-full" />
            </UFormField>
            <UButton v-if="activeFilters" label="Limpar filtros" icon="i-lucide-x" color="neutral" variant="ghost" size="sm" class="self-end"
                     @click="clearFilters" />
          </div>
        </template>
      </UPopover>
      <div class="ms-auto flex items-center gap-3">
        <span class="text-sm text-muted">Total devido <strong class="text-error tabular">{{ formatMoney(totalOpen) }}</strong></span>
        <UFieldGroup>
          <UButton icon="i-lucide-columns-3" aria-label="Kanban" :color="view === 'kanban' ? 'primary' : 'neutral'" variant="subtle" @click="view = 'kanban'" />
          <UButton icon="i-lucide-list" aria-label="Lista" :color="view === 'list' ? 'primary' : 'neutral'" variant="subtle" @click="view = 'list'" />
        </UFieldGroup>
      </div>
    </template>

    <div class="grid gap-3 sm:grid-cols-3">
      <SStat label="Em aberto" :value="formatMoney(sum(filtered))" tone="error" icon="i-lucide-scale" />
      <SStat label="Recebido" :value="formatMoney(totalReceived)" tone="success" icon="i-lucide-badge-dollar-sign" />
      <SStat label="Honorários pagos" :value="formatMoney(totalReceived * LEGAL_FEE_RATE)" icon="i-lucide-hand-coins" />
    </div>

    <div v-if="view === 'kanban' && status === 'open'" class="grid auto-cols-[minmax(11rem,1fr)] grid-flow-col gap-2 overflow-x-auto pb-2" :class="{ 'opacity-70': loading }">
      <section v-for="col in columnsByStage" :key="col.value"
               class="flex min-w-0 flex-col rounded-xl bg-elevated/50 ring ring-default transition"
               :class="{ 'ring-primary bg-primary/5': over === col.value }"
               @dragover.prevent="over = Number(col.value)" @dragleave="over = over === col.value ? null : over"
               @drop.prevent="onDrop(Number(col.value))">
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
              <span class="tabular text-error">{{ formatMoney(card.due_amount) }}</span>
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
    <UModal v-model:open="agreement.open" title="Acordo ou sentença" :ui="{ content: 'max-w-xl' }">
      <template #body>
        <LegalAgreementForm v-if="agreement.case" :case-id="agreement.case.id!" :stage-id="agreement.stage"
                            @saved="agreementSaved" @cancel="agreement.open = false" />
      </template>
    </UModal>
    <UModal v-model:open="protocol.open" title="Número do processo">
      <template #body>
        <form id="protocol-form" @submit.prevent="confirmProtocol">
          <UInput v-model="protocol.number" autofocus class="w-full" />
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="protocol.open = false" />
          <UButton type="submit" form="protocol-form" label="Mover" :disabled="!protocol.number.trim()" />
        </div>
      </template>
    </UModal>
  </AppPage>
</template>
