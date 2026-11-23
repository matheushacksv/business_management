<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Event = components['schemas']['EventOut']
definePageMeta({ permission: ['users', 'change'] })

const { api, unwrap, notifyError, notifySuccess } = useApi()
const confirm = useConfirm()
const lookups = useLookups()
lookups.ensure('subgroups').catch(notifyError)
const UBadge = resolveComponent('UBadge')
const UButton = resolveComponent('UButton')

const webhookUrl = computed(() => `${location.origin}/api/webhooks/pipedrive/deal/`)
const copy = (text: string) => navigator.clipboard.writeText(text).then(() => notifySuccess('Copiado'))

// Settings
const config = ref<components['schemas']['PipedriveConfigOut'] | null>(null)
unwrap(api.GET('/api/integrations/pipedrive')).then(c => (config.value = c)).catch(notifyError)
const revenueSubgroups = computed(() => (lookups.cache.value.subgroups ?? [])
  .filter(s => INFLOW_GROUPS.includes(s.group))
  .map(s => ({ label: s.name, value: s.id!, description: lookups.groupLabel(s.group) })))
async function saveSubgroup(subgroupId: number | undefined) {
  try {
    config.value = await unwrap(api.PUT('/api/integrations/pipedrive', { body: { subgroup_id: subgroupId ?? null } }))
    notifySuccess('Salvo')
  } catch (e) {
    notifyError(e)
  }
}

// Credentials: shown once; generating again invalidates the previous ones
const creds = reactive({ open: false, username: '', password: '' })
async function generate() {
  if (config.value?.username && !await confirm({
    title: 'Gerar novas credenciais?', confirmLabel: 'Gerar', color: 'warning',
    description: 'As atuais param de funcionar: atualize a automação no Pipedrive.',
  })) return
  try {
    Object.assign(creds, await unwrap(api.POST('/api/integrations/pipedrive/credentials')), { open: true })
    config.value = await unwrap(api.GET('/api/integrations/pipedrive'))
  } catch (e) {
    notifyError(e)
  }
}

const BODY_TEMPLATE = JSON.stringify({
  deal_id: 0, person_id: 0, person_name: '', person_email: '', person_phone: '', client_document: '',
  company_document: '', proposal_value: '', product: '', owner_name: '', installments: '', payment_method: '',
  notes: '', signed_date: '', down_payment: '', down_payment_date: '', first_installment_date: '',
}, null, 2)

// Event log
const status = ref<string>()
const page = ref(1)
const events = ref<Event[]>([])
const count = ref(0)
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    const data = await unwrap(api.GET('/api/integrations/events', { params: { query: { status: status.value, page: page.value } } }))
    events.value = data.items
    count.value = data.count
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(status, () => { page.value = 1 })
watch([status, page], load, { immediate: true })

async function reprocess(e: Event) {
  try {
    const r = await unwrap(api.POST('/api/integrations/events/{event_id}/reprocess', { params: { path: { event_id: e.id } } }))
    r.status === 'error' ? notifyError(r.message) : notifySuccess(LABEL[r.status]!.label)
    load()
  } catch (err) {
    notifyError(err)
  }
}
const viewing = ref<Event | null>(null)

const LABEL: Record<string, { label: string; color: 'success' | 'neutral' | 'error' }> = {
  processed: { label: 'Processado', color: 'success' },
  ignored: { label: 'Ignorado', color: 'neutral' },
  error: { label: 'Erro', color: 'error' },
}
const columns: TableColumn<Event>[] = [
  { accessorKey: 'received_at', header: 'Recebido', cell: ({ row }) => formatDateTime(row.original.received_at) },
  { accessorKey: 'key', header: 'Origem', cell: ({ row }) => h('div', [
    h('p', { class: 'text-highlighted' }, row.original.source === 'asaas'
      ? `Asaas · ${row.original.payload.event ?? '—'}` : String(row.original.payload.person_name ?? '—')),
    h('p', { class: 'text-xs text-dimmed' }, `#${row.original.key}`),
  ]) },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(UBadge, { ...LABEL[row.original.status], variant: 'subtle' }) },
  { accessorKey: 'message', header: 'Mensagem', cell: ({ row }) => h('p', { class: 'max-w-md whitespace-pre-line text-xs text-muted' }, row.original.message || '—') },
  { id: 'actions', header: '', cell: ({ row }) => h('div', { class: 'flex justify-end gap-1' }, [
    h(UButton, { icon: 'i-lucide-braces', size: 'xs', color: 'neutral', variant: 'ghost', 'aria-label': 'Ver payload',
      onClick: () => (viewing.value = row.original) }),
    row.original.status === 'error' && h(UButton, { label: 'Reprocessar', icon: 'i-lucide-rotate-cw', size: 'xs', variant: 'soft',
      onClick: () => reprocess(row.original) }),
    row.original.sale_id && h(UButton, { icon: 'i-lucide-handshake', size: 'xs', color: 'neutral', variant: 'ghost',
      'aria-label': 'Abrir venda', to: { path: '/sales', query: { sale: row.original.sale_id } } }),
  ]) },
]
</script>

