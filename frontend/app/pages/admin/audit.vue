<script setup lang="ts">
import type { components } from '~/types/api'

type Event = components['schemas']['HistoryEventOut']
definePageMeta({ permission: ['users', 'view'] })

const { api, unwrap, notifyError } = useApi()
const lookups = useLookups()
await lookups.ensure('users')

const TARGETS: Record<string, string> = {
  transaction: 'Lançamento', invoice: 'Nota fiscal', sale: 'Venda', contact: 'Contato', company: 'Empresa',
  subgroup: 'Subgrupo', account: 'Conta', product: 'Produto', salesperson: 'Equipe', user: 'Usuário', attachment: 'Anexo',
}
const targetOptions = Object.entries(TARGETS).filter(([k]) => k !== 'attachment').map(([value, label]) => ({ value, label }))

const filters = reactive({ user_id: undefined as number | undefined, target: undefined as string | undefined, date_from: '', date_to: '' })
const page = ref(1)
const items = ref<Event[]>([])
const count = ref(0)
const loading = ref(false)
const expanded = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    const query: Record<string, unknown> = { page: page.value }
    for (const [k, v] of Object.entries(filters)) if (v) query[k] = v
    const data = await unwrap(api.GET('/api/history/feed', { params: { query: query as any } }))
    items.value = data.items
    count.value = data.count
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(filters, () => { page.value === 1 ? load() : (page.value = 1) }, { deep: true })
watch(page, load)
onMounted(load)

const changes = (e: Event) => Object.entries(e.changes ?? {}).filter(([f]) => !['updated_at', 'created_at'].includes(f))
</script>

<template>
  <AppPage title="Auditoria">
    <template #toolbar>
      <USelect v-model="filters.user_id" :items="lookups.options.users.value" placeholder="Todos os usuários" class="w-56" />
      <USelect v-model="filters.target" :items="targetOptions" placeholder="Todos os registros" class="w-48" />
      <UInput v-model="filters.date_from" type="date" class="w-40" aria-label="De" />
      <UInput v-model="filters.date_to" type="date" class="w-40" aria-label="Até" />
      <UButton v-if="filters.user_id || filters.target || filters.date_from || filters.date_to" label="Limpar" icon="i-lucide-x"
               color="neutral" variant="ghost" @click="Object.assign(filters, { user_id: undefined, target: undefined, date_from: '', date_to: '' })" />
    </template>

    <div class="s-panel divide-y divide-muted" :class="{ 'opacity-70': loading }">
      <p v-if="!items.length && !loading" class="p-6 text-sm text-dimmed">Nenhuma alteração no período.</p>
      <div v-for="e in items" :key="e.id" class="px-4 py-3">
        <button class="flex w-full items-center gap-3 text-left cursor-pointer" @click="expanded = expanded === e.id ? null : e.id">
          <span class="size-2 rounded-full shrink-0"
                :class="{ insert: 'bg-emerald-400', update: 'bg-sky-400', delete: 'bg-red-400' }[e.action] ?? 'bg-(--ui-text-dimmed)'" />
          <span class="text-sm text-highlighted">
            {{ e.user_email ?? (e.source === 'spreadsheet_import' ? 'Importação' : 'Sistema') }}
          </span>
          <span class="text-sm text-muted">
            {{ (LABELS.action[e.action] ?? e.action).toLowerCase() }} {{ (TARGETS[e.target] ?? e.target).toLowerCase() }} #{{ e.target_id }}
          </span>
          <span class="ms-auto text-xs text-dimmed whitespace-nowrap">{{ formatDateTime(e.created_at) }}</span>
          <UIcon :name="expanded === e.id ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" class="size-4 text-dimmed" />
        </button>
        <div v-if="expanded === e.id" class="mt-2 ms-5 rounded-lg bg-muted p-3 ring ring-muted text-xs space-y-1">
          <template v-if="e.action === 'update' && changes(e).length">
            <p v-for="[field, pair] in changes(e)" :key="field">
              <span class="text-muted">{{ field }}:</span>
              <span class="text-error line-through decoration-red-400/50">{{ (pair as any[])[0] ?? '∅' }}</span>
              →
              <span class="text-success">{{ (pair as any[])[1] ?? '∅' }}</span>
            </p>
          </template>
          <pre v-else class="whitespace-pre-wrap text-dimmed">{{ JSON.stringify(e.data, null, 2) }}</pre>
        </div>
      </div>
    </div>

    <div class="flex items-center justify-between text-sm text-muted">
      <span>{{ count.toLocaleString('pt-BR') }} alteração(ões)</span>
      <UPagination v-if="count > 50" v-model:page="page" :total="count" :items-per-page="50" />
    </div>
  </AppPage>
</template>
