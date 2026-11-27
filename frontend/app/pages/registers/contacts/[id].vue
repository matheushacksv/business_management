<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { components } from '~/types/api'

type Contact = components['schemas']['ContactOut']
type Summary = components['schemas']['ContactSummaryOut']
type Sale = components['schemas']['SaleOut']
type Transaction = components['schemas']['TransactionOut']
type Pending = components['schemas']['PendingInvoiceOut']
type Card = components['schemas']['CardOut']
type Case = components['schemas']['CaseOut']

// Customer/supplier page: everything about one contact in one place (PDF §9)
definePageMeta({ permission: ['contacts', 'view'] })

const route = useRoute()
const id = computed(() => Number(route.params.id))
const { api, unwrap, notifyError, notifySuccess } = useApi()
const confirm = useConfirm()
const auth = useAuth()
const canSales = computed(() => auth.can('sales', 'view'))
const canMoney = computed(() => auth.can('transactions', 'view'))
const canEdit = computed(() => auth.can('contacts', 'change'))
const canDunning = computed(() => auth.can('dunning', 'view'))
const canLegal = computed(() => auth.can('legal', 'view'))
const collectionOpen = ref(false)

const UProgress = resolveComponent('UProgress')
const SStatusBadge = resolveComponent('SStatusBadge')
const SMoney = resolveComponent('SMoney')

const contact = ref<Contact | null>(null)
const summary = ref<Summary | null>(null)

async function loadContact() {
  try {
    const path = { contact_id: id.value }
    ;[contact.value, summary.value] = await Promise.all([
      unwrap(api.GET('/api/contact/{contact_id}', { params: { path } })),
      unwrap(api.GET('/api/contact/{contact_id}/summary', { params: { path } })),
    ])
    notes.value = contact.value.notes ?? ''
  } catch (e) {
    notifyError(e)
    await navigateTo('/registers/contacts')
  }
}

// Tabs (only what the role may see)
const tabs = computed(() => [
  canSales.value && { label: 'Vendas', value: 'sales', icon: 'i-lucide-handshake' },
  canMoney.value && { label: 'Lançamentos', value: 'transactions', icon: 'i-lucide-arrow-left-right' },
  canMoney.value && { label: 'Notas pendentes', value: 'invoices', icon: 'i-lucide-receipt-text' },
  canDunning.value && { label: 'Cobrança', value: 'dunning', icon: 'i-lucide-phone-call' },
  canLegal.value && { label: 'Jurídico', value: 'legal', icon: 'i-lucide-scale' },
  { label: 'Ligações', value: 'calls', icon: 'i-lucide-phone' },
  { label: 'Anexos', value: 'attachments', icon: 'i-lucide-paperclip' },
  { label: 'Observações', value: 'notes', icon: 'i-lucide-notebook-pen' },
  { label: 'Histórico', value: 'history', icon: 'i-lucide-history' },
].filter(Boolean) as { label: string; value: string; icon: string }[])
const tab = ref('')
// Call anytime, with or without a dunning activity: the "Ligações" tab shows it
const callsList = ref<{ dial: () => void } | null>(null)
async function dial() {
  tab.value = 'calls'
  await nextTick()
  callsList.value?.dial()
}
watch(tabs, t => { if (!t.some(x => x.value === tab.value)) tab.value = t[0]!.value }, { immediate: true })

