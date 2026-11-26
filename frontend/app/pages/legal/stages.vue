<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Stage = components['schemas']['LegalStageOut']
definePageMeta({ permission: ['legal', 'view'] })
const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()

const yes = (v: boolean) => h('span', { class: v ? 'text-highlighted' : 'text-dimmed' }, v ? 'Sim' : '—')
const columns = [
  { accessorKey: 'position', header: 'Ordem' },
  { accessorKey: 'name', header: 'Etapa' },
  { accessorKey: 'requires_agreement', header: 'Exige acordo', cell: ({ row }: any) => yes(row.original.requires_agreement) },
  { accessorKey: 'requires_checklist', header: 'Exige checklist', cell: ({ row }: any) => yes(row.original.requires_checklist) },
]
const fields = [
  { key: 'name', label: 'Nome', required: true },
  { key: 'position', label: 'Ordem', type: 'number' as const, default: 0 },
  { key: 'requires_agreement', label: 'Exige acordo', type: 'switch' as const },
  { key: 'requires_checklist', label: 'Exige checklist', type: 'switch' as const },
]
// Old contracts' cancellation fine = 3 minimum wages
const auth = useAuth()
const minimumWage = ref<number>()
unwrap(api.GET('/api/legal-config')).then(c => (minimumWage.value = Number(c.minimum_wage))).catch(notifyError)
async function saveWage() {
  if (!minimumWage.value) return
  try {
    await unwrap(api.PUT('/api/legal-config', { body: { minimum_wage: minimumWage.value.toFixed(2) } }))
    notifySuccess('Salário mínimo salvo')
  } catch (e) {
    notifyError(e)
  }
}
const body = (d: Record<string, any>) => ({
  name: d.name, position: Number(d.position ?? 0), requires_agreement: !!d.requires_agreement, requires_checklist: !!d.requires_checklist,
})
</script>

<template>
  <AppCrud
    title="Configurar jurídico" tabs="legal" module="legal" singular="Etapa"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/legal-stage')) as Promise<Stage[]>"
    :create="(d) => unwrap(api.POST('/api/legal-stage', { body: body(d) }))"
    :update="(id, d) => unwrap(api.PATCH('/api/legal-stage/{stage_id}', { params: { path: { stage_id: id } }, body: body(d) }))"
    :remove="(id) => unwrap(api.DELETE('/api/legal-stage/{stage_id}', { params: { path: { stage_id: id } } }))"
    @changed="lookups.refresh('legalStages')"
  >
    <template #actions>
      <UFormField label="Salário mínimo" orientation="horizontal" class="items-center">
        <UInputNumber v-model="minimumWage" :min="1" :step="0.01" :increment="false" :decrement="false" :disabled="!auth.can('legal', 'change')"
                      :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-36" @blur="saveWage" />
      </UFormField>
    </template>
  </AppCrud>
</template>
