<script setup lang="ts">
import type { components } from '~/types/api'

type Transaction = components['schemas']['TransactionOut']
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ transactionId: number | null }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const tx = ref<Transaction | null>(null)
const editing = ref(false)
const tab = ref('details')
const canChange = computed(() => auth.can('transactions', 'change'))

const tabs = [
  { label: 'Detalhes', value: 'details', icon: 'i-lucide-file-text' },
  { label: 'Notas fiscais', value: 'invoices', icon: 'i-lucide-receipt-text' },
  { label: 'Anexos', value: 'attachments', icon: 'i-lucide-paperclip' },
  { label: 'Histórico', value: 'history', icon: 'i-lucide-history' },
]

async function load() {
  if (!props.transactionId) return
  try {
    tx.value = await unwrap(api.GET('/api/transaction/{transaction_id}', { params: { path: { transaction_id: props.transactionId } } }))
  } catch (e) {
    notifyError(e)
    open.value = false
  }
}

watch(() => [props.transactionId, open.value], () => {
  if (open.value) {
    editing.value = false
    tab.value = 'details'
    load()
  }
}, { immediate: true })

async function saved() {
  editing.value = false
  await load()
  emit('changed')
}

async function remove() {
  if (!tx.value || !confirm('Excluir este lançamento?')) return
  try {
    await unwrap(api.DELETE('/api/transaction/{transaction_id}', { params: { path: { transaction_id: tx.value.id! } } }))
    notifySuccess('Lançamento excluído')
    open.value = false
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

async function toggleStatus() {
  if (!tx.value) return
  try {
    await unwrap(api.PATCH('/api/transaction/{transaction_id}', {
      params: { path: { transaction_id: tx.value.id! } },
      body: { status: tx.value.status === 'realized' ? 'planned' : 'realized' },
    }))
    await saved()
  } catch (e) {
    notifyError(e)
  }
}

async function cancelFollowing() {
  if (!tx.value?.series_id || !confirm(`Cancelar as parcelas PREVISTAS a partir da ${tx.value.series_index}ª? As realizadas são mantidas.`)) return
  try {
    const { affected } = await unwrap(api.DELETE('/api/transaction-series/{series_id}', {
      params: { path: { series_id: tx.value.series_id }, query: { from_index: tx.value.series_index ?? 1 } },
    }))
    notifySuccess(`${affected} ocorrência(s) cancelada(s)`)
    open.value = false
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

const fields = computed(() => {
  const t = tx.value
  if (!t) return []
  return [
    ['Empresa', t.company_name],
    ['Data', formatDate(t.date)],
    ['Subgrupo', t.subgroup_name],
    ['Cliente/Fornecedor', t.contact_name ?? '—'],
    ['Conta', t.account_name ?? '—'],
    ['Produto / Nº boleto', t.reference || '—'],
    ['Parcela', t.series_index ? `${t.series_index}ª da série` : '—'],
  ]
})
</script>

<template>
  <USlideover v-model:open="open" :title="tx ? `Lançamento #${tx.id}` : 'Lançamento'" :ui="{ content: 'max-w-xl' }">
    <template #body>
      <div v-if="!tx" class="space-y-3">
        <USkeleton class="h-24 w-full" />
        <USkeleton class="h-40 w-full" />
      </div>

      <div v-else class="space-y-5">
        <div class="s-panel p-4 flex items-center gap-4">
          <div class="flex-1">
            <p class="font-display text-2xl font-semibold tracking-tight"><SMoney :value="tx.amount" :type="tx.type" /></p>
            <div class="mt-1 flex flex-wrap gap-1.5">
              <SStatusBadge kind="type" :value="tx.type" />
              <SStatusBadge kind="status" :value="tx.status" />
              <UBadge v-if="tx.is_reversal" label="Estorno" color="warning" variant="subtle" size="sm" />
            </div>
          </div>
          <UButton v-if="canChange" :label="tx.status === 'realized' ? 'Marcar previsto' : 'Marcar realizado'"
                   :icon="tx.status === 'realized' ? 'i-lucide-rotate-ccw' : 'i-lucide-check'"
                   color="neutral" variant="outline" size="sm" class="rounded-full" @click="toggleStatus" />
        </div>

        <UTabs v-model="tab" :items="tabs" :content="false" size="sm" class="w-full" />

        <template v-if="tab === 'details'">
          <TransactionsForm v-if="editing" :transaction="tx" @saved="saved" @cancel="editing = false" />
          <template v-else>
            <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
              <div v-for="[label, value] in fields" :key="label">
                <dt class="text-xs text-dimmed">{{ label }}</dt>
                <dd class="text-sm text-highlighted">{{ value }}</dd>
              </div>
              <div v-if="tx.notes" class="col-span-2">
                <dt class="text-xs text-dimmed">Observações</dt>
                <dd class="text-sm text-highlighted whitespace-pre-line">{{ tx.notes }}</dd>
              </div>
            </dl>
            <div class="flex flex-wrap gap-2 pt-2">
              <UButton v-if="canChange" label="Editar" icon="i-lucide-pencil" @click="editing = true" />
              <UButton v-if="tx.series_id && auth.can('transactions', 'delete')" label="Cancelar desta em diante"
                       icon="i-lucide-calendar-x" color="warning" variant="soft" @click="cancelFollowing" />
              <UButton v-if="auth.can('transactions', 'delete')" label="Excluir" icon="i-lucide-trash-2" color="error"
                       variant="ghost" class="ms-auto" @click="remove" />
            </div>
          </template>
        </template>
        <TransactionsInvoices v-else-if="tab === 'invoices'" :transaction-id="tx.id!" :editable="canChange" />
        <AppAttachments v-else-if="tab === 'attachments'" target="transaction" :target-id="tx.id!" :editable="canChange" />
        <AppHistory v-else target="transaction" :target-id="tx.id!" />
      </div>
    </template>
  </USlideover>
</template>