// Sales (ponytail: first 100 = the API max page size; paginate if a customer ever has more)
const sales = ref<Sale[]>([])
const salesLoading = ref(false)
async function loadSales() {
  salesLoading.value = true
  try {
    sales.value = (await unwrap(api.GET('/api/sale', { params: { query: { contact_id: [id.value], ordering: '-date', page_size: 100 } as any } }))).items
  } catch (e) { notifyError(e) } finally { salesLoading.value = false }
}
const saleColumns: TableColumn<Sale>[] = [
  { accessorKey: 'date', header: 'Data', cell: ({ row }) => formatDate(row.original.date) },
  { accessorKey: 'product_name', header: 'Produto', cell: ({ row }) => h('div', [
    h('p', { class: 'text-highlighted' }, row.original.product_name ?? '—'),
    h('p', { class: 'text-xs text-dimmed' }, row.original.payment_terms || ''),
  ]) },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(SStatusBadge, { kind: 'sale', value: row.original.status }) },
  { accessorKey: 'amount', header: () => h('span', { class: 'block text-right' }, 'Valor / recebido'), cell: ({ row }) => {
    const s = row.original
    const pct = Math.min(100, (Number(s.received_amount) / Number(s.amount)) * 100)
    return h('div', { class: 'w-40 ms-auto text-right space-y-1' }, [
      h('p', { class: 'tabular text-highlighted' }, formatMoney(s.amount)),
      h(UProgress, { modelValue: pct, size: 'xs', color: 'success' }),
      h('p', { class: 'text-xs text-dimmed tabular' }, `${formatMoney(s.received_amount)} recebido`),
    ])
  } },
]
const saleId = ref<number | null>(null)
const saleOpen = ref(false)

// Transactions
const PAGE_SIZE = 50
const txStatus = ref<'all' | 'planned' | 'realized' | 'overdue'>('all')  // overdue: planned, due before today
const txPage = ref(1)
const txs = ref<Transaction[]>([])
const txCount = ref(0)
const txLoading = ref(false)
async function loadTransactions() {
  txLoading.value = true
  try {
    const query = {
      contact_id: [id.value], ordering: '-date', page: txPage.value,
      ...(txStatus.value === 'overdue'
        ? { status: ['planned'], date_to: new Date(Date.now() - 864e5).toLocaleDateString('sv-SE') }
        : txStatus.value !== 'all' ? { status: [txStatus.value] } : {}),
    }
    const data = await unwrap(api.GET('/api/transaction', { params: { query: query as any } }))
    txs.value = data.items
    txCount.value = data.count
  } catch (e) { notifyError(e) } finally { txLoading.value = false }
}
watch(txStatus, () => (txPage.value === 1 ? loadTransactions() : (txPage.value = 1)))
watch(txPage, loadTransactions)
const isOverdue = (t: Transaction) => t.status === 'planned' && t.date < today()
const txColumns: TableColumn<Transaction>[] = [
  { accessorKey: 'date', header: 'Data', cell: ({ row }) => h('span', { class: isOverdue(row.original) ? 'text-error font-medium' : '' },
    formatDate(row.original.date) + (isOverdue(row.original) ? ' · em atraso' : '')) },
  { accessorKey: 'subgroup_name', header: 'Subgrupo', cell: ({ row }) => h('div', [
    h('p', { class: 'text-highlighted' }, row.original.subgroup_name),
    h('p', { class: 'text-xs text-dimmed' }, row.original.reference || ''),
  ]) },
  { accessorKey: 'company_name', header: 'Empresa', meta: { class: { td: 'text-muted' } } },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(SStatusBadge, { kind: 'status', value: row.original.status }) },
  { accessorKey: 'amount', header: () => h('span', { class: 'block text-right' }, 'Valor'),
    cell: ({ row }) => h('div', { class: 'text-right' }, h(SMoney, { value: row.original.amount, type: row.original.type })) },
]
const txId = ref<number | null>(null)
const txOpen = ref(false)

// Pending invoices
const invoices = ref<Pending[]>([])
const invoicesLoading = ref(false)
async function loadInvoices() {
  invoicesLoading.value = true
  try {
    invoices.value = (await unwrap(api.GET('/api/invoice/pending', { params: { query: { contact_id: id.value, page_size: 100 } as any } }))).items
  } catch (e) { notifyError(e) } finally { invoicesLoading.value = false }
}
const invoiceColumns: TableColumn<Pending>[] = [
  { accessorKey: 'transaction_date', header: 'Data', cell: ({ row }) => formatDate(row.original.transaction_date) },
  { accessorKey: 'kind', header: 'Nota', cell: ({ row }) => h('div', [
    h('p', LABELS.invoiceKind[row.original.kind]),
    h('p', { class: 'text-xs text-dimmed' }, row.original.direction === 'receive' ? 'Receber do fornecedor' : 'Emitir ao cliente'),
  ]) },
  { accessorKey: 'company_name', header: 'Empresa', meta: { class: { td: 'text-muted' } } },
  { accessorKey: 'pending_reason', header: 'Pendência', cell: ({ row }) => h(SStatusBadge, { kind: 'invoice', value: row.original.pending_reason }) },
  { accessorKey: 'transaction_amount', header: () => h('span', { class: 'block text-right' }, 'Valor'),
    cell: ({ row }) => h('div', { class: 'text-right' }, h(SMoney, { value: row.original.transaction_amount })) },
]

