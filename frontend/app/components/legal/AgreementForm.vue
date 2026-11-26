<script setup lang="ts">
import type { components } from '~/types/api'

// Agreement / sentence: its installments replace the case's open ones
type Case = components['schemas']['CaseOut']
const props = defineProps<{ caseId: number; stageId?: number }>()
const emit = defineEmits<{ saved: [item: Case]; cancel: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('legalStages').catch(notifyError)
const stageOptions = computed(() => (lookups.cache.value.legalStages ?? []).filter(s => s.requires_agreement).map(s => ({ label: s.name, value: s.id })))

const state = reactive({
  stage_id: props.stageId as number | undefined,
  down_payment: undefined as number | undefined,
  down_payment_date: '',
  total: undefined as number | undefined,
  count: 1,
  first_due: '',
  text: '',
})
watch(stageOptions, list => { state.stage_id ??= list[0]?.value }, { immediate: true })
const installment = computed(() => state.total ? Math.max(state.total - (state.down_payment ?? 0), 0) / state.count : 0)
const ready = computed(() => !!state.stage_id && state.count >= 1 && installment.value > 0 && !!state.first_due
  && (!state.down_payment || !!state.down_payment_date))

const saving = ref(false)
async function submit() {
  saving.value = true
  try {
    const saved = await unwrap(api.POST('/api/collection-case/{case_id}/agreement', {
      params: { path: { case_id: props.caseId } },
      body: {
        stage_id: state.stage_id, text: state.text, total: state.total!.toFixed(2), count: state.count, first_due: state.first_due,
        down_payment: state.down_payment ? state.down_payment.toFixed(2) : null, down_payment_date: state.down_payment ? state.down_payment_date : null,
      },
    }))
    notifySuccess('Acordo registrado')
    emit('saved', saved)
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}
const money = { style: 'currency', currency: 'BRL' } as const
</script>

<template>
  <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="submit">
    <UFormField v-if="stageOptions.length > 1" label="Etapa" class="sm:col-span-2">
      <USelect v-model="state.stage_id" :items="stageOptions" class="w-full" />
    </UFormField>
    <UFormField label="Valor total do acordo" required class="sm:col-span-2">
      <UInputNumber v-model="state.total" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="money" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField label="Entrada">
      <UInputNumber v-model="state.down_payment" :min="0" :step="0.01" :increment="false" :decrement="false"
                    :format-options="money" locale="pt-BR" class="w-full" />
    </UFormField>
    <UFormField label="Data da entrada" :required="!!state.down_payment">
      <UInput v-model="state.down_payment_date" type="date" class="w-full" />
    </UFormField>
    <UFormField label="Parcelas" required>
      <UInputNumber v-model="state.count" :min="1" :max="120" class="w-full" />
    </UFormField>
    <UFormField label="Valor de cada parcela">
      <p class="py-1.5 text-sm text-highlighted tabular">{{ formatMoney(installment) }}</p>
    </UFormField>
    <UFormField label="Primeiro vencimento" required>
      <UInput v-model="state.first_due" type="date" class="w-full" />
    </UFormField>
    <UFormField label="Observações" class="sm:col-span-2">
      <UTextarea v-model="state.text" :rows="2" autoresize class="w-full" />
    </UFormField>
    <div class="sm:col-span-2 flex justify-end gap-2">
      <UButton label="Cancelar" color="neutral" variant="ghost" @click="emit('cancel')" />
      <UButton type="submit" label="Registrar acordo" :loading="saving" :disabled="!ready" />
    </div>
  </form>
</template>
