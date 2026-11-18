<script setup lang="ts">
import type { components } from '~/types/api'

type Sale = components['schemas']['SaleOut']
type Transaction = components['schemas']['TransactionOut']
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ saleId: number | null }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const lookups = useLookups()
lookups.ensure('subgroups', 'accounts').catch(notifyError)

const sale = ref<Sale | null>(null)
const receivables = ref<Transaction[]>([])
const tab = ref('summary')
const editing = ref(false)
const canChange = computed(() => auth.can('sales', 'change'))
const tabs = [
  { label: 'Resumo', value: 'summary', icon: 'i-lucide-file-text' },
  { label: 'Parcelas', value: 'receivables', icon: 'i-lucide-calendar-range' },
  { label: 'Comissões', value: 'commissions', icon: 'i-lucide-hand-coins' },
  { label: 'Contrato', value: 'contract', icon: 'i-lucide-file-signature' },
  { label: 'Histórico', value: 'history', icon: 'i-lucide-history' },
]

async function load() {
  if (!props.saleId) return
  try {
    sale.value = await unwrap(api.GET('/api/sale/{sale_id}', { params: { path: { sale_id: props.saleId } } }))
    if (auth.can('transactions')) {
      receivables.value = await unwrap(api.GET('/api/sale/{sale_id}/receivables', { params: { path: { sale_id: props.saleId } } }))
    }
  } catch (e) {
    notifyError(e)
  }
}
watch(() => [props.saleId, open.value], () => {
  if (open.value) { tab.value = 'summary'; editing.value = false; load() }
}, { immediate: true })

const received = computed(() => (sale.value ? Math.min(100, (Number(sale.value.received_amount) / Number(sale.value.amount)) * 100) : 0))
const toSchedule = computed(() => (sale.value ? Number(sale.value.amount) - receivables.value.reduce((s, t) => s + Number(t.amount), 0) : 0))

// Receivables generator
const gen = reactive({ subgroup_id: undefined as number | undefined, first_date: today(), installments: 1, down_payment: 0, account_id: undefined as number | undefined })
const generating = ref(false)
const revenueSubgroups = computed(() => (lookups.cache.value.subgroups ?? [])
  .filter(s => s.group === 'operating_revenue' || s.group === 'non_operating_revenue')
  .map(s => ({ label: s.name, value: s.id! })))
const saleAccounts = computed(() => (lookups.cache.value.accounts ?? []).filter(a => a.company === sale.value?.company_id)
  .map(a => ({ label: a.name, value: a.id! })))
watch(sale, (s) => { if (s?.installments_count) gen.installments = s.installments_count })

async function generate() {
  if (!sale.value || !gen.subgroup_id) {
    notifyError('Escolha o subgrupo de receita.', 'Dados incompletos')
    return
  }
  generating.value = true
  try {
    const created = await unwrap(api.POST('/api/sale/{sale_id}/receivables', {
      params: { path: { sale_id: sale.value.id! } },
      body: { ...gen, subgroup_id: gen.subgroup_id, account_id: gen.account_id ?? null, down_payment: gen.down_payment.toFixed(2) },
    }))
    notifySuccess(`${created.length} parcela(s) a receber criada(s)`)
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  } finally {
    generating.value = false
  }
}

async function saved() {
  editing.value = false
  await load()
  emit('changed')
}
</script>