// Dunning cards (open first, then the closed ones: history) and legal cases of this contact; a click opens them on their screen
const cards = ref<Card[]>([])
const stageNames = ref<Record<number, string>>({})
const cases = ref<Case[]>([])
const followLoading = ref(false)
async function loadFollowUp() {
  followLoading.value = true
  try {
    await Promise.all([
      canDunning.value && Promise.all([
        unwrap(api.GET('/api/dunning/card', { params: { query: { contact_id: id.value, outcome: 'all' } } })),
        unwrap(api.GET('/api/dunning/stage')),
      ]).then(([c, s]) => {
        cards.value = c
        stageNames.value = Object.fromEntries(s.map(x => [x.id, x.name]))
      }),
      canLegal.value && unwrap(api.GET('/api/collection-case', { params: { query: { contact_id: id.value } } })).then(c => (cases.value = c)),
    ])
  } catch (e) { notifyError(e) } finally { followLoading.value = false }
}
const cardColumns: TableColumn<Card>[] = [
  { accessorKey: 'company_name', header: 'Empresa', meta: { class: { td: 'text-muted' } } },
  { accessorKey: 'stage_id', header: 'Etapa', cell: ({ row }) => row.original.closed_at
    ? h('div', [h('p', DUNNING_LABELS.outcome[row.original.outcome] ?? row.original.outcome), h('p', { class: 'text-xs text-dimmed' }, formatDate(row.original.closed_at))])
    : h('span', { class: row.original.critical ? 'text-error font-medium' : '' }, stageNames.value[row.original.stage_id] ?? '—') },
  { accessorKey: 'oldest_overdue', header: 'Atraso desde', cell: ({ row }) => formatDate(row.original.oldest_overdue) },
  { accessorKey: 'next_activity', header: 'Próxima atividade', cell: ({ row }) => h('span', { class: row.original.late_activities ? 'text-error' : '' },
    formatDate(row.original.next_activity) || '—') },
  { accessorKey: 'assignee_name', header: 'Responsável', cell: ({ row }) => row.original.assignee_name ?? '—' },
  { accessorKey: 'overdue_amount', header: () => h('span', { class: 'block text-right' }, 'Em atraso'), cell: ({ row }) => h('div', { class: 'text-right' }, [
    h('p', { class: 'tabular text-highlighted' }, formatMoney(row.original.overdue_amount)),
    h('p', { class: 'text-xs text-dimmed' }, plural(row.original.overdue_count, 'parcela', 'parcelas')),
  ]) },
]
const caseColumns: TableColumn<Case>[] = [
  { accessorKey: 'created_at', header: 'Aberto em', cell: ({ row }) => formatDate(row.original.created_at) },
  { accessorKey: 'company_name', header: 'Empresa', meta: { class: { td: 'text-muted' } } },
  { accessorKey: 'stage_name', header: 'Etapa', cell: ({ row }) => h('div', [
    h('p', row.original.closed_at ? 'Concluída' : row.original.stage_name),
    row.original.unrecoverable_at ? h('p', { class: 'text-xs text-error' }, 'Irrecuperável') : null,
  ]) },
  { accessorKey: 'responsible_name', header: 'Responsável', cell: ({ row }) => row.original.responsible_name ?? '—' },
  { accessorKey: 'open_amount', header: () => h('span', { class: 'block text-right' }, 'Em aberto / recebido'), cell: ({ row }) => h('div', { class: 'text-right' }, [
    h('p', { class: 'tabular text-highlighted' }, formatMoney(row.original.open_amount)),
    h('p', { class: 'text-xs text-dimmed tabular' }, `${formatMoney(row.original.received_amount)} recebido`),
  ]) },
]

