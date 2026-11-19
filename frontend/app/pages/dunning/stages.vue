<script setup lang="ts">
import type { components } from '~/types/api'

type Stage = components['schemas']['StageOut']
definePageMeta({ permission: ['dunning', 'view'] })
const { api, unwrap } = useApi()

const kindItems = Object.entries(DUNNING_LABELS.stageKind).map(([value, label]) => ({ label, value }))
const columns = [
  { accessorKey: 'position', header: 'Ordem' },
  { accessorKey: 'name', header: 'Etapa' },
  { accessorKey: 'kind', header: 'Tipo', cell: ({ row }: any) => DUNNING_LABELS.stageKind[row.original.kind] },
]
const fields = [
  { key: 'name', label: 'Nome', required: true },
  { key: 'position', label: 'Ordem', type: 'number' as const, default: 0 },
  { key: 'kind', label: 'Tipo', type: 'select' as const, options: kindItems, required: true, default: 'open', span: 2 as const },
]
const body = (d: Record<string, any>) => ({ name: d.name, position: Number(d.position ?? 0), kind: d.kind })
</script>

<template>
  <AppCrud
    title="Etapas da cobrança" module="dunning" singular="Etapa"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/dunning/stage')) as Promise<Stage[]>"
    :create="(d) => unwrap(api.POST('/api/dunning/stage', { body: body(d) }))"
    :update="(id, d) => unwrap(api.PATCH('/api/dunning/stage/{stage_id}', { params: { path: { stage_id: id } }, body: body(d) }))"
    :remove="(id) => unwrap(api.DELETE('/api/dunning/stage/{stage_id}', { params: { path: { stage_id: id } } }))"
  />
</template>
