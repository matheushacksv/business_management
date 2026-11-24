<script setup lang="ts">
import type { components } from '~/types/api'

type Transaction = components['schemas']['TransactionOut']
type Transfer = components['schemas']['TransferOut']
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ transactionId: number | null }>()
const emit = defineEmits<{ changed: [], duplicate: [tx: Transaction] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const confirm = useConfirm()
const auth = useAuth()
const tx = ref<Transaction | null>(null)
// Leg of a transfer between companies: changes go through the transfer (both legs together).
// null when the user can't see the other company: the leg is then read-only.
const transfer = ref<Transfer | null>(null)
const editing = ref(false)
const tab = ref('details')
const isLeg = computed(() => !!tx.value?.transfer_id)
// A leg the user can't manage as a transfer (other company not visible) stays read-only
const canChange = computed(() => auth.can('transactions', 'change') && (!isLeg.value || !!transfer.value))
// Transfer and investment legs are created through their own screens
const lookups = useLookups()
const canDuplicate = computed(() => auth.can('transactions', 'create') && !isLeg.value
  && lookups.cache.value.subgroups?.find(s => s.id === tx.value?.subgroup)?.group !== 'transfer')
const canDelete = computed(() => auth.can('transactions', 'delete') && (!isLeg.value || !!transfer.value))

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
    transfer.value = null
    if (tx.value.transfer_id) {
      transfer.value = await unwrap(api.GET('/api/transfer/{transfer_id}', { params: { path: { transfer_id: tx.value.transfer_id } } }))
        .catch(() => null)
    }
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
  if (!tx.value) return
  if (transfer.value) {
    if (!await confirm({ title: 'Excluir transferência?', description: 'A saída e a entrada das duas empresas serão excluídas.' })) return
  } else if (!await confirm({ title: 'Excluir lançamento?', description: 'Notas fiscais e anexos ligados a ele também são excluídos.' })) return
  try {
    if (transfer.value) {
      await unwrap(api.DELETE('/api/transfer/{transfer_id}', { params: { path: { transfer_id: transfer.value.id } } }))
    } else {
      await unwrap(api.DELETE('/api/transaction/{transaction_id}', { params: { path: { transaction_id: tx.value.id! } } }))
    }
    notifySuccess(transfer.value ? 'Transferência excluída' : 'Lançamento excluído')
    open.value = false
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

async function toggleStatus() {
  if (!tx.value) return
  const status = tx.value.status === 'realized' ? 'planned' : 'realized'
  try {
    if (transfer.value) {
      await unwrap(api.PATCH('/api/transfer/{transfer_id}', { params: { path: { transfer_id: transfer.value.id } }, body: { status } }))
    } else {
      await unwrap(api.PATCH('/api/transaction/{transaction_id}', { params: { path: { transaction_id: tx.value.id! } }, body: { status } }))
    }
    await saved()
  } catch (e) {
    notifyError(e)
  }
}

async function cancelFollowing() {
  if (!tx.value?.series_id) return
  if (!await confirm({
    title: 'Cancelar desta em diante?', confirmLabel: 'Cancelar parcelas', color: 'warning', icon: 'i-lucide-calendar-x',
    description: `As parcelas PREVISTAS a partir da ${tx.value.series_index}ª serão excluídas. As realizadas são mantidas.`,
  })) return
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
  return <[string, string][]>[
    ['Empresa', t.company_name],
    ['Data', formatDate(t.date)],
    ['Subgrupo', t.subgroup_name],
    ['Cliente/Fornecedor', t.contact_name ?? '—'],
    ['Conta', t.account_name ?? '—'],
    [t.transfer_id ? 'Transferência' : 'Produto / Nº boleto', t.reference || '—'],
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
              <UBadge v-if="isLeg" label="Transferência" icon="i-lucide-repeat" color="primary" variant="subtle" size="sm" />
              <UBadge v-if="tx.collection_case_id" label="Em cobrança" icon="i-lucide-scale" color="warning" variant="subtle" size="sm" />
            </div>
          </div>
          <UButton v-if="canChange" :label="tx.status === 'realized' ? 'Marcar previsto' : 'Marcar realizado'"
                   :icon="tx.status === 'realized' ? 'i-lucide-rotate-ccw' : 'i-lucide-check'"
                   color="neutral" variant="outline" size="sm" class="rounded-full" @click="toggleStatus" />
        </div>

        <UTabs v-model="tab" :items="tabs" :content="false" size="sm" class="w-full" />

        <template v-if="tab === 'details'">
          <TransactionsTransferForm v-if="editing && transfer" :transfer="transfer" @saved="saved" @cancel="editing = false" />
          <TransactionsForm v-else-if="editing" :transaction="tx" @saved="saved" @cancel="editing = false" />
          <template v-else>
            <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
              <div v-for="[label, value] in fields" :key="label">
                <dt class="text-xs text-dimmed">{{ label }}</dt>
                <dd class="text-sm text-highlighted">
                  <NuxtLink v-if="label === 'Cliente/Fornecedor' && tx.contact" :to="`/registers/contacts/${tx.contact}`"
                            class="text-primary hover:underline">{{ value }}</NuxtLink>
                  <template v-else>{{ value }}</template>
                </dd>
              </div>
              <div v-if="tx.notes" class="col-span-2">
                <dt class="text-xs text-dimmed">Observações</dt>
                <dd class="text-sm text-highlighted whitespace-pre-line">{{ tx.notes }}</dd>
              </div>
            </dl>
            <UAlert v-if="isLeg && !transfer" color="neutral" variant="subtle" icon="i-lucide-lock"
                    title="Parte de uma transferência entre empresas"
                    description="Só quem tem acesso às duas empresas pode alterar ou excluir." />
            <div class="flex flex-wrap gap-2 pt-2">
              <UButton v-if="canChange" :label="transfer ? 'Editar transferência' : 'Editar'" icon="i-lucide-pencil" @click="editing = true" />
              <UButton v-if="canDuplicate" label="Duplicar" icon="i-lucide-copy" color="neutral" variant="outline"
                       @click="emit('duplicate', tx); open = false" />
              <UButton v-if="tx.series_id && auth.can('transactions', 'delete')" label="Cancelar desta em diante"
                       icon="i-lucide-calendar-x" color="warning" variant="soft" @click="cancelFollowing" />
              <UButton v-if="canDelete" :label="transfer ? 'Excluir transferência' : 'Excluir'" icon="i-lucide-trash-2" color="error"
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