// Notes
const notes = ref('')
const savingNotes = ref(false)
async function saveNotes() {
  savingNotes.value = true
  try {
    contact.value = await unwrap(api.PATCH('/api/contact/{contact_id}', { params: { path: { contact_id: id.value } }, body: { notes: notes.value } }))
    notes.value = contact.value.notes ?? ''
    notifySuccess('Observações salvas')
  } catch (e) { notifyError(e) } finally { savingNotes.value = false }
}

// Edit / delete
const editOpen = ref(false)
async function remove() {
  if (!await confirm({ title: `Excluir ${contact.value?.name}?`, description: 'Só é possível se não houver lançamentos ou vendas ligados.' })) return
  try {
    await unwrap(api.DELETE('/api/contact/{contact_id}', { params: { path: { contact_id: id.value } } }))
    notifySuccess('Contato excluído')
    await navigateTo('/registers/contacts')
  } catch (e) { notifyError(e) }
}

// Anything changed in a drawer can move the totals
async function refreshAll() {
  await Promise.all([loadContact(), canSales.value && loadSales(), canMoney.value && loadTransactions(), canMoney.value && loadInvoices(), loadFollowUp()])
}
watch(id, refreshAll, { immediate: true })

// Merge a duplicate into this contact (its transactions, sales, cases and files move here)
const canMerge = computed(() => auth.can('contacts', 'change') && auth.can('contacts', 'delete'))
const mergeOpen = ref(false)
const mergeSource = ref<number | null>(null)
const merging = ref(false)
async function merge() {
  if (!mergeSource.value || !contact.value) return
  const ok = await confirm({
    title: 'Mesclar contatos?',
    description: `Lançamentos, vendas, cobranças e anexos do duplicado passam para "${contact.value.name}" e o duplicado é excluído. Não dá para desfazer.`,
    confirmLabel: 'Mesclar', color: 'warning', icon: 'i-lucide-merge',
  })
  if (!ok) return
  merging.value = true
  try {
    await unwrap(api.POST('/api/contact/{contact_id}/merge', {
      params: { path: { contact_id: id.value } }, body: { source_ids: [mergeSource.value] },
    }))
    notifySuccess('Contatos mesclados')
    mergeOpen.value = false
    mergeSource.value = null
    await refreshAll()
  } catch (e) {
    notifyError(e)
  } finally {
    merging.value = false
  }
}

const m = computed(() => summary.value?.money)
const isSupplier = computed(() => !!m.value && [m.value.paid, m.value.to_pay, m.value.overdue_payable].some(v => Number(v) > 0))
// Funnel of the finance team: opens (or finds) the card and goes there
const sending = ref(false)
async function sendToDunning() {
  sending.value = true
  try {
    const cards = await unwrap(api.POST('/api/dunning/send/{contact_id}', { params: { path: { contact_id: id.value } } }))
    await navigateTo({ path: '/dunning', query: { card: cards[0]!.id } })
  } catch (e) {
    notifyError(e)
  } finally {
    sending.value = false
  }
}
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
</script>

