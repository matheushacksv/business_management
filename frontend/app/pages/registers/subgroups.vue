<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Subgroup = components['schemas']['SubgroupOut']
definePageMeta({ permission: ['subgroups', 'view'] })
const { api, unwrap } = useApi()
const lookups = useLookups()
await lookups.ensure('groups')

const columns = [
  { accessorKey: 'group', header: 'Grupo', cell: ({ row }: any) => lookups.groupLabel(row.original.group) },
  { accessorKey: 'name', header: 'Subgrupo', cell: ({ row }: any) => h('span', { class: 'text-highlighted' }, row.original.name) },
]
const fields = computed(() => [
  { key: 'group', label: 'Grupo do DRE', type: 'select' as const, options: lookups.options.groups.value, required: true },
  { key: 'name', label: 'Nome', required: true },
])
</script>

<template>
  <AppCrud
    title="Plano de contas" module="subgroups" singular="Subgrupo"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/subgroup', { params: { query: {} } })) as Promise<Subgroup[]>"
    :create="(d) => unwrap(api.POST('/api/subgroup', { body: d as any }))"
    :update="(id, d) => unwrap(api.PATCH('/api/subgroup/{subgroup_id}', { params: { path: { subgroup_id: id } }, body: d as any }))"
    :remove="(id) => unwrap(api.DELETE('/api/subgroup/{subgroup_id}', { params: { path: { subgroup_id: id } } }))"
    @changed="lookups.refresh('subgroups')"
  />
</template>
