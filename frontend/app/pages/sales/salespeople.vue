<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Salesperson = components['schemas']['SalespersonOut']
definePageMeta({ permission: ['sales', 'view'] })
const { api, unwrap } = useApi()
const auth = useAuth()
const lookups = useLookups()
if (auth.me.value?.is_admin) await lookups.ensure('users').catch(() => {})

const userLabel = (id: number | null) => (id ? lookups.cache.value.users?.find(u => u.id === id)?.email ?? `#${id}` : '—')
const columns = [
  { accessorKey: 'name', header: 'Nome' },
  { accessorKey: 'user_id', header: 'Login no sistema', cell: ({ row }: any) => userLabel(row.original.user_id) },
  { accessorKey: 'active', header: 'Situação', cell: ({ row }: any) => h('span', { class: row.original.active ? 'text-success' : 'text-dimmed' }, row.original.active ? 'Ativo' : 'Inativo') },
]
const fields = computed(() => [
  { key: 'name', label: 'Nome', required: true },
  { key: 'active', label: 'Ativo', type: 'switch' as const },
  ...(auth.me.value?.is_admin
    ? [{ key: 'user_id', label: 'Usuário (opcional)', type: 'select' as const, options: lookups.options.users.value, span: 2 as const }]
    : []),
])
</script>

<template>
  <AppCrud
    title="Vendedores e assessores" module="sales" singular="Vendedor"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/salesperson', { params: { query: {} } })) as Promise<Salesperson[]>"
    :create="(d) => unwrap(api.POST('/api/salesperson', { body: { name: d.name, user_id: d.user_id ?? null } }))"
    :update="(id, d) => unwrap(api.PATCH('/api/salesperson/{salesperson_id}', { params: { path: { salesperson_id: id } }, body: d }))"
    :remove="(id) => unwrap(api.DELETE('/api/salesperson/{salesperson_id}', { params: { path: { salesperson_id: id } } }))"
    @changed="lookups.refresh('salespeople')"
  />
</template>
