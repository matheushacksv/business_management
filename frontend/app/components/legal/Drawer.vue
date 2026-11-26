<script setup lang="ts">
import type { components } from '~/types/api'

type Case = components['schemas']['CaseOut']
type Comment = components['schemas']['CommentOut']
type Transaction = components['schemas']['TransactionOut']
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ caseId: number | null }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const canChange = computed(() => auth.can('legal', 'change'))

const item = ref<Case | null>(null)
const comments = ref<Comment[]>([])
const installments = ref<Transaction[]>([])
const tab = ref('summary')
const editing = ref(false)

// Admins settle an installment here (same as on the transaction: Bling NF-e, dunning card)
const realizing = ref<number | null>(null)
async function realize(t: Transaction) {
  realizing.value = t.id!
  try {
    await unwrap(api.PATCH('/api/transaction/{transaction_id}', { params: { path: { transaction_id: t.id! } }, body: { status: 'realized' } }))
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  } finally {
    realizing.value = null
  }
}
// Progress (comments) lives in its own column, always visible
const tabs = [
  { label: 'Resumo', value: 'summary', icon: 'i-lucide-file-text' },
  { label: 'Checklist', value: 'checklist', icon: 'i-lucide-list-checks' },
  { label: 'Parcelas', value: 'installments', icon: 'i-lucide-calendar-range' },
  { label: 'Documentos', value: 'documents', icon: 'i-lucide-paperclip' },
]

async function load() {
  if (!props.caseId) return
  const path = { case_id: props.caseId }
  try {
    ;[item.value, comments.value, installments.value] = await Promise.all([
      unwrap(api.GET('/api/collection-case/{case_id}', { params: { path } })),
      unwrap(api.GET('/api/collection-case/{case_id}/comments', { params: { path } })),
      unwrap(api.GET('/api/collection-case/{case_id}/transactions', { params: { path } })),
    ])
  } catch (e) {
    notifyError(e)
  }
}
watch(() => [props.caseId, open.value], () => {
  if (open.value) { item.value = null; tab.value = 'summary'; editing.value = false; load() }
}, { immediate: true })

const text = ref('')
const sending = ref(false)
async function addComment() {
  if (!text.value.trim() || !item.value) return
  sending.value = true
  try {
    await unwrap(api.POST('/api/collection-case/{case_id}/comments', {
      params: { path: { case_id: item.value.id! } }, body: { text: text.value },
    }))
    text.value = ''
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  } finally {
    sending.value = false
  }
}

async function saved() {
  editing.value = false
  await load()
  emit('changed')
}

// Loss: separate from the stage (sent to legal is not the same as unrecoverable)
async function toggleUnrecoverable() {
  const mark = !item.value!.unrecoverable_at
  if (mark && !await confirm({ title: 'Marcar como irrecuperável?', confirmLabel: 'Marcar', color: 'error' })) return
  try {
    item.value = await unwrap(api.PATCH('/api/collection-case/{case_id}', {
      params: { path: { case_id: props.caseId! } }, body: { unrecoverable: mark },
    }))
    emit('changed')
    load()
  } catch (e) {
    notifyError(e)
  }
}