<template>
  <AppPage title="Integrações">
    <SPanel title="Pipedrive">
      <div class="grid gap-4 md:grid-cols-2">
        <UFormField label="URL (POST)">
          <UInput :model-value="webhookUrl" readonly class="w-full">
            <template #trailing>
              <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar URL" @click="copy(webhookUrl)" />
            </template>
          </UInput>
        </UFormField>
        <UFormField label="Usuário">
          <div class="flex gap-2">
            <UInput :model-value="config?.username || '—'" readonly class="flex-1" />
            <UButton :label="config?.username ? 'Gerar novas' : 'Gerar credenciais'" icon="i-lucide-key-round" color="neutral"
                     variant="outline" @click="generate" />
          </div>
        </UFormField>
        <UFormField label="Subgrupo das parcelas">
          <USelectMenu :model-value="config?.subgroup_id ?? undefined" :items="revenueSubgroups" value-key="value"
                       placeholder="Nenhum" class="w-full" @update:model-value="(v: any) => saveSubgroup(v)" />
        </UFormField>
        <UFormField label="Executa como">
          <UInput :model-value="config?.user_email ?? '—'" readonly class="w-full" />
        </UFormField>
      </div>
      <UButton label="Copiar modelo do JSON" icon="i-lucide-braces" color="neutral" variant="outline" size="sm" class="mt-4"
               @click="copy(BODY_TEMPLATE)" />
    </SPanel>
    <IntegrationsAsaas />

    <template #toolbar>
      <USelect v-model="status" :items="Object.entries(LABEL).map(([value, l]) => ({ label: l.label, value }))"
               placeholder="Status" class="w-40" />
      <UButton v-if="status" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Limpar status" @click="status = undefined" />
      <UButton icon="i-lucide-refresh-cw" color="neutral" variant="ghost" aria-label="Atualizar" class="ms-auto" @click="load" />
    </template>

    <div class="s-panel overflow-hidden" :class="{ 'opacity-70': loading }">
      <UTable :data="events" :columns="columns" :loading="loading" empty="Nenhuma chamada recebida" />
    </div>
    <div class="flex items-center justify-between text-sm text-muted">
      <span>{{ count }} chamada(s)</span>
      <UPagination v-if="count > 50" v-model:page="page" :total="count" :items-per-page="50" />
    </div>

    <UModal v-model:open="creds.open" title="Credenciais do webhook">
      <template #body>
        <div class="flex flex-col gap-3">
          <UFormField v-for="[label, value] in [['Nome de usuário autent. HTTP', creds.username], ['Senha autent. HTTP', creds.password]]"
                      :key="label" :label="label">
            <UInput :model-value="value" readonly class="w-full font-mono">
              <template #trailing>
                <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" :aria-label="`Copiar ${label}`" @click="copy(value!)" />
              </template>
            </UInput>
          </UFormField>
        </div>
      </template>
    </UModal>

    <UModal :open="!!viewing" title="Payload recebido" @update:open="(v: boolean) => { if (!v) viewing = null }">
      <template #body>
        <pre class="max-h-[60dvh] overflow-auto rounded-lg bg-elevated p-3 text-xs">{{ JSON.stringify(viewing?.payload, null, 2) }}</pre>
      </template>
    </UModal>
  </AppPage>
</template>
