<script setup lang="ts">
import type { components } from '~/types/api'

type Card = components['schemas']['CardOut']
type Activity = components['schemas']['ActivityOut']
type Installment = components['schemas']['InstallmentOut']
type Stage = components['schemas']['StageOut']

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ cardId: number | null; stages: Stage[]; assignees: { label: string; value: number }[] }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const canChange = computed(() => auth.can('dunning', 'change'))

const card = ref<Card | null>(null)
const activities = ref<Activity[]>([])
const installments = ref<Installment[]>([])
const notes = ref<components['schemas']['NoteOut'][]>([])
async function load() {
  if (!props.cardId) return
  const path = { card_id: props.cardId }
  try {
    ;[card.value, activities.value, installments.value, notes.value] = await Promise.all([
      unwrap(api.GET('/api/dunning/card/{card_id}', { params: { path } })),
      unwrap(api.GET('/api/dunning/card/{card_id}/activities', { params: { path } })),
      unwrap(api.GET('/api/dunning/card/{card_id}/installments', { params: { path } })),
      unwrap(api.GET('/api/dunning/card/{card_id}/notes', { params: { path } })),
    ])
  } catch (e) {
    notifyError(e)
  }
}
watch(() => [open.value, props.cardId], () => { if (open.value) load() }, { immediate: true })

const note = reactive({ text: '', sending: false })
async function addNote() {
  if (!note.text.trim()) return
  note.sending = true
  try {
    const created = await unwrap(api.POST('/api/dunning/card/{card_id}/notes', {
      params: { path: { card_id: props.cardId! } }, body: { text: note.text },
    }))
    notes.value.unshift(created)
    note.text = ''
  } catch (e) {
    notifyError(e)
  } finally {
    note.sending = false
  }
}

const stageItems = computed(() => props.stages.map(s => ({ label: s.name, value: s.id })))
async function patchCard(body: { stage_id?: number; assignee_id?: number | null; outcome?: 'resolved' | 'legal'; legal_case_id?: number; paid_on?: string }) {
  try {
    card.value = await unwrap(api.PATCH('/api/dunning/card/{card_id}', { params: { path: { card_id: props.cardId! } }, body }))
    emit('changed')
    if (card.value.closed_at) await load()
  } catch (e) {
    notifyError(e)
    load()
  }
}
const changeStage = (stageId: number) => patchCard({ stage_id: stageId })

// Resolver: paid | renegotiated (new terms replace the open installments) | legal
const resolveItems = computed(() => [
  { label: 'Pagou', icon: 'i-lucide-badge-check', onSelect: resolve },
  { label: 'Renegociação', icon: 'i-lucide-refresh-cw', onSelect: () => Object.assign(reneg, { open: true, total: undefined, down_payment: undefined, down_payment_date: '', count: 1, first_due: '', close_contract: false }) },
  ...(auth.can('legal', 'create') ? [{ label: 'Jurídico', icon: 'i-lucide-scale', onSelect: () => { legalOpen.value = true } }] : []),
])
const reneg = reactive({ open: false, saving: false, total: undefined as number | undefined, down_payment: undefined as number | undefined,
  down_payment_date: '', count: 1, first_due: '', close_contract: false })
const renegInstallment = computed(() => reneg.total ? Math.max(reneg.total - (reneg.down_payment ?? 0), 0) / reneg.count : 0)
const renegReady = computed(() => renegInstallment.value > 0 && !!reneg.first_due && (!reneg.down_payment || !!reneg.down_payment_date))
async function renegotiate() {
  reneg.saving = true
  try {
    card.value = await unwrap(api.POST('/api/dunning/card/{card_id}/renegotiate', {
      params: { path: { card_id: props.cardId! } },
      body: { total: reneg.total!.toFixed(2), count: reneg.count, first_due: reneg.first_due, close_contract: reneg.close_contract,
        down_payment: reneg.down_payment ? reneg.down_payment.toFixed(2) : null, down_payment_date: reneg.down_payment ? reneg.down_payment_date : null },
    }))
    reneg.open = false
    emit('changed')
    await load()
  } catch (e) {
    notifyError(e)
  } finally {
    reneg.saving = false
  }
}

