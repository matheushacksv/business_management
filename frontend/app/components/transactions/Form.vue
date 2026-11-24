<script setup lang="ts">
import type { components } from '~/types/api'

type Transaction = components['schemas']['TransactionOut']
// `copy`: new transaction prefilled from another one (duplicate), dated the next month
const props = defineProps<{ transaction?: Transaction | null, copy?: Transaction | null }>()
const emit = defineEmits<{ saved: [id: number | null, again?: boolean]; cancel: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('companies', 'subgroups', 'groups', 'accounts').catch(notifyError)

const isEdit = computed(() => !!props.transaction)
const mode = ref<'single' | 'installment' | 'recurring'>('single')
const saving = ref(false)

const t = props.transaction ?? props.copy
const state = reactive({
  company_id: t?.company ?? (lookups.options.companies.value[0]?.value as number | undefined),
  date: props.copy ? nextMonth(props.copy.date) : t?.date ?? today(),
  type: t?.type ?? 'outflow',
  subgroup_id: t?.subgroup as number | undefined,
  amount: t ? Number(t.amount) : (undefined as number | undefined),
  status: props.transaction?.status ?? 'planned',
  account_id: (t?.account ?? undefined) as number | undefined,
  contact_id: (t?.contact ?? null) as number | null,
  reference: t?.reference ?? '',
  notes: t?.notes ?? '',
  count: 2,
})

const accounts = computed(() =>
  (lookups.cache.value.accounts ?? []).filter(a => a.company === state.company_id).map(a => ({ label: a.name, value: a.id! })),
)
// Default company once the list arrives (new transactions only)
watch(lookups.options.companies, (companies) => {
  if (!state.company_id && companies.length) state.company_id = companies[0]!.value as number
}, { immediate: true })

// Picking a subgroup sets its natural type (revenue -> inflow, cost -> outflow).
// Not immediate: opening an existing transaction keeps its type. The user may still flip it (reversal).
// Transfers between companies have their own form: their system subgroup isn't offered here
const subgroupItems = computed(() => lookups.options.subgroups.value.filter(o => o.group !== 'transfer'))
const subgroupGroup = computed(() => lookups.cache.value.subgroups?.find(s => s.id === state.subgroup_id)?.group)
watch(() => state.subgroup_id, () => {
  const natural = naturalType(subgroupGroup.value)
  if (natural) state.type = natural
})
const isReversal = computed(() => {
  const natural = naturalType(subgroupGroup.value)
  return !!natural && natural !== state.type
})

watch(() => state.company_id, () => {
  if (state.account_id && !accounts.value.some(a => a.value === state.account_id)) state.account_id = undefined
})

const modes = [
  { label: 'Único', value: 'single' },
  { label: 'Parcelado', value: 'installment' },
  { label: 'Recorrente', value: 'recurring' },
]
const amountLabel = computed(() => (mode.value === 'installment' ? 'Valor total' : mode.value === 'recurring' ? 'Valor de cada mês' : 'Valor'))
const preview = computed(() => {
  if (mode.value === 'single' || !state.amount || !state.count) return ''
  return mode.value === 'installment'
    ? `${state.count}× de ${formatMoney(state.amount / state.count)} (centavos ajustados na 1ª)`
    : `${state.count} meses · total ${formatMoney(state.amount * state.count)}`
})

// "Criar e novo": keeps company, date, type, status, subgroup and account for the next one
const again = ref(false)
function resetForNext() {
  Object.assign(state, { amount: undefined, contact_id: null, reference: '', notes: '' })
}

async function submit(event?: Event) {
  if (event) again.value = false  // form submit (Enter / "Criar")
  if (!state.company_id || !state.subgroup_id || !state.amount || state.amount <= 0) {
    notifyError('Preencha empresa, subgrupo e um valor maior que zero.', 'Dados incompletos')
    return
  }
  saving.value = true
  const common = {
    subgroup_id: state.subgroup_id, type: state.type as any, status: state.status as any,
    account_id: state.account_id ?? null, contact_id: state.contact_id, reference: state.reference, notes: state.notes,
  }
  const amount = state.amount.toFixed(2)
  try {
    if (isEdit.value) {
      await unwrap(api.PATCH('/api/transaction/{transaction_id}', {
        params: { path: { transaction_id: t!.id! } },
        body: { ...common, date: state.date, amount },
      }))
      notifySuccess('Lançamento atualizado')
      emit('saved', t!.id!)
    } else if (mode.value === 'single') {
      const created = await unwrap(api.POST('/api/transaction', {
        body: { ...common, company_id: state.company_id, date: state.date, amount },
      }))
      notifySuccess('Lançamento criado')
      if (again.value) resetForNext()
      emit('saved', created.id!, again.value)
    } else {
      await unwrap(api.POST('/api/transaction-series', {
        body: {
          ...common, kind: mode.value as any, count: state.count, first_date: state.date, company_id: state.company_id,
          amount: mode.value === 'recurring' ? amount : null,
          total_amount: mode.value === 'installment' ? amount : null,
        },
      }))
      notifySuccess(`${state.count} lançamentos criados`)
      if (again.value) resetForNext()
      emit('saved', null, again.value)
    }
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="submit($event)">
    <UFormField v-if="!isEdit" label="Tipo de lançamento" class="sm:col-span-2">
      <UTabs v-model="mode" :items="modes" :content="false" size="sm" />
    </UFormField>

    <UFormField label="Empresa" required>
      <USelect v-model="state.company_id" :items="lookups.options.companies.value" :disabled="isEdit" class="w-full" />
    </UFormField>
    <UFormField :label="mode === 'single' ? 'Data' : 'Data da 1ª ocorrência'" required>
      <UInput v-model="state.date" type="date" class="w-full" />
    </UFormField>

    <UFormField label="Tipo" required
                :help="isReversal ? `Estorno: ${state.type === 'inflow' ? 'entrada' : 'saída'} em ${lookups.groupLabel(subgroupGroup)} reduz esse grupo no DRE` : undefined"
                :ui="{ help: 'text-warning' }">
      <UTabs v-model="state.type" :items="TYPE_OPTIONS" :content="false" size="sm" />
    </UFormField>
    <UFormField label="Status" required>
      <UTabs v-model="state.status" :items="STATUS_OPTIONS" :content="false" size="sm" />
    </UFormField>

    <UFormField label="Subgrupo" required class="sm:col-span-2">
      <USelectMenu v-model="state.subgroup_id" :items="subgroupItems" value-key="value"
                   placeholder="Escolha a categoria" class="w-full" />
    </UFormField>

    <UFormField :label="amountLabel" required>
      <UInputNumber v-model="state.amount" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField v-if="mode !== 'single'" :label="mode === 'installment' ? 'Parcelas' : 'Meses'" required :hint="preview">
      <UInputNumber v-model="state.count" :min="mode === 'installment' ? 2 : 1" :max="120" class="w-full" />
    </UFormField>
    <UFormField v-else label="Conta">
      <USelect v-model="state.account_id" :items="accounts" placeholder="Opcional" class="w-full" />
    </UFormField>

    <UFormField v-if="mode !== 'single'" label="Conta">
      <USelect v-model="state.account_id" :items="accounts" placeholder="Opcional" class="w-full" />
    </UFormField>
    <UFormField label="Cliente/Fornecedor" :class="mode === 'single' ? 'sm:col-span-2' : ''">
      <AppContactSelect v-model="state.contact_id" :initial-label="t?.contact_name" />
    </UFormField>

    <UFormField label="Produto / Nº boleto" class="sm:col-span-2">
      <UInput v-model="state.reference" class="w-full" />
    </UFormField>
    <UFormField label="Observações" class="sm:col-span-2">
      <UTextarea v-model="state.notes" :rows="2" class="w-full" />
    </UFormField>

    <div class="flex justify-end gap-2 sm:col-span-2">
      <UButton label="Cancelar" color="neutral" variant="ghost" @click="emit('cancel')" />
      <!-- type=button: Enter in a field submits with the default "Criar" -->
      <UButton v-if="!isEdit" label="Criar e novo" color="neutral" variant="outline" :loading="saving && again"
               @click="again = true; submit()" />
      <UButton type="submit" :label="isEdit ? 'Salvar' : 'Criar'" :loading="saving && !again" />
    </div>
  </form>
</template>
