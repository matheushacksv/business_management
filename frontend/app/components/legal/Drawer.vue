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
  { label: 'Acordo', value: 'installments', icon: 'i-lucide-calendar-range' },
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

async function refresh() {
  await load()
  emit('changed')
}

async function saved() {
  editing.value = false
  await refresh()
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

// Agreement: registering creates its installments; breaking it cancels the open ones and the lawsuit goes on
const lookups = useLookups()
lookups.ensure('legalStages').catch(notifyError)
const stages = computed(() => lookups.cache.value.legalStages ?? [])
// One agreement at a time: a new one only after the current is marked as broken
const inAgreement = computed(() => !!item.value?.agreement?.trim()
  || !!stages.value.find(s => s.id === item.value?.stage_id)?.requires_agreement)
const agreementOpen = ref(false)
async function agreementSaved() {
  agreementOpen.value = false
  await refresh()
}
const broken = reactive({ open: false, stage: undefined as number | undefined, saving: false })
const brokenOptions = computed(() => stages.value.filter(s => !s.requires_agreement).map(s => ({ label: s.name, value: s.id })))
async function breakAgreement() {
  broken.saving = true
  try {
    await unwrap(api.POST('/api/collection-case/{case_id}/broken-agreement', { params: { path: { case_id: item.value!.id! } }, body: { stage_id: broken.stage! } }))
    broken.open = false
    await refresh()
  } catch (e) {
    notifyError(e)
  } finally {
    broken.saving = false
  }
}

// Legal responsible: in the modal header (also ticks its checklist item)
const people = ref<{ label: string; value: number }[]>([])
unwrap(api.GET('/api/collection-case/responsibles'))
  .then(list => (people.value = list.map(p => ({ label: p.name, value: p.id })))).catch(notifyError)
async function setResponsible(id: number | null) {
  try {
    await unwrap(api.PATCH('/api/collection-case/{case_id}', { params: { path: { case_id: item.value!.id! } }, body: { responsible_id: id } }))
    await refresh()
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
    <template #actions>
      <USelect v-if="item" :model-value="item.responsible_id ?? undefined" :items="people" :disabled="!canChange"
               placeholder="Responsável jurídico" aria-label="Responsável jurídico" icon="i-lucide-user-round" class="ms-auto me-10 w-72"
               @update:model-value="(v: any) => setResponsible(v ?? null)" />
    </template>
    <template #body>
      <USkeleton v-if="!item" class="h-40 w-full" />
      <div v-else class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <div class="min-w-0 space-y-5">
        <div class="s-panel grid grid-cols-2 gap-x-4 gap-y-3 p-4 text-xs">
          <div class="min-w-0"><p class="text-dimmed">Devido (em aberto)</p><p class="font-display text-lg text-error tabular truncate">{{ formatMoney(item.due_amount) }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Recebido (acordo)</p><p class="font-display text-lg text-success tabular truncate">{{ formatMoney(item.received_amount) }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Valor da proposta</p><p class="text-sm text-highlighted tabular truncate">{{ item.proposal_amount != null ? formatMoney(item.proposal_amount) : '—' }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Pago pelo cliente</p><p class="text-sm text-highlighted tabular truncate">{{ item.paid_amount != null ? formatMoney(item.paid_amount) : '—' }}</p></div>
          <div class="min-w-0"><p class="text-dimmed">Honorários do acordo (20%)</p><p class="text-sm text-highlighted tabular truncate">{{ formatMoney((Number(item.open_amount) + Number(item.received_amount)) * LEGAL_FEE_RATE) }}</p></div>
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

        <!-- Kept alive across tabs: ticking the checklist mid-edit must not lose what was typed -->
        <LegalForm v-if="editing" v-show="tab === 'summary'" :item="item" @saved="saved" @cancel="editing = false" />
        <template v-if="tab === 'summary'">
          <template v-if="!editing">
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
              <div><dt class="text-xs text-dimmed">Nº do processo</dt><dd class="tabular">{{ item.process_number || '—' }}</dd></div>
              <div class="col-span-2"><dt class="text-xs text-dimmed">O que foi entregue</dt><dd class="whitespace-pre-line">{{ item.delivered || '—' }}</dd></div>
              <div class="col-span-2"><dt class="text-xs text-dimmed">Resumo da situação</dt><dd class="whitespace-pre-line">{{ item.summary || '—' }}</dd></div>
              <div v-if="item.agreement" class="col-span-2"><dt class="text-xs text-dimmed">Acordo ou sentença</dt><dd class="whitespace-pre-line">{{ item.agreement }}</dd></div>
            </dl>
            <div class="flex gap-2">
              <UButton v-if="canChange" label="Editar" icon="i-lucide-pencil" @click="editing = true" />
              <UButton v-if="canChange && !item.closed_at && !inAgreement" label="Registrar acordo" icon="i-lucide-handshake" color="neutral" variant="soft"
                       @click="agreementOpen = true" />
              <UButton v-if="canChange && inAgreement" label="Acordo descumprido" icon="i-lucide-circle-x" color="warning" variant="soft"
                       @click="broken.open = true" />
              <UButton v-if="canChange" :label="item.closed_at ? 'Reabrir' : 'Concluir'"
                       :icon="item.closed_at ? 'i-lucide-rotate-ccw' : 'i-lucide-circle-check'" color="success" variant="soft"
                       @click="setDone(!item.closed_at)" />
              <UButton v-if="auth.can('legal', 'delete')" label="Excluir" icon="i-lucide-trash-2" color="error" variant="ghost" @click="remove" />
            </div>
          </template>
        </template>

        <LegalChecklist v-else-if="tab === 'checklist'" :item="item" @changed="refresh" />

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
          <p v-else class="text-sm text-dimmed">Nenhum acordo registrado.</p>
        </template>
      </div>

      <SPanel title="Andamento" class="lg:sticky lg:top-0">
        <form class="flex flex-col gap-2" @submit.prevent="addComment">
          <UTextarea v-model="text" :rows="3" autoresize placeholder="Comentário ou observação do andamento…" class="w-full" />
          <UButton type="submit" label="Comentar" icon="i-lucide-send" :loading="sending" :disabled="!text.trim()" class="self-end" />
        </form>
        <ul class="mt-4 max-h-[60dvh] space-y-3 overflow-y-auto">
          <template v-for="c in comments" :key="c.id!">
            <li v-if="c.is_log" class="flex gap-2 px-1 text-xs text-muted">
              <UIcon name="i-lucide-history" class="mt-0.5 size-3.5 shrink-0 text-dimmed" />
              <div class="min-w-0">
                <p class="whitespace-pre-line">{{ c.text }}</p>
                <p class="mt-0.5 text-dimmed">{{ c.author_name ?? 'Sistema' }} · {{ new Date(c.created_at!).toLocaleString('pt-BR') }}</p>
              </div>
            </li>
            <li v-else class="rounded-lg bg-elevated/50 p-3 text-sm ring ring-default">
              <p class="mb-1 flex items-center gap-1.5 text-xs text-dimmed">
                <UIcon name="i-lucide-message-square" class="size-3.5" />
                {{ c.author_name ?? 'Sistema' }} · {{ new Date(c.created_at!).toLocaleString('pt-BR') }}
              </p>
              <p class="whitespace-pre-line text-highlighted">{{ c.text }}</p>
            </li>
          </template>
        </ul>
      </SPanel>
      </div>
    </template>
  </UModal>

  <UModal v-model:open="agreementOpen" title="Registrar acordo" :ui="{ content: 'max-w-xl' }">
    <template #body>
      <LegalAgreementForm v-if="item" :case-id="item.id!" @saved="agreementSaved" @cancel="agreementOpen = false" />
    </template>
  </UModal>
  <UModal v-model:open="broken.open" title="Acordo descumprido">
    <template #body>
      <UFormField label="Voltar para a etapa" required>
        <USelect v-model="broken.stage" :items="brokenOptions" class="w-full" />
      </UFormField>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton label="Cancelar" color="neutral" variant="ghost" @click="broken.open = false" />
        <UButton label="Confirmar" color="warning" :loading="broken.saving" :disabled="!broken.stage" @click="breakAgreement" />
      </div>
    </template>
  </UModal>
</template>