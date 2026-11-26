<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Stage = components['schemas']['LegalStageOut']
definePageMeta({ permission: ['legal', 'view'] })
const { api, unwrap } = useApi()
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
const body = (d: Record<string, any>) => ({
  name: d.name, position: Number(d.position ?? 0), requires_agreement: !!d.requires_agreement, requires_checklist: !!d.requires_checklist,
})
</script>

<template>
  <AppCrud
    title="Etapas do jurídico" module="legal" singular="Etapa"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/legal-stage')) as Promise<Stage[]>"
    :create="(d) => unwrap(api.POST('/api/legal-stage', { body: body(d) }))"
    :update="(id, d) => unwrap(api.PATCH('/api/legal-stage/{stage_id}', { params: { path: { stage_id: id } }, body: body(d) }))"
    :remove="(id) => unwrap(api.DELETE('/api/legal-stage/{stage_id}', { params: { path: { stage_id: id } } }))"
    @changed="lookups.refresh('legalStages')"
  />
</template>