// Partial payment: the installment becomes two (this part, maybe paid now, + the rest on a new date)
const split = reactive({ open: false, saving: false, item: null as Installment | null, amount: undefined as number | undefined,
  date: '', paid: true, rest_date: '' })
function openSplit(i: Installment) {
  const today = new Date().toLocaleDateString('sv-SE')
  Object.assign(split, { open: true, item: i, amount: undefined, date: today, paid: true, rest_date: '' })
}
const splitRest = computed(() => split.item ? Number(split.item.amount) - (split.amount ?? 0) : 0)
const splitReady = computed(() => !!split.amount && splitRest.value > 0 && !!split.date && !!split.rest_date)
async function confirmSplit() {
  split.saving = true
  try {
    await unwrap(api.POST('/api/transaction/{transaction_id}/split', {
      params: { path: { transaction_id: split.item!.id } },
      body: { amount: split.amount!.toFixed(2), date: split.date, paid: split.paid, rest_date: split.rest_date },
    }))
    split.open = false
    emit('changed')
    await load()
  } catch (e) {
    notifyError(e)
  } finally {
    split.saving = false
  }
}

// Resolved = paid: late installments are settled on the payment date (shows them first)
const resolving = reactive({ open: false, date: '', saving: false })
function resolve() {
  if (!installments.value.length) return patchCard({ outcome: 'resolved' })
  Object.assign(resolving, { open: true, date: new Date().toLocaleDateString('sv-SE') })
}
async function confirmResolve() {
  resolving.saving = true
  await patchCard({ outcome: 'resolved', paid_on: resolving.date })
  resolving.saving = false
  if (card.value?.closed_at) resolving.open = false
}

