<script setup lang="ts">
import type { components } from '~/types/api'

type Event = components['schemas']['HistoryEventOut']
const props = defineProps<{ target: string; targetId: number }>()

const { api, unwrap, notifyError } = useApi()
const events = ref<Event[]>([])
const loading = ref(false)

// Technical fields that only add noise to the timeline
const HIDDEN = new Set(['updated_at', 'created_at', 'id'])

async function load() {
  loading.value = true
  try {
    events.value = (await unwrap(api.GET('/api/history', {
      params: { query: { target: props.target as any, target_id: props.targetId } },
    }))).reverse()
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}

function changes(event: Event) {
  if (event.action !== 'update') return []
  return Object.entries(event.changes ?? {})
    .filter(([field]) => !HIDDEN.has(field))
    .map(([field, pair]) => ({ field, before: (pair as any[])[0], after: (pair as any[])[1] }))
}

function show(value: unknown) {
  if (value === null || value === undefined || value === '') return '∅'
  return String(value)
}

watch(() => props.targetId, load, { immediate: true })
defineExpose({ load })
</script>

<template>
  <div>
    <USkeleton v-if="loading" class="h-20 w-full" />
    <p v-else-if="!events.length" class="text-sm text-dimmed">Sem histórico.</p>
    <ol v-else class="relative ms-2 border-s border-default">
      <li v-for="event in events" :key="event.id" class="ms-4 pb-5 last:pb-0">
        <span class="absolute -start-1.5 mt-1.5 size-3 rounded-full ring-4 ring-(--ui-bg)"
              :class="{ insert: 'bg-emerald-400', update: 'bg-sky-400', delete: 'bg-red-400' }[event.action] ?? 'bg-(--ui-text-dimmed)'" />
        <p class="text-sm text-highlighted">
          <span class="font-medium">{{ event.user_email ?? (event.source === 'spreadsheet_import' ? 'Importação da planilha' : 'Sistema') }}</span>
          <span class="text-muted"> · {{ LABELS.action[event.action] ?? event.action }}</span>
        </p>
        <p class="text-xs text-dimmed">{{ formatDateTime(event.created_at) }}</p>
        <ul v-if="changes(event).length" class="mt-2 space-y-1 rounded-lg bg-muted p-2 ring ring-muted">
          <li v-for="c in changes(event)" :key="c.field" class="text-xs">
            <span class="text-muted">{{ c.field }}:</span>
            <span class="text-error line-through decoration-red-400/50">{{ show(c.before) }}</span>
            <UIcon name="i-lucide-arrow-right" class="mx-1 size-3 align-middle text-dimmed" />
            <span class="text-success">{{ show(c.after) }}</span>
          </li>
        </ul>
      </li>
    </ol>
  </div>
</template>
