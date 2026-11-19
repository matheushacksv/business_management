<script setup lang="ts">
import type { components } from '~/types/api'

type Card = components['schemas']['CardOut']
definePageMeta({ permission: ['dunning', 'view'] })

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('companies').catch(notifyError)
const { stages, assignees } = useDunning()
const canChange = computed(() => auth.can('dunning', 'change'))

const filters = reactive({ search: '', company_id: [] as number[], assignee_id: undefined as number | undefined })
const items = ref<Card[]>([])
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    const query: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(filters)) if (Array.isArray(v) ? v.length : v) query[k] = v
    items.value = await unwrap(api.GET('/api/dunning/card', { params: { query: query as any } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
let timer: ReturnType<typeof setTimeout> | undefined
watch(filters, () => { clearTimeout(timer); timer = setTimeout(load, 300) }, { deep: true })
onMounted(load)

const sum = (list: Card[]) => list.reduce((s, c) => s + Number(c.overdue_amount), 0)
const openCards = computed(() => items.value.filter(c => !c.closed_at))
const columns = computed(() => stages.value.map(s => {
  const cards = items.value.filter(c => c.stage_id === s.id)
  return { ...s, cards, total: sum(cards) }
}))
const lateActivities = computed(() => openCards.value.reduce((s, c) => s + c.late_activities, 0))

// Drag and drop between open stages (native HTML5); resolved / legal go through the card (confirmation)
const dragging = ref<number | null>(null)
const over = ref<number | null>(null)
async function onDrop(stageId: number) {
  over.value = null
  const card = items.value.find(c => c.id === dragging.value)
  dragging.value = null
  const stage = stages.value.find(s => s.id === stageId)
  if (!card || card.closed_at || card.stage_id === stageId || !stage) return
  if (stage.kind !== 'open') return openCard(card.id)
  const previous = card.stage_id
  card.stage_id = stageId
  try {
    await unwrap(api.PATCH('/api/dunning/card/{card_id}', { params: { path: { card_id: card.id } }, body: { stage_id: stageId } }))
  } catch (e) {
    card.stage_id = previous
    notifyError(e)
  }
}

const selected = ref<number | null>(null)
const modalOpen = ref(false)
function openCard(id: number) {
  selected.value = id
  modalOpen.value = true
}
const initials = (name: string | null | undefined) => (name ?? '').split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(p => p[0]!.toUpperCase()).join('')
</script>

<template>
  <AppPage title="Cobrança">
    <template #toolbar>
      <UInput v-model="filters.search" icon="i-lucide-search" placeholder="Cliente…" class="w-56" />
      <USelectMenu v-model="filters.company_id" :items="lookups.options.companies.value" value-key="value" multiple
                   placeholder="Empresas" class="w-44" />
      <USelectMenu v-model="filters.assignee_id" :items="assignees" value-key="value" placeholder="Responsável" class="w-48" />
      <UButton v-if="filters.assignee_id" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Limpar responsável"
               @click="filters.assignee_id = undefined" />
      <div class="ms-auto flex items-center gap-4 text-sm text-muted">
        <span>Em atraso <strong class="tabular text-error">{{ formatMoney(sum(openCards)) }}</strong></span>
        <span>Cards <strong class="tabular text-highlighted">{{ openCards.length }}</strong></span>
        <span>Atividades atrasadas <strong class="tabular" :class="lateActivities ? 'text-error' : 'text-highlighted'">{{ lateActivities }}</strong></span>
      </div>
    </template>

    <div class="flex gap-3 overflow-x-auto pb-2" :class="{ 'opacity-70': loading }">
      <section v-for="col in columns" :key="col.id"
               class="flex w-72 shrink-0 flex-col rounded-xl bg-elevated/50 ring ring-default transition"
               :class="{ 'ring-primary bg-primary/5': over === col.id }"
               @dragover.prevent="over = col.id" @dragleave="over = over === col.id ? null : over"
               @drop.prevent="onDrop(col.id)">
        <header class="flex items-center justify-between gap-2 border-b border-default px-3 py-2">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-highlighted">{{ col.name }}</p>
            <p class="text-xs text-dimmed tabular">{{ formatMoney(col.total) }}</p>
          </div>
          <UBadge :label="String(col.cards.length)" color="neutral" variant="subtle" size="sm" />
        </header>
        <div class="flex max-h-[calc(100dvh-15rem)] min-h-24 flex-col gap-2 overflow-y-auto p-2">
          <article v-for="card in col.cards" :key="card.id" :draggable="canChange && !card.closed_at"
                   class="cursor-pointer rounded-lg bg-default p-3 text-sm ring ring-default hover:ring-primary/60"
                   :class="{ 'opacity-40': dragging === card.id, 'opacity-60': card.closed_at }"
                   @dragstart="dragging = card.id" @dragend="dragging = null" @click="openCard(card.id)">
            <div class="flex items-start justify-between gap-2">
              <p class="font-medium text-highlighted line-clamp-2">{{ card.contact_name }}</p>
              <UTooltip v-if="card.assignee_name" :text="card.assignee_name">
                <span class="grid size-6 shrink-0 place-items-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary">
                  {{ initials(card.assignee_name) }}
                </span>
              </UTooltip>
            </div>
            <p class="truncate text-xs text-dimmed">{{ card.company_name }} · {{ card.overdue_count }} parcela(s)</p>
            <div class="mt-2 flex items-end justify-between text-xs">
              <span v-if="card.closed_at" class="text-dimmed">{{ formatDate(card.closed_at) }}</span>
              <span v-else-if="card.next_activity" class="flex items-center gap-1 tabular"
                    :class="card.late_activities ? 'text-error' : card.next_activity === today() ? 'text-warning' : 'text-dimmed'">
                <UIcon name="i-lucide-calendar-clock" /> {{ formatDate(card.next_activity) }}
              </span>
              <span v-else class="text-dimmed">{{ daysLate(card.overdue_since) }} dia(s)</span>
              <span class="tabular text-error">{{ formatMoney(card.overdue_amount) }}</span>
            </div>
          </article>
          <p v-if="!col.cards.length" class="py-4 text-center text-xs text-dimmed">Vazio</p>
        </div>
      </section>
    </div>

    <DunningCardModal v-model:open="modalOpen" :card-id="selected" :stages="stages" :assignees="assignees" @changed="load" />
  </AppPage>
</template>