<template>
  <USlideover v-model:open="open" :title="sale?.contact_name ?? (sale ? `Venda #${sale.id}` : 'Venda')" :ui="{ content: 'max-w-2xl' }">
    <template #body>
      <USkeleton v-if="!sale" class="h-40 w-full" />
      <div v-else class="space-y-5">
        <div class="s-panel p-4 space-y-3">
          <div class="flex items-start justify-between gap-3">
            <div>
              <p class="font-display text-2xl font-semibold tracking-tight">{{ formatMoney(sale.amount) }}</p>
              <p class="text-xs text-muted">{{ formatDate(sale.date) }} · {{ sale.product_name ?? 'Sem produto' }}</p>
            </div>
            <SStatusBadge kind="sale" :value="sale.status" />
          </div>
          <UProgress :model-value="received" color="success" size="sm" />
          <div class="grid grid-cols-3 gap-2 text-xs">
            <div><p class="text-dimmed">Recebido</p><p class="text-success tabular">{{ formatMoney(sale.received_amount) }}</p></div>
            <div><p class="text-dimmed">Programado</p><p class="text-primary tabular">{{ formatMoney(sale.scheduled_amount) }}</p></div>
            <div><p class="text-dimmed">A receber</p><p class="text-highlighted tabular">{{ formatMoney(sale.pending_amount) }}</p></div>
          </div>
        </div>

        <div class="@container">
          <UTabs v-model="tab" :items="tabs" :content="false" size="sm" class="w-full"
                 :ui="{ trigger: 'group min-w-0', label: 'hidden group-data-[state=active]:block @xl:block' }" />
        </div>

        <template v-if="tab === 'summary'">
          <SalesForm v-if="editing" :sale="sale" @saved="saved" @cancel="editing = false" />
          <template v-else>
            <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div v-if="sale.contact_id">
                <dt class="text-xs text-dimmed">Cliente</dt>
                <dd><NuxtLink :to="`/registers/contacts/${sale.contact_id}`" class="text-primary hover:underline">{{ sale.contact_name }}</NuxtLink></dd>
              </div>
              <div><dt class="text-xs text-dimmed">Vendedor</dt><dd>{{ sale.salesperson_name ?? '—' }}</dd></div>
              <div><dt class="text-xs text-dimmed">Forma de pagamento</dt><dd>{{ sale.payment_method || '—' }}</dd></div>
              <div><dt class="text-xs text-dimmed">Condições</dt><dd>{{ sale.payment_terms || '—' }}</dd></div>
              <div><dt class="text-xs text-dimmed">Parcelas</dt><dd>{{ sale.installments_count ?? '—' }}</dd></div>
              <div v-if="sale.notes" class="col-span-2"><dt class="text-xs text-dimmed">Observações</dt><dd class="whitespace-pre-line">{{ sale.notes }}</dd></div>
            </dl>
            <UButton v-if="canChange" label="Editar" icon="i-lucide-pencil" @click="editing = true" />
          </template>
        </template>

        <template v-else-if="tab === 'receivables'">
          <p v-if="!auth.can('transactions')" class="text-sm text-dimmed">Seu perfil não acessa lançamentos.</p>
          <template v-else>
            <ul v-if="receivables.length" class="divide-y divide-muted rounded-xl ring ring-default">
              <li v-for="r in receivables" :key="r.id!" class="flex items-center gap-3 px-3 py-2 text-sm">
                <span class="w-24 text-muted tabular">{{ formatDate(r.date) }}</span>
                <span class="flex-1 truncate">{{ r.reference || (r.series_index ? `Parcela ${r.series_index}` : 'Parcela') }}</span>
                <SStatusBadge kind="status" :value="r.status" />
                <SMoney :value="r.amount" class="w-28 text-right" />
              </li>
            </ul>
            <p v-else class="text-sm text-dimmed">Nenhuma parcela programada ainda.</p>

            <SPanel v-if="canChange && auth.can('transactions', 'create') && toSchedule > 0.005" title="Programar recebimento"
                    :description="`Falta programar ${formatMoney(toSchedule)}`">
              <div class="grid gap-3 sm:grid-cols-2">
                <UFormField label="Subgrupo de receita" required class="sm:col-span-2">
                  <USelect v-model="gen.subgroup_id" :items="revenueSubgroups" placeholder="Ex.: Mentorias e Treinamentos" class="w-full" />
                </UFormField>
                <UFormField label="Entrada">
                  <UInputNumber v-model="gen.down_payment" :min="0" :step="0.01" :increment="false" :decrement="false"
                                :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
                </UFormField>
                <UFormField label="Parcelas (após a entrada)">
                  <UInputNumber v-model="gen.installments" :min="1" :max="120" class="w-full" />
                </UFormField>
                <UFormField label="1º vencimento">
                  <UInput v-model="gen.first_date" type="date" class="w-full" />
                </UFormField>
                <UFormField label="Conta">
                  <USelect v-model="gen.account_id" :items="saleAccounts" placeholder="Opcional" class="w-full" />
                </UFormField>
              </div>
              <UButton label="Gerar parcelas" icon="i-lucide-calendar-plus" class="mt-4" :loading="generating" @click="generate" />
            </SPanel>
          </template>
        </template>

        <SalesCommissions v-else-if="tab === 'commissions'" :sale-id="sale.id!" />
        <AppAttachments v-else-if="tab === 'contract'" target="sale" :target-id="sale.id!" :editable="canChange" />
        <AppHistory v-else target="sale" :target-id="sale.id!" />
      </div>
    </template>
  </USlideover>
</template>