<template>
  <AppPage :title="contact?.name ?? 'Cliente/fornecedor'">
    <template #actions>
      <UButton v-if="auth.me.value?.has_phone_line && contact?.phone" label="Ligar" icon="i-lucide-phone-outgoing"
               variant="soft" @click="dial" />
      <SStatusBadge v-if="summary?.situation" kind="situation" :value="summary.situation" class="self-center" />
      <UButton v-if="auth.can('dunning', 'change')" label="Enviar para cobrança" icon="i-lucide-phone-call" color="neutral" variant="outline"
               :disabled="!contact" :loading="sending" @click="sendToDunning" />
      <UButton v-if="auth.can('legal', 'create')" label="Enviar ao jurídico" icon="i-lucide-scale" color="neutral" variant="outline"
               :disabled="!contact" @click="collectionOpen = true" />
      <UButton v-if="canMerge" label="Mesclar duplicado" icon="i-lucide-merge" color="neutral" variant="outline"
               :disabled="!contact" @click="mergeOpen = true" />
      <UButton v-if="canEdit" label="Editar" icon="i-lucide-pencil" color="neutral" variant="outline" :disabled="!contact" @click="editOpen = true" />
      <UButton v-if="auth.can('contacts', 'delete')" icon="i-lucide-trash-2" color="error" variant="ghost" aria-label="Excluir contato" @click="remove" />
    </template>

    <NuxtLink to="/registers/contacts" class="inline-flex items-center gap-1 text-sm text-muted hover:text-highlighted w-fit">
      <UIcon name="i-lucide-arrow-left" class="size-4" /> Clientes e fornecedores
    </NuxtLink>

    <USkeleton v-if="!contact" class="h-28 w-full" />
    <SPanel v-else>
      <div class="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
        <div class="min-w-0">
          <p class="font-display text-xl font-semibold tracking-tight text-highlighted">{{ contact.name }}</p>
          <p v-if="contact.company_name" class="text-muted">{{ contact.company_name }}</p>
        </div>
        <span v-if="contact.document" class="inline-flex items-center gap-1.5 text-toned tabular">
          <UIcon name="i-lucide-id-card" class="size-4 text-dimmed" />{{ formatDocument(contact.document) }}
        </span>
        <a v-if="contact.email" :href="`mailto:${contact.email}`" class="inline-flex items-center gap-1.5 text-toned hover:text-primary">
          <UIcon name="i-lucide-mail" class="size-4 text-dimmed" />{{ contact.email }}
        </a>
        <a v-if="contact.phone" :href="`tel:${contact.phone}`" class="inline-flex items-center gap-1.5 text-toned hover:text-primary">
          <UIcon name="i-lucide-phone" class="size-4 text-dimmed" />{{ contact.phone }}
        </a>
      </div>
    </SPanel>

    <template v-if="summary && (summary.sales || m)">
      <section class="space-y-2">
        <h2 class="text-xs font-medium uppercase tracking-wide text-muted">Como cliente</h2>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SStat v-if="summary.sales" label="Vendido" :value="formatMoney(summary.sales.sold)" icon="i-lucide-handshake"
                 :hint="plural(summary.sales.sales_count, 'venda', 'vendas')" />
          <template v-if="m">
            <SStat label="Recebido" :value="formatMoney(m.received)" icon="i-lucide-circle-check" tone="success" />
            <SStat label="A receber" :value="formatMoney(m.to_receive)" icon="i-lucide-calendar-clock" tone="primary" />
            <SStat label="Em atraso" :value="formatMoney(m.overdue_receivable)" icon="i-lucide-alarm-clock"
                   :tone="Number(m.overdue_receivable) > 0 ? 'error' : 'default'"
                   :hint="plural(m.overdue_receivable_count, 'parcela', 'parcelas')" />
          </template>
        </div>
      </section>
      <section v-if="isSupplier && m" class="space-y-2">
        <h2 class="text-xs font-medium uppercase tracking-wide text-muted">Como fornecedor</h2>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SStat label="Pago" :value="formatMoney(m.paid)" icon="i-lucide-circle-check" />
          <SStat label="A pagar" :value="formatMoney(m.to_pay)" icon="i-lucide-calendar-clock" tone="primary" />
          <SStat label="Em atraso" :value="formatMoney(m.overdue_payable)" icon="i-lucide-alarm-clock"
                 :tone="Number(m.overdue_payable) > 0 ? 'error' : 'default'"
                 :hint="plural(m.overdue_payable_count, 'conta', 'contas')" />
        </div>
      </section>
    </template>

    <UTabs v-model="tab" :items="tabs" :content="false" size="sm" class="w-full" />

    <div v-if="tab === 'sales'" class="s-panel overflow-hidden">
      <UTable :data="sales" :columns="saleColumns" :loading="salesLoading" empty="Nenhuma venda para este cliente"
              @select="(_: Event, row: any) => { saleId = row.original.id; saleOpen = true }" />
    </div>

    <template v-else-if="tab === 'transactions'">
      <UTabs v-model="txStatus" :items="[{ label: 'Todos', value: 'all' }, ...STATUS_OPTIONS, { label: 'Vencidas', value: 'overdue' }]" :content="false" size="xs" class="w-fit" />
      <div class="s-panel overflow-hidden">
        <UTable :data="txs" :columns="txColumns" :loading="txLoading" empty="Nenhum lançamento"
                @select="(_: Event, row: any) => { txId = row.original.id; txOpen = true }" />
      </div>
      <div class="flex items-center justify-between text-sm text-muted">
        <span>{{ txCount.toLocaleString('pt-BR') }} lançamento(s)</span>
        <UPagination v-if="txCount > PAGE_SIZE" v-model:page="txPage" :total="txCount" :items-per-page="PAGE_SIZE" />
      </div>
    </template>

    <div v-else-if="tab === 'invoices'" class="s-panel overflow-hidden">
      <UTable :data="invoices" :columns="invoiceColumns" :loading="invoicesLoading" empty="Nenhuma nota pendente 🎉"
              @select="(_: Event, row: any) => { txId = row.original.transaction_id; txOpen = true }" />
    </div>

    <div v-else-if="tab === 'dunning'" class="s-panel overflow-hidden">
      <UTable :data="cards" :columns="cardColumns" :loading="followLoading" empty="Nenhuma cobrança"
              @select="(_: Event, row: any) => navigateTo({ path: '/dunning', query: { card: row.original.id } })" />
    </div>

    <div v-else-if="tab === 'legal'" class="s-panel overflow-hidden">
      <UTable :data="cases" :columns="caseColumns" :loading="followLoading" empty="Nenhuma ação no jurídico"
              @select="(_: Event, row: any) => navigateTo({ path: '/legal', query: { case: row.original.id } })" />
    </div>

    <SPanel v-else-if="tab === 'calls'">
      <ContactsCalls ref="callsList" :contact-id="id" :button="false" />
    </SPanel>

    <SPanel v-else-if="tab === 'attachments'">
      <AppAttachments target="contact" :target-id="id" :editable="canEdit" />
    </SPanel>

    <SPanel v-else-if="tab === 'notes'">
      <UTextarea v-model="notes" :rows="8" autoresize :disabled="!canEdit" class="w-full"
                 placeholder="Combinados, preferências de cobrança, responsáveis, contatos adicionais…" />
      <div v-if="canEdit" class="mt-3 flex justify-end">
        <UButton label="Salvar observações" :loading="savingNotes" :disabled="notes === contact?.notes" @click="saveNotes" />
      </div>
    </SPanel>

    <SPanel v-else-if="tab === 'history'">
      <AppHistory target="contact" :target-id="id" />
    </SPanel>

    <SalesDrawer v-model:open="saleOpen" :sale-id="saleId" @changed="refreshAll" />
    <TransactionsDrawer v-model:open="txOpen" :transaction-id="txId" @changed="refreshAll" />
    <AppContactFormModal v-model:open="editOpen" :contact="contact" @saved="(c) => (contact = c)" />
    <UModal v-model:open="mergeOpen" title="Mesclar duplicado">
      <template #body>
        <AppContactSelect v-model="mergeSource" placeholder="Buscar o contato duplicado" />
        <p v-if="mergeSource === id" class="mt-2 text-xs text-error">Escolha outro contato.</p>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="mergeOpen = false" />
          <UButton label="Mesclar" icon="i-lucide-merge" :loading="merging" :disabled="!mergeSource || mergeSource === id" @click="merge" />
        </div>
      </template>
    </UModal>
    <UModal v-model:open="collectionOpen" title="Ação de cobrança por inadimplência" :ui="{ content: 'max-w-2xl' }">
      <template #body>
        <LegalForm :contact-id="id" :contact-name="contact?.name" @saved="navigateTo('/legal')" @cancel="collectionOpen = false" />
      </template>
    </UModal>
  </AppPage>
</template>
