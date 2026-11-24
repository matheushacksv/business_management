<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Stage = components['schemas']['StageOut']
definePageMeta({ permission: ['dunning', 'view'] })
const { api, unwrap, notifyError, notifySuccess } = useApi()

const columns = [
  { accessorKey: 'position', header: 'Ordem' },
  { accessorKey: 'name', header: 'Etapa' },
  { accessorKey: 'severity', header: 'Cor', cell: ({ row }: any) => h(SStatusBadge, { kind: 'situation', value: row.original.severity }) },
]
const SStatusBadge = resolveComponent('SStatusBadge')
const fields = [
  { key: 'name', label: 'Nome', required: true },
  { key: 'position', label: 'Ordem', type: 'number' as const, default: 0 },
  { key: 'severity', label: 'Cor', type: 'select' as const, required: true, default: 'attention',
    options: [{ label: 'Amarelo · atenção', value: 'attention' }, { label: 'Vermelho · crítico', value: 'critical' }] },
]
const body = (d: Record<string, any>) => ({ name: d.name, position: Number(d.position ?? 0), severity: d.severity })

// Traffic light rules
const auth = useAuth()
const config = reactive({ start_date: null as string | null, critical_days: 30, attention_days: 1, legal_critical: true })
unwrap(api.GET('/api/dunning/config')).then(c => Object.assign(config, c)).catch(notifyError)
async function saveConfig() {
  try {
    Object.assign(config, await unwrap(api.PUT('/api/dunning/config', { body: { ...config } })))
    notifySuccess('Salvo')
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <AppCrud
    title="Etapas da cobrança" module="dunning" singular="Etapa"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/dunning/stage')) as Promise<Stage[]>"
    :create="(d) => unwrap(api.POST('/api/dunning/stage', { body: body(d) }))"
    :update="(id, d) => unwrap(api.PATCH('/api/dunning/stage/{stage_id}', { params: { path: { stage_id: id } }, body: body(d) }))"
    :remove="(id) => unwrap(api.DELETE('/api/dunning/stage/{stage_id}', { params: { path: { stage_id: id } } }))"
  >
    <template #actions>
      <UFormField label="Atenção após (dias de atraso)" orientation="horizontal" class="items-center">
        <UInputNumber v-model="config.attention_days" :min="1" :max="config.critical_days" :disabled="!auth.can('dunning', 'change')"
                      class="w-28" @blur="saveConfig" />
      </UFormField>
      <UFormField label="Crítico após (dias de atraso)" orientation="horizontal" class="items-center">
        <UInputNumber v-model="config.critical_days" :min="1" :max="365" :disabled="!auth.can('dunning', 'change')"
                      class="w-28" @blur="saveConfig" />
      </UFormField>
      <USwitch v-model="config.legal_critical" label="Jurídico = crítico" :disabled="!auth.can('dunning', 'change')"
               @update:model-value="saveConfig" />
    </template>
  </AppCrud>
</template>