// Concluding takes the action off the board (filter "Concluídas" brings it back)
async function setDone(done: boolean) {
  if (done && !await confirm({ title: 'Concluir ação?', confirmLabel: 'Concluir' })) return
  try {
    item.value = await unwrap(api.PATCH('/api/collection-case/{case_id}', {
      params: { path: { case_id: props.caseId! } }, body: { closed: done },
    }))
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

async function remove() {
  if (!item.value) return
  const ok = await confirm({
    title: 'Excluir ação?',
    description: 'As parcelas vinculadas continuam lançadas e voltam para a DRE e o fluxo de caixa.',
    confirmLabel: 'Excluir', color: 'error', icon: 'i-lucide-trash-2',
  })
  if (!ok) return
  try {
    await unwrap(api.DELETE('/api/collection-case/{case_id}', { params: { path: { case_id: item.value.id! } } }))
    notifySuccess('Ação excluída')
    open.value = false
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

// Imported cases come without the required fields: flag it
const incomplete = computed(() => !!item.value && (!item.value.client_company || !item.value.contact_info
  || !item.value.delivered || !item.value.summary || !item.value.drive_link
  || item.value.proposal_amount == null || item.value.paid_amount == null))
</script>

<template>
  <UModal v-model:open="open" :title="item?.contact_name ?? 'Ação'"
          :description="item ? `${item.closed_at ? 'Concluída' : item.stage_name} · ${item.company_name}` : undefined"
          :ui="{ content: 'sm:max-w-6xl' }">
    <template #body>
      <USkeleton v-if="!item" class="h-40 w-full" />
      <div v-else class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <div class="min-w-0 space-y-5">
        <div class="s-panel grid grid-cols-2 gap-x-4 gap-y-3 p-4 text-xs">
          <div class="min-w-0"><p class="text-dimmed">Devido (em aberto)</p><p class="font-display text-lg text-error tabular truncate">{{ formatMoney(item.open_amount) }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Recebido (parcelas)</p><p class="font-display text-lg text-success tabular truncate">{{ formatMoney(item.received_amount) }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Valor da proposta</p><p class="text-sm text-highlighted tabular truncate">{{ item.proposal_amount != null ? formatMoney(item.proposal_amount) : '—' }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Pago pelo cliente</p><p class="text-sm text-highlighted tabular truncate">{{ item.paid_amount != null ? formatMoney(item.paid_amount) : '—' }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Honorários (20%)</p><p class="text-sm text-highlighted tabular truncate">{{ (formatMoney((Number(item.open_amount) + Number(item.received_amount)) * LEGAL_FEE_RATE)) }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Honorários pagos</p><p class="text-sm text-highlighted tabular truncate">{{ formatMoney(Number(item.received_amount) * LEGAL_FEE_RATE) }}</p></div>
        </div>

        <div v-if="item.unrecoverable_at || canChange" class="flex items-center justify-between gap-2">
          <UBadge v-if="item.unrecoverable_at" color="neutral" variant="solid" icon="i-lucide-ban"
                  :label="`Irrecuperável desde ${formatDate(item.unrecoverable_at)}${item.unrecoverable_by_name ? ` · ${item.unrecoverable_by_name}` : ''}`" />
          <span v-else />
          <UButton v-if="canChange" :label="item.unrecoverable_at ? 'Desmarcar irrecuperável' : 'Marcar irrecuperável'"
                   icon="i-lucide-ban" size="xs" color="neutral" variant="ghost" @click="toggleUnrecoverable" />
        </div>

        <UAlert v-if="incomplete && !editing" color="warning" variant="subtle" icon="i-lucide-triangle-alert"
                title="Ação incompleta" />

        <UTabs v-model="tab" :items="tabs" :content="false" size="sm" class="w-full" />

        <template v-if="tab === 'summary'">
          <LegalForm v-if="editing" :item="item" @saved="saved" @cancel="editing = false" />
          <template v-else>
            <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div>
                <dt class="text-xs text-dimmed">Cliente</dt>
                <dd><NuxtLink :to="`/registers/contacts/${item.contact_id}`" class="text-primary hover:underline">{{ item.contact_name }}</NuxtLink></dd>
              </div>
              <div><dt class="text-xs text-dimmed">Empresa</dt><dd>{{ item.client_company || '—' }}</dd></div>
              <div><dt class="text-xs text-dimmed">Contato</dt><dd>{{ item.contact_info || '—' }}</dd></div>
              <div>
                <dt class="text-xs text-dimmed">Link do drive</dt>
                <dd><a v-if="item.drive_link" :href="item.drive_link" target="_blank" rel="noopener" class="text-primary hover:underline">Abrir pasta</a><span v-else>—</span></dd>
              </div>
              <div class="col-span-2"><dt class="text-xs text-dimmed">O que foi entregue</dt><dd class="whitespace-pre-line">{{ item.delivered || '—' }}</dd></div>
              <div class="col-span-2"><dt class="text-xs text-dimmed">Resumo da situação</dt><dd class="whitespace-pre-line">{{ item.summary || '—' }}</dd></div>
              <div v-if="item.agreement" class="col-span-2"><dt class="text-xs text-dimmed">Acordo ou sentença</dt><dd class="whitespace-pre-line">{{ item.agreement }}</dd></div>
            </dl>
            <div class="flex gap-2">
              <UButton v-if="canChange" label="Editar" icon="i-lucide-pencil" @click="editing = true" />
              <UButton v-if="canChange" :label="item.closed_at ? 'Reabrir' : 'Concluir'"
                       :icon="item.closed_at ? 'i-lucide-rotate-ccw' : 'i-lucide-circle-check'" color="success" variant="soft"
                       @click="setDone(!item.closed_at)" />
              <UButton v-if="auth.can('legal', 'delete')" label="Excluir" icon="i-lucide-trash-2" color="error" variant="ghost" @click="remove" />
            </div>
          </template>
        </template>

        <LegalChecklist v-else-if="tab === 'checklist'" :item="item" @changed="saved" />

        <AppAttachments v-else-if="tab === 'documents'" target="collection_case" :target-id="item.id!" :editable="canChange" />

        <template v-else>
          <ul v-if="installments.length" class="divide-y divide-muted rounded-xl ring ring-default">
            <li v-for="t in installments" :key="t.id!" class="flex items-center gap-3 px-3 py-2 text-sm">
              <span class="w-24 text-muted tabular">{{ formatDate(t.date) }}</span>
              <span class="flex-1 truncate">{{ t.reference || t.subgroup_name }}</span>
              <SStatusBadge kind="status" :value="t.status" />
              <SMoney :value="t.amount" class="w-28 text-right" />
              <UButton v-if="auth.me.value?.is_admin && t.status === 'planned'" icon="i-lucide-check" color="success" variant="ghost"
                       size="xs" aria-label="Marcar como realizado" :loading="realizing === t.id" @click="realize(t)" />
            </li>
          </ul>
          <p v-else class="text-sm text-dimmed">Nenhuma parcela vinculada.</p>
        </template>
      </div>

      <SPanel title="Andamento" class="lg:sticky lg:top-0">
        <form class="flex flex-col gap-2" @submit.prevent="addComment">
          <UTextarea v-model="text" :rows="3" autoresize placeholder="Comentário ou observação do andamento…" class="w-full" />
          <UButton type="submit" label="Comentar" icon="i-lucide-send" :loading="sending" :disabled="!text.trim()" class="self-end" />
        </form>
        <ul class="mt-4 max-h-[60dvh] space-y-3 overflow-y-auto">
          <li v-for="c in comments" :key="c.id!" class="rounded-lg bg-elevated/50 p-3 text-sm ring ring-default">
            <p class="mb-1 text-xs text-dimmed">{{ c.author_name ?? 'Sistema' }} · {{ new Date(c.created_at!).toLocaleString('pt-BR') }}</p>
            <p class="whitespace-pre-line">{{ c.text }}</p>
          </li>
        </ul>
      </SPanel>
      </div>
    </template>
  </UModal>
</template>
