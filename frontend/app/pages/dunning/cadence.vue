<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Step = components['schemas']['StepOut']
definePageMeta({ permission: ['dunning', 'view'] })
const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()

// Installments due before this date stay out of the funnel
const startDate = ref('')
unwrap(api.GET('/api/dunning/config')).then(c => { startDate.value = c.start_date ?? '' }).catch(notifyError)
async function saveStart() {
  try {
    await unwrap(api.PUT('/api/dunning/config', { body: { start_date: startDate.value || null } }))
    notifySuccess('Data de início salva')
  } catch (e) {
    notifyError(e)
  }
}

const kindItems = Object.entries(DUNNING_LABELS.activityKind).map(([value, label]) => ({ label, value }))
const columns = [
  { accessorKey: 'day', header: 'Dia de atraso', cell: ({ row }: any) => `${row.original.day}º dia` },
  { accessorKey: 'kind', header: 'Tipo', cell: ({ row }: any) => DUNNING_LABELS.activityKind[row.original.kind] },
  { accessorKey: 'title', header: 'Atividade' },
  { accessorKey: 'template', header: 'Mensagem', cell: ({ row }: any) => h('p', { class: 'max-w-md truncate text-muted' }, row.original.template || '—') },
  { accessorKey: 'active', header: 'Situação', cell: ({ row }: any) => h('span', { class: row.original.active ? 'text-success' : 'text-dimmed' }, row.original.active ? 'Ativa' : 'Inativa') },
]
const fields = [
  { key: 'day', label: 'Dia de atraso', type: 'number' as const, required: true, default: 1 },
  { key: 'kind', label: 'Tipo', type: 'select' as const, options: kindItems, required: true, default: 'message' },
  { key: 'title', label: 'Atividade', required: true, span: 2 as const },
  { key: 'template', label: 'Mensagem', type: 'textarea' as const, placeholder: '{cliente} {empresa} {valor} {parcelas} {vencimento} {dias}' },
  { key: 'active', label: 'Ativa', type: 'switch' as const, default: true },
]
const body = (d: Record<string, any>) => ({ day: Number(d.day), kind: d.kind, title: d.title, template: d.template ?? '', active: !!d.active })
</script>

<template>
  <AppCrud
    title="Cadência da cobrança" module="dunning" singular="Atividade"
    :columns="columns" :fields="fields" :search-keys="['title', 'template']"
    :load="() => unwrap(api.GET('/api/dunning/cadence')) as Promise<Step[]>"
    :create="(d) => unwrap(api.POST('/api/dunning/cadence', { body: body(d) }))"
    :update="(id, d) => unwrap(api.PATCH('/api/dunning/cadence/{step_id}', { params: { path: { step_id: id } }, body: body(d) }))"
    :remove="(id) => unwrap(api.DELETE('/api/dunning/cadence/{step_id}', { params: { path: { step_id: id } } }))"
  >
    <template #actions>
      <UFormField label="Cobrar atrasos a partir de" orientation="horizontal" class="items-center">
        <UInput v-model="startDate" type="date" :disabled="!auth.can('dunning', 'change')" class="w-40" @change="saveStart" />
      </UFormField>
    </template>
  </AppCrud>
</template>
