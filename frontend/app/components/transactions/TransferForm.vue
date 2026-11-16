<script setup lang="ts">
import type { components } from '~/types/api'

type Transfer = components['schemas']['TransferOut']

// Transfer between companies of the group: creates/edits both legs at once (never in the DRE)
const props = defineProps<{ transfer?: Transfer | null }>()
const emit = defineEmits<{ saved: [transfer: Transfer]; cancel: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('companies', 'accounts').catch(notifyError)

const t = props.transfer
const isEdit = !!t
const saving = ref(false)
const state = reactive({
  from_company_id: t?.from_company_id as number | undefined,
  to_company_id: t?.to_company_id as number | undefined,
  date: t?.date ?? today(),
  amount: t ? Number(t.amount) : (undefined as number | undefined),
  status: t?.status ?? 'realized',
  from_account_id: (t?.from_account_id ?? undefined) as number | undefined,
  to_account_id: (t?.to_account_id ?? undefined) as number | undefined,
  notes: t?.notes ?? '',
})

const accountsOf = (companyId?: number) => (lookups.cache.value.accounts ?? [])
  .filter(a => a.company === companyId).map(a => ({ label: a.name, value: a.id! }))
const fromAccounts = computed(() => accountsOf(state.from_company_id))
const toAccounts = computed(() => accountsOf(state.to_company_id))
const toCompanies = computed(() => lookups.options.companies.value.filter(c => c.value !== state.from_company_id))

// Changing a company drops the account of the old one
watch(() => state.from_company_id, () => { if (!isEdit) state.from_account_id = undefined })
watch(() => state.to_company_id, () => { if (!isEdit) state.to_account_id = undefined })
watch(() => state.from_company_id, (id) => { if (id && id === state.to_company_id) state.to_company_id = undefined })

async function submit() {
  if (!state.from_company_id || !state.to_company_id || !state.amount || state.amount <= 0) {
    notifyError('Informe as duas empresas e um valor maior que zero.', 'Campos obrigatórios')
    return
  }
  saving.value = true
  const common = {
    date: state.date, amount: state.amount.toFixed(2), status: state.status as any, notes: state.notes,
    from_account_id: state.from_account_id ?? null, to_account_id: state.to_account_id ?? null,
  }
  try {
    const saved = t
      ? await unwrap(api.PATCH('/api/transfer/{transfer_id}', { params: { path: { transfer_id: t.id } }, body: common }))
      : await unwrap(api.POST('/api/transfer', {
          body: { ...common, from_company_id: state.from_company_id, to_company_id: state.to_company_id },
        }))
    notifySuccess(t ? 'Transferência atualizada' : 'Transferência registrada')
    emit('saved', saved)
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="submit">
    <p class="sm:col-span-2 text-xs text-muted">
      Gera uma saída na empresa de origem e uma entrada na de destino. Mexe no caixa de cada empresa, não entra no DRE.
    </p>

    <UFormField label="De (origem)" required>
      <USelect v-model="state.from_company_id" :items="lookups.options.companies.value" :disabled="isEdit"
               placeholder="Empresa" class="w-full" />
    </UFormField>
    <UFormField label="Para (destino)" required>
      <USelect v-model="state.to_company_id" :items="toCompanies" :disabled="isEdit" placeholder="Empresa" class="w-full" />
    </UFormField>

    <UFormField label="Conta de saída">
      <USelect v-model="state.from_account_id" :items="fromAccounts" placeholder="Opcional" class="w-full" />
    </UFormField>
    <UFormField label="Conta de entrada">
      <USelect v-model="state.to_account_id" :items="toAccounts" placeholder="Opcional" class="w-full" />
    </UFormField>

    <UFormField label="Valor" required>
      <UInputNumber v-model="state.amount" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField label="Data" required>
      <UInput v-model="state.date" type="date" class="w-full" />
    </UFormField>

    <UFormField label="Status" required class="sm:col-span-2">
      <UTabs v-model="state.status" :items="STATUS_OPTIONS" :content="false" size="sm" />
    </UFormField>
    <UFormField label="Observações" class="sm:col-span-2">
      <UTextarea v-model="state.notes" :rows="2" class="w-full" />
    </UFormField>

    <div class="flex justify-end gap-2 sm:col-span-2">
      <UButton label="Cancelar" color="neutral" variant="ghost" @click="emit('cancel')" />
      <UButton type="submit" :label="isEdit ? 'Salvar' : 'Transferir'" :loading="saving" />
    </div>
  </form>
</template>
