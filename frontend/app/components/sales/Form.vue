<script setup lang="ts">
import type { components } from '~/types/api'

type Sale = components['schemas']['SaleOut']
const props = defineProps<{ sale?: Sale | null }>()
const emit = defineEmits<{ saved: [id: number]; cancel: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('companies', 'products', 'plans', 'salespeople').catch(notifyError)

const s = props.sale
const state = reactive({
  company_id: s?.company_id as number | undefined,
  date: s?.date ?? today(),
  amount: s ? Number(s.amount) : (undefined as number | undefined),
  contact_id: s?.contact_id ?? null,
  product_id: s?.product_id ?? undefined,
  plan_id: s?.plan_id ?? undefined,
  salesperson_id: s?.salesperson_id ?? undefined,
  delivery_responsible_id: s?.delivery_responsible_id ?? undefined,
  payment_method: s?.payment_method ?? '',
  payment_terms: s?.payment_terms ?? '',
  installments_count: s?.installments_count ?? undefined,
  status: s?.status ?? 'active',
  notes: s?.notes ?? '',
})
watch(lookups.options.companies, (c) => {
  if (!state.company_id && c.length) state.company_id = c[0]!.value as number
}, { immediate: true })

const statusOptions = Object.entries(LABELS.saleStatus).map(([value, label]) => ({ value, label }))
const saving = ref(false)

async function submit() {
  if (!state.company_id || !state.amount || state.amount <= 0) {
    notifyError('Informe a empresa e um valor maior que zero.', 'Dados incompletos')
    return
  }
  saving.value = true
  const body = {
    date: state.date, amount: state.amount.toFixed(2), contact_id: state.contact_id,
    product_id: state.product_id ?? null, plan_id: state.plan_id ?? null, salesperson_id: state.salesperson_id ?? null,
    delivery_responsible_id: state.delivery_responsible_id ?? null, payment_method: state.payment_method,
    payment_terms: state.payment_terms, installments_count: state.installments_count || null,
    status: state.status as any, notes: state.notes,
  }
  try {
    const saved = s
      ? await unwrap(api.PATCH('/api/sale/{sale_id}', { params: { path: { sale_id: s.id! } }, body }))
      : await unwrap(api.POST('/api/sale', { body: { ...body, company_id: state.company_id } }))
    notifySuccess(s ? 'Venda atualizada' : 'Venda registrada')
    emit('saved', saved.id!)
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="submit">
    <UFormField label="Empresa" required>
      <USelect v-model="state.company_id" :items="lookups.options.companies.value" :disabled="!!s" class="w-full" />
    </UFormField>
    <UFormField label="Data da venda" required>
      <UInput v-model="state.date" type="date" class="w-full" />
    </UFormField>
    <UFormField label="Cliente" class="sm:col-span-2">
      <AppContactSelect v-model="state.contact_id" :initial-label="s?.contact_name" />
    </UFormField>
    <UFormField label="Valor do contrato" required>
      <UInputNumber v-model="state.amount" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField label="Produto/serviço">
      <USelect v-model="state.product_id" :items="lookups.options.products.value" placeholder="Opcional" class="w-full" />
    </UFormField>
    <UFormField label="Plano">
      <USelect v-model="state.plan_id" :items="lookups.options.plans.value" placeholder="Opcional" class="w-full" />
    </UFormField>
    <UFormField label="Vendedor">
      <USelect v-model="state.salesperson_id" :items="lookups.options.salespeople.value" placeholder="Opcional" class="w-full" />
    </UFormField>
    <UFormField label="Responsável pela entrega">
      <USelect v-model="state.delivery_responsible_id" :items="lookups.options.salespeople.value" placeholder="Opcional" class="w-full" />
    </UFormField>
    <UFormField label="Forma de pagamento">
      <UInput v-model="state.payment_method" placeholder="Ex.: Boleto - Asaas, PIX" class="w-full" />
    </UFormField>
    <UFormField label="Nº de parcelas">
      <UInputNumber v-model="state.installments_count" :min="1" class="w-full" />
    </UFormField>
    <UFormField label="Condições" class="sm:col-span-2">
      <UInput v-model="state.payment_terms" placeholder="Ex.: Entrada + 11 parcelas" class="w-full" />
    </UFormField>
    <UFormField label="Status">
      <USelect v-model="state.status" :items="statusOptions" class="w-full" />
    </UFormField>
    <UFormField label="Observações" class="sm:col-span-2">
      <UTextarea v-model="state.notes" :rows="2" class="w-full" />
    </UFormField>
    <div class="flex justify-end gap-2 sm:col-span-2">
      <UButton label="Cancelar" color="neutral" variant="ghost" @click="emit('cancel')" />
      <UButton type="submit" :label="s ? 'Salvar' : 'Registrar venda'" :loading="saving" />
    </div>
  </form>
</template>
