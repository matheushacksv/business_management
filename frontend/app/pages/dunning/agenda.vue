<script setup lang="ts">
import type { components } from '~/types/api'

type Item = components['schemas']['AgendaOut']
definePageMeta({ permission: ['dunning', 'view'] })

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const { stages, assignees } = useDunning()
onMounted(() => notifyPaidOff(() => navigateTo('/dunning?outcome=resolved')).catch(notifyError))

// Default: my activities, if I can be responsible
const assignee = ref<number | undefined>(auth.can('dunning', 'change') ? auth.me.value?.id ?? undefined : undefined)
const items = ref<Item[]>([])
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    items.value = await unwrap(api.GET('/api/dunning/agenda', { params: { query: { assignee_id: assignee.value } } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(assignee, load, { immediate: true })

const late = computed(() => items.value.filter(a => a.due_date < today()))
const todays = computed(() => items.value.filter(a => a.due_date === today()))

const selected = ref<number | null>(null)
const modalOpen = ref(false)
function openCard(id: number) {
  selected.value = id
  modalOpen.value = true
}
</script>

<template>
  <AppPage title="Agenda de cobrança">
    <template #toolbar>
      <USelectMenu v-model="assignee" :items="assignees" value-key="value" placeholder="Todos" class="w-56" />
      <UButton v-if="assignee" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Todos" @click="assignee = undefined" />
    </template>

    <div class="grid gap-4 lg:grid-cols-2" :class="{ 'opacity-70': loading }">
      <SPanel v-for="group in [{ title: 'Atrasadas', list: late, tone: 'text-error' }, { title: 'Hoje', list: todays, tone: 'text-warning' }]"
              :key="group.title" :title="`${group.title} · ${group.list.length}`">
        <ul class="flex flex-col divide-y divide-muted">
          <li v-for="a in group.list" :key="a.id" class="flex cursor-pointer items-start gap-3 py-2 text-sm hover:bg-elevated/50"
              @click="openCard(a.card_id)">
            <UIcon :name="DUNNING_LABELS.activityIcon[a.kind]!" class="mt-0.5 size-4 shrink-0 text-muted" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-highlighted">{{ a.contact_name }}</p>
              <p class="truncate text-xs text-dimmed">{{ a.title }} · {{ a.company_name }}{{ a.assignee_name ? ` · ${a.assignee_name}` : '' }}</p>
            </div>
            <span class="text-xs tabular" :class="group.tone">{{ formatDate(a.due_date) }}</span>
          </li>
          <li v-if="!group.list.length" class="py-2 text-sm text-dimmed">Nada.</li>
        </ul>
      </SPanel>
    </div>

    <DunningCardModal v-model:open="modalOpen" :card-id="selected" :stages="stages" :assignees="assignees" @changed="load" />
  </AppPage>
</template>