// Outcomes take the card off the board (like won/lost on Pipedrive). Legal: the action form
// (every field required) opens the case first, then the card closes linked to it
const legalOpen = ref(false)
async function toLegal(caseId: number) {
  legalOpen.value = false
  await patchCard({ outcome: 'legal', legal_case_id: caseId })
}
async function dismiss() {
  if (!await confirm({
    title: 'Excluir card?', confirmLabel: 'Excluir', color: 'error', icon: 'i-lucide-trash-2',
    description: 'O cliente só volta ao funil quando vencer uma parcela nova.',
  })) return
  try {
    await unwrap(api.DELETE('/api/dunning/card/{card_id}', { params: { path: { card_id: props.cardId! } } }))
    notifySuccess('Card excluído')
    open.value = false
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

// Messages: placeholders filled with the card values; copy or open WhatsApp
const text = (a: Activity) => card.value ? fillTemplate(a.message, card.value) : a.message
const whatsapp = (a: Activity) => {
  const phone = card.value?.contact_phone.replace(/\D/g, '')
  if (!phone) return undefined
  return `https://wa.me/${phone.length <= 11 ? `55${phone}` : phone}?text=${encodeURIComponent(text(a))}`
}
const copy = (value: string) => navigator.clipboard.writeText(value).then(() => notifySuccess('Copiado'))

// Complete: did the customer answer? + notes
const done = reactive({ id: null as number | null, answered: true, notes: '' })
function startDone(a: Activity) {
  Object.assign(done, { id: a.id, answered: true, notes: '' })
}
async function patchActivity(a: Activity, body: Record<string, unknown>) {
  try {
    await unwrap(api.PATCH('/api/dunning/activity/{activity_id}', { params: { path: { activity_id: a.id } }, body }))
    done.id = null
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}
async function removeActivity(a: Activity) {
  if (!await confirm({ title: `Excluir "${a.title}"?`, confirmLabel: 'Excluir', color: 'error' })) return
  try {
    await unwrap(api.DELETE('/api/dunning/activity/{activity_id}', { params: { path: { activity_id: a.id } } }))
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

const form = reactive({ open: false, kind: 'call' as Activity['kind'], title: '', due_date: today(), message: '' })
const kindItems = Object.entries(DUNNING_LABELS.activityKind).map(([value, label]) => ({ label, value }))
async function addActivity() {
  try {
    await unwrap(api.POST('/api/dunning/card/{card_id}/activities', {
      params: { path: { card_id: props.cardId! } },
      body: { kind: form.kind, title: form.title, due_date: form.due_date, message: form.message },
    }))
    Object.assign(form, { open: false, title: '', message: '', due_date: today() })
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

// API4COM: an answered call (real conversation) completes the activity; calls listed in the "Ligações" panel
const { calling, call } = usePhoneCall()
const callsList = ref<{ load: () => void; dial: () => void; calling: boolean } | null>(null)
const callingId = ref<number | null>(null)
function callFor(a: Activity) {
  callingId.value = a.id
  call({ activity_id: a.id }, () => { callsList.value?.load(); load(); emit('changed') })
}

const pending = computed(() => activities.value.filter(a => !a.done_at))
const history = computed(() => activities.value.filter(a => a.done_at))
const isOpen = computed(() => !!card.value && !card.value.closed_at)
</script>

<template>
  <UModal v-model:open="open" :title="card?.contact_name ?? 'Cobrança'" :ui="{ content: 'sm:max-w-5xl' }">
    <template #body>
      <USkeleton v-if="!card" class="h-40 w-full" />
      <div v-else class="space-y-5">
        <div class="s-panel grid gap-4 p-4 sm:grid-cols-4">
          <div>
            <p class="text-xs text-dimmed">Em atraso</p>
            <p class="font-display text-2xl font-semibold tabular text-error">{{ formatMoney(card.overdue_amount) }}</p>
            <p class="text-xs text-muted">{{ card.overdue_count }} parcela(s) · {{ card.company_name }}</p>
          </div>
          <div>
            <p class="text-xs text-dimmed">Desde</p>
            <p class="text-highlighted">{{ formatDate(card.overdue_since) }}</p>
            <p v-if="card.oldest_overdue" class="text-xs text-error">{{ daysLate(card.oldest_overdue) }} dia(s) de atraso</p>
          </div>
          <UFormField label="Etapa">
            <USelect :model-value="card.stage_id" :items="stageItems" :disabled="!canChange || !isOpen" class="w-full"
                     @update:model-value="(v: any) => changeStage(v)" />
          </UFormField>
          <UFormField label="Responsável">
            <USelectMenu :model-value="card.assignee_id ?? undefined" :items="assignees" value-key="value"
                         :disabled="!canChange" placeholder="Ninguém" class="w-full"
                         @update:model-value="(v: any) => patchCard({ assignee_id: v ?? null })" />
          </UFormField>
          <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted sm:col-span-4">
            <UButton v-if="card.contact_phone && auth.me.value?.has_phone_line" :label="card.contact_phone" icon="i-lucide-phone"
                     size="xs" color="neutral" variant="link" class="p-0" aria-label="Ligar pela API4COM"
                     :loading="callsList?.calling" @click="callsList?.dial()" />
            <span v-else-if="card.contact_phone"><UIcon name="i-lucide-phone" class="align-middle" /> {{ card.contact_phone }}</span>
            <span v-if="card.contact_email"><UIcon name="i-lucide-mail" class="align-middle" /> {{ card.contact_email }}</span>
            <NuxtLink :to="`/registers/contacts/${card.contact_id}`" class="hover:text-primary">Ficha do cliente</NuxtLink>
            <NuxtLink v-if="card.legal_case_id" to="/legal" class="text-warning hover:text-primary">Ação no jurídico</NuxtLink>
            <div class="ms-auto flex flex-wrap items-center gap-2">
              <UBadge v-if="!isOpen" :label="`${DUNNING_LABELS.outcome[card.outcome]} · ${formatDate(card.closed_at)}`"
                      :color="card.outcome === 'legal' ? 'warning' : card.outcome === 'renegotiated' ? 'info' : 'success'" variant="subtle" />
              <UDropdownMenu v-else-if="canChange" :items="resolveItems" :content="{ align: 'end' }">
                <UButton label="Resolver" icon="i-lucide-circle-check" trailing-icon="i-lucide-chevron-down" size="sm" color="success" variant="soft" />
              </UDropdownMenu>
              <UButton v-if="isOpen && auth.can('dunning', 'delete')" icon="i-lucide-trash-2" size="sm" color="error"
                       variant="ghost" aria-label="Excluir card" @click="dismiss" />
            </div>
          </div>
        </div>

        <div class="grid items-start gap-4 lg:grid-cols-[1fr_22rem]">
          <SPanel title="Atividades">
            <template v-if="canChange && isOpen" #actions>
              <UButton label="Nova" icon="i-lucide-plus" size="sm" color="neutral" variant="outline" @click="form.open = !form.open" />
            </template>
            <div v-if="form.open" class="mb-4 grid gap-3 rounded-lg p-3 ring ring-default sm:grid-cols-3">
              <UFormField label="Tipo">
                <USelect v-model="form.kind" :items="kindItems" class="w-full" />
              </UFormField>
              <UFormField label="Título">
                <UInput v-model="form.title" class="w-full" />
              </UFormField>
              <UFormField label="Data">
                <UInput v-model="form.due_date" type="date" class="w-full" />
              </UFormField>
              <UFormField v-if="form.kind === 'message'" label="Mensagem" class="sm:col-span-3">
                <UTextarea v-model="form.message" :rows="3" autoresize class="w-full" />
              </UFormField>
              <div class="sm:col-span-3">
                <UButton label="Adicionar" size="sm" :disabled="!form.title.trim() || !form.due_date" @click="addActivity" />
              </div>
            </div>

            <ul class="flex flex-col gap-2">
              <li v-for="a in pending" :key="a.id" class="rounded-lg p-3 ring ring-default">
                <div class="flex items-start gap-3">
                  <UIcon :name="DUNNING_LABELS.activityIcon[a.kind]!" class="mt-0.5 size-4 shrink-0 text-muted" />
                  <div class="min-w-0 flex-1">
                    <p class="text-sm text-highlighted">{{ a.title }}</p>
                    <p class="text-xs tabular" :class="a.due_date < today() ? 'text-error' : a.due_date === today() ? 'text-warning' : 'text-dimmed'">
                      {{ formatDate(a.due_date) }}
                    </p>
                  </div>
                  <div v-if="canChange && isOpen" class="flex gap-1">
                    <UButton v-if="auth.me.value?.has_phone_line && card.contact_phone" icon="i-lucide-phone-outgoing" size="xs"
                             color="neutral" variant="ghost" aria-label="Ligar" :loading="calling && callingId === a.id" @click="callFor(a)" />
                    <UButton v-if="a.message && whatsapp(a)" icon="i-lucide-send" size="xs" color="neutral" variant="ghost"
                             :to="whatsapp(a)" target="_blank" aria-label="Abrir no WhatsApp" />
                    <UButton v-if="a.message" icon="i-lucide-copy" size="xs" color="neutral" variant="ghost" aria-label="Copiar mensagem"
                             @click="copy(text(a))" />
                    <UButton label="Concluir" icon="i-lucide-check" size="xs" variant="soft" @click="startDone(a)" />
                    <UButton icon="i-lucide-trash-2" size="xs" color="neutral" variant="ghost" aria-label="Excluir" @click="removeActivity(a)" />
                  </div>
                </div>
                <p v-if="a.message" class="mt-2 whitespace-pre-line rounded-md bg-elevated/60 p-2 text-sm text-toned">{{ text(a) }}</p>
                <div v-if="done.id === a.id" class="mt-3 flex flex-col gap-2">
                  <URadioGroup v-model="done.answered" orientation="horizontal"
                               :items="[{ label: 'Cliente respondeu', value: true }, { label: 'Sem retorno', value: false }]" />
                  <UTextarea v-model="done.notes" :rows="2" autoresize placeholder="Observações" class="w-full" />
                  <div class="flex gap-2">
                    <UButton label="Salvar" size="xs" @click="patchActivity(a, { done: true, answered: done.answered, notes: done.notes })" />
                    <UButton label="Cancelar" size="xs" color="neutral" variant="ghost" @click="done.id = null" />
                  </div>
                </div>
              </li>
              <li v-if="!pending.length" class="text-sm text-dimmed">Nenhuma atividade pendente.</li>
            </ul>

            <template v-if="history.length">
              <p class="mt-5 mb-2 text-xs font-medium uppercase tracking-wide text-dimmed">Histórico</p>
              <ul class="flex flex-col divide-y divide-muted">
                <li v-for="a in history" :key="a.id" class="flex items-start gap-3 py-2 text-sm">
                  <UIcon :name="DUNNING_LABELS.activityIcon[a.kind]!" class="mt-0.5 size-4 shrink-0 text-dimmed" />
                  <div class="min-w-0 flex-1">
                    <p class="text-toned">
                      {{ a.title }}
                      <UBadge v-if="a.answered === false" label="Sem retorno" color="warning" variant="subtle" size="sm" />
                      <UBadge v-else-if="a.answered" label="Respondeu" color="success" variant="subtle" size="sm" />
                    </p>
                    <p class="text-xs text-dimmed">{{ formatDateTime(a.done_at) }} · {{ a.done_by_name ?? '—' }}</p>
                    <p v-if="a.notes" class="mt-1 whitespace-pre-line text-muted">{{ a.notes }}</p>
                  </div>
                  <UButton v-if="canChange && isOpen" icon="i-lucide-undo-2" size="xs" color="neutral" variant="ghost"
                           aria-label="Reabrir" @click="patchActivity(a, { done: false })" />
                </li>
              </ul>
            </template>
          </SPanel>

          <div class="flex flex-col gap-4">
          <SPanel title="Ligações">
            <ContactsCalls ref="callsList" :contact-id="card.contact_id" :phone="card.contact_phone" />
          </SPanel>
          <SPanel title="Observações">
            <form v-if="canChange" class="flex flex-col gap-2" @submit.prevent="addNote">
              <UTextarea v-model="note.text" :rows="2" autoresize class="w-full" />
              <UButton type="submit" label="Adicionar" icon="i-lucide-send" size="sm" :loading="note.sending"
                       :disabled="!note.text.trim()" class="self-end" />
            </form>
            <ul class="mt-3 flex max-h-80 flex-col gap-2 overflow-y-auto">
              <li v-for="n in notes" :key="n.id" class="rounded-lg bg-elevated/50 p-2.5 text-sm ring ring-default">
                <p class="mb-1 text-xs text-dimmed">{{ n.author_name ?? '—' }} · {{ formatDateTime(n.created_at) }}</p>
                <p class="whitespace-pre-line">{{ n.text }}</p>
              </li>
              <li v-if="!notes.length" class="text-sm text-dimmed">Nenhuma.</li>
            </ul>
          </SPanel>

          <SPanel title="Parcelas em atraso">
            <ul class="flex flex-col divide-y divide-muted text-sm tabular">
              <li v-for="i in installments" :key="i.id" class="flex justify-between gap-2 py-1.5">
                <div class="min-w-0">
                  <p class="text-toned">{{ formatDate(i.date) }}</p>
                  <p v-if="i.reference" class="truncate text-xs text-dimmed">{{ i.reference }}</p>
                </div>
                <div class="flex items-center gap-1">
                  <span class="text-error">{{ formatMoney(i.amount) }}</span>
                  <UButton v-if="isOpen && canChange && auth.can('transactions', 'change')" icon="i-lucide-split" size="xs" color="neutral"
                           variant="ghost" aria-label="Pagamento parcial" title="Pagamento parcial" @click="openSplit(i)" />
                </div>
              </li>
              <li v-if="!installments.length" class="py-1.5 text-dimmed">Nenhuma.</li>
            </ul>
          </SPanel>
          </div>
        </div>
      </div>
    </template>
  </UModal>

  <UModal v-model:open="legalOpen" title="Ação de cobrança por inadimplência" :ui="{ content: 'max-w-2xl' }">
    <template #body>
      <LegalForm v-if="card" :contact-id="card.contact_id" :contact-name="card.contact_name" :company-id="card.company_id"
                 :summary="`Encaminhado pelo funil de cobrança (em atraso desde ${formatDate(card.overdue_since)}).`"
                 @saved="toLegal" @cancel="legalOpen = false" />
    </template>
  </UModal>
  <UModal v-model:open="resolving.open" title="Resolvido: dar baixa nas parcelas">
    <template #body>
      <ul class="mb-4 divide-y divide-muted rounded-lg ring ring-default text-sm">
        <li v-for="i in installments" :key="i.id" class="flex justify-between gap-2 px-3 py-1.5">
          <span>{{ formatDate(i.date) }} <span class="text-dimmed">{{ i.reference }}</span></span>
          <SMoney :value="i.amount" />
        </li>
      </ul>
      <UFormField label="Data do pagamento" required>
        <UInput v-model="resolving.date" type="date" class="w-full" />
      </UFormField>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton label="Cancelar" color="neutral" variant="ghost" @click="resolving.open = false" />
        <UButton label="Dar baixa e resolver" color="success" :loading="resolving.saving" :disabled="!resolving.date" @click="confirmResolve" />
      </div>
    </template>
  </UModal>
  <UModal v-model:open="reneg.open" title="Renegociação" :ui="{ content: 'max-w-xl' }">
    <template #body>
      <form id="reneg-form" class="grid gap-4 sm:grid-cols-2" @submit.prevent="renegotiate">
        <UFormField label="Valor total renegociado" required class="sm:col-span-2">
          <UInputNumber v-model="reneg.total" :min="0" :step="0.01" :increment="false" :decrement="false"
                        :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
        </UFormField>
        <UFormField label="Entrada">
          <UInputNumber v-model="reneg.down_payment" :min="0" :step="0.01" :increment="false" :decrement="false"
                        :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
        </UFormField>
        <UFormField label="Data da entrada" :required="!!reneg.down_payment">
          <UInput v-model="reneg.down_payment_date" type="date" class="w-full" />
        </UFormField>
        <UFormField label="Parcelas" required>
          <UInputNumber v-model="reneg.count" :min="1" :max="120" class="w-full" />
        </UFormField>
        <UFormField label="Valor de cada parcela">
          <p class="py-1.5 text-sm text-highlighted tabular">{{ formatMoney(renegInstallment) }}</p>
        </UFormField>
        <UFormField label="Primeiro vencimento" required>
          <UInput v-model="reneg.first_due" type="date" class="w-full" />
        </UFormField>
        <UFormField label="Contrato encerrado">
          <USwitch v-model="reneg.close_contract" class="py-1.5" />
        </UFormField>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton label="Cancelar" color="neutral" variant="ghost" @click="reneg.open = false" />
        <UButton type="submit" form="reneg-form" label="Renegociar" :loading="reneg.saving" :disabled="!renegReady" />
      </div>
    </template>
  </UModal>
  <UModal v-model:open="split.open" title="Pagamento parcial">
    <template #body>
      <form v-if="split.item" id="split-form" class="grid gap-4 sm:grid-cols-2" @submit.prevent="confirmSplit">
        <UFormField label="Parcela" class="sm:col-span-2">
          <p class="text-sm text-highlighted tabular">{{ split.item.reference || formatDate(split.item.date) }} · {{ formatMoney(split.item.amount) }}</p>
        </UFormField>
        <UFormField label="Valor da 1ª parte" required>
          <UInputNumber v-model="split.amount" :min="0" :step="0.01" :increment="false" :decrement="false"
                        :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
        </UFormField>
        <UFormField :label="split.paid ? 'Pago em' : 'Vencimento da 1ª parte'" required>
          <UInput v-model="split.date" type="date" class="w-full" />
        </UFormField>
        <UFormField label="Já foi paga" class="sm:col-span-2">
          <USwitch v-model="split.paid" />
        </UFormField>
        <UFormField label="Restante">
          <p class="py-1.5 text-sm tabular" :class="splitRest > 0 ? 'text-highlighted' : 'text-error'">{{ formatMoney(splitRest) }}</p>
        </UFormField>
        <UFormField label="Vencimento do restante" required>
          <UInput v-model="split.rest_date" type="date" class="w-full" />
        </UFormField>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton label="Cancelar" color="neutral" variant="ghost" @click="split.open = false" />
        <UButton type="submit" form="split-form" label="Dividir" :loading="split.saving" :disabled="!splitReady" />
      </div>
    </template>
  </UModal>
</template>
