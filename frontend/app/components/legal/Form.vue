<script setup lang="ts">
import type { components } from '~/types/api'

// "Ação de cobrança por inadimplência": every field is required (client rule)
type Case = components['schemas']['CaseOut']
// companyId / summary: prefilled when coming from the dunning funnel
const props = defineProps<{ item?: Case | null; contactId?: number | null; contactName?: string | null; companyId?: number; summary?: string }>()
const emit = defineEmits<{ saved: [id: number]; cancel: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('companies', 'legalStages').catch(notifyError)

const c = props.item
const state = reactive({
  company_id: (c?.company_id ?? props.companyId) as number | undefined,
  contact_id: c?.contact_id ?? props.contactId ?? null,
  client_company: c?.client_company ?? '',
  contact_info: c?.contact_info ?? '',
  delivered: c?.delivered ?? '',
  proposal_amount: c?.proposal_amount != null ? Number(c.proposal_amount) : (undefined as number | undefined),
  paid_amount: c?.paid_amount != null ? Number(c.paid_amount) : (undefined as number | undefined),
  summary: c?.summary ?? props.summary ?? '',
  drive_link: c?.drive_link ?? '',
  stage_id: c?.stage_id as number | undefined,
  agreement: c?.agreement ?? '',
})
watch(lookups.options.companies, (list) => {
  if (!state.company_id && list.length) state.company_id = list[0]!.value as number
}, { immediate: true })

// New case: prefill from what the system already has (registration, sales, payments, collection attempts)
let autoSummary = ''  // replaced (not appended again) when the customer/company changes
watch(() => [state.contact_id, state.company_id], async ([contactId, companyId]) => {
  if (c || !contactId || !companyId) return
  try {
    const p = await unwrap(api.GET('/api/collection-case/prefill', { params: { query: { company_id: companyId as number, contact_id: contactId as number } } }))
    state.client_company ||= p.client_company
    state.contact_info ||= p.contact_info
    state.delivered ||= p.delivered
    state.summary = [state.summary.replace(autoSummary, '').trim(), p.summary].filter(Boolean).join(' ')
    autoSummary = p.summary
    if (state.proposal_amount == null && p.proposal_amount != null) state.proposal_amount = Number(p.proposal_amount)
    if (state.paid_amount == null) state.paid_amount = Number(p.paid_amount)
  } catch (e) {
    notifyError(e)
  }
}, { immediate: true })

// A new case cannot open in a stage that requires the checklist (ticked later, in the Drawer)
const stageList = computed(() => (lookups.cache.value.legalStages ?? []).filter(s => c || !s.requires_checklist))
const stageOptions = computed(() => stageList.value.map(s => ({ label: s.name, value: s.id })))
watch(stageList, list => { state.stage_id ??= list[0]?.id }, { immediate: true })
const needsAgreement = computed(() => !!stageList.value.find(s => s.id === state.stage_id)?.requires_agreement)
const saving = ref(false)

const missing = computed(() => {
  const fields: [unknown, string][] = [
    [state.company_id, 'Empresa do grupo'], [state.contact_id, 'Cliente'], [state.client_company.trim(), 'Empresa'],
    [state.contact_info.trim(), 'Contato'], [state.delivered.trim(), 'O que foi entregue'],
    [state.proposal_amount != null, 'Valor da proposta'], [state.paid_amount != null, 'Valor pago pelo cliente'],
    [state.summary.trim(), 'Resumo da situação'], [state.drive_link.trim(), 'Link do drive'],
  ]
  if (needsAgreement.value) fields.push([state.agreement.trim(), 'Acordo feito'])
  return fields.filter(([value]) => !value).map(([, label]) => label)
})

async function submit() {
  if (missing.value.length) {
    notifyError(`Preencha: ${missing.value.join(', ')}.`, 'Campos obrigatórios')
    return
  }
  saving.value = true
  const body = {
    client_company: state.client_company, contact_info: state.contact_info, delivered: state.delivered,
    proposal_amount: state.proposal_amount!.toFixed(2), paid_amount: state.paid_amount!.toFixed(2),
    summary: state.summary, drive_link: state.drive_link.trim(), stage_id: state.stage_id, agreement: state.agreement,
  }
  try {
    const saved = c
      ? await unwrap(api.PATCH('/api/collection-case/{case_id}', { params: { path: { case_id: c.id! } }, body }))
      : await unwrap(api.POST('/api/collection-case', {
          body: { ...body, company_id: state.company_id!, contact_id: state.contact_id! },
        }))
    notifySuccess(c ? 'Ação atualizada' : 'Ação aberta')
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
    <UFormField label="Cliente" required class="sm:col-span-2">
      <AppContactSelect v-if="!c" v-model="state.contact_id" :initial-label="contactName" />
      <p v-else class="text-sm text-highlighted">{{ c.contact_name }}</p>
    </UFormField>
    <UFormField label="Empresa do cliente" required>
      <UInput v-model="state.client_company" class="w-full" />
    </UFormField>
    <UFormField label="Contato" required>
      <UInput v-model="state.contact_info" class="w-full" />
    </UFormField>
    <UFormField label="O que foi entregue" required class="sm:col-span-2">
      <UTextarea v-model="state.delivered" :rows="2" autoresize class="w-full" />
    </UFormField>
    <UFormField label="Valor da proposta" required>
      <UInputNumber v-model="state.proposal_amount" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField label="Valor pago pelo cliente" required>
      <UInputNumber v-model="state.paid_amount" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField label="Resumo da situação do cliente" required class="sm:col-span-2">
      <UTextarea v-model="state.summary" :rows="3" autoresize class="w-full" />
    </UFormField>
    <UFormField label="Link do drive" required class="sm:col-span-2">
      <UInput v-model="state.drive_link" type="url" placeholder="Cole o link da pasta no Google Drive" icon="i-lucide-link" class="w-full" />
    </UFormField>
    <UFormField v-if="!c" label="Empresa do grupo" required>
      <USelect v-model="state.company_id" :items="lookups.options.companies.value" :disabled="!!companyId" class="w-full" />
    </UFormField>
    <UFormField label="Etapa" :class="c ? 'sm:col-span-2' : ''">
      <USelect v-model="state.stage_id" :items="stageOptions" class="w-full" />
    </UFormField>
    <UFormField v-if="needsAgreement || state.agreement" label="Acordo ou sentença" :required="needsAgreement" class="sm:col-span-2">
      <UTextarea v-model="state.agreement" :rows="2" autoresize
                 placeholder="Ex.: R$ 20.000,00 em 10x de R$ 2.000,00, primeiro vencimento dia 10/12" class="w-full" />
    </UFormField>
    <div class="sm:col-span-2 flex justify-end gap-2">
      <UButton label="Cancelar" color="neutral" variant="ghost" @click="emit('cancel')" />
      <UButton type="submit" :label="c ? 'Salvar' : 'Abrir caso'" :loading="saving" />
    </div>
  </form>
</template>
