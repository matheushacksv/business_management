<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Plan = components['schemas']['PlanOut']
definePageMeta({ permission: ['sales', 'view'] })
const { api, unwrap } = useApi()
const lookups = useLookups()

const columns = [
  { accessorKey: 'name', header: 'Plano' },
  { accessorKey: 'nfe_skus', header: 'Itens da NF-e (SKU no Bling)', cell: ({ row }: any) => h('span', { class: 'text-muted' },
    row.original.nfe_skus.length ? `${row.original.nfe_skus.length} · ${row.original.nfe_skus.join(', ')}` : '—') },
  { accessorKey: 'active', header: 'Situação', cell: ({ row }: any) => h('span', { class: row.original.active ? 'text-success' : 'text-dimmed' }, row.original.active ? 'Ativo' : 'Inativo') },
]
const fields = [
  { key: 'name', label: 'Nome', required: true },
  { key: 'active', label: 'Ativo', type: 'switch' as const },
  { key: 'nfe_skus', label: 'Itens da NF-e (SKU no Bling)', type: 'tags' as const, placeholder: 'AP01' },
]
</script>

<template>
  <AppCrud
    title="Catálogo" tabs="catalog" module="sales" singular="Plano"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/plan', { params: { query: {} } })) as Promise<Plan[]>"
    :create="(d) => unwrap(api.POST('/api/plan', { body: { name: d.name, nfe_skus: d.nfe_skus } }))"
    :update="(id, d) => unwrap(api.PATCH('/api/plan/{plan_id}', { params: { path: { plan_id: id } }, body: d }))"
    :remove="(id) => unwrap(api.DELETE('/api/plan/{plan_id}', { params: { path: { plan_id: id } } }))"
    @changed="lookups.refresh('plans')"
  />
</template>
