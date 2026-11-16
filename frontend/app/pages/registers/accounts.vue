<script setup lang="ts">
import type { components } from '~/types/api'

type Account = components['schemas']['AccountOut']
definePageMeta({ permission: ['accounts', 'view'] })
const { api, unwrap } = useApi()
const lookups = useLookups()
await lookups.ensure('companies')

const companyName = (id: number) => lookups.cache.value.companies?.find(c => c.id === id)?.name ?? '—'
const columns = [
  { accessorKey: 'name', header: 'Conta' },
  { accessorKey: 'company', header: 'Empresa', cell: ({ row }: any) => companyName(row.original.company) },
]
const fields = computed(() => [
  { key: 'company_id', label: 'Empresa', type: 'select' as const, options: lookups.options.companies.value,
    required: true, readonlyOnEdit: true },
  { key: 'name', label: 'Nome', required: true, placeholder: 'Ex.: Itaú CC 1234, Cartão C6' },
])
</script>

<template>
  <AppCrud
    title="Contas bancárias e cartões" module="accounts" singular="Conta"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :to-form="(a: Account) => ({ company_id: a.company, name: a.name })"
    :load="() => unwrap(api.GET('/api/account', { params: { query: {} } })) as Promise<Account[]>"
    :create="(d) => unwrap(api.POST('/api/account', { body: d as any }))"
    :update="(id, d) => unwrap(api.PATCH('/api/account/{account_id}', { params: { path: { account_id: id } }, body: { name: d.name } }))"
    :remove="(id) => unwrap(api.DELETE('/api/account/{account_id}', { params: { path: { account_id: id } } }))"
    @changed="lookups.refresh('accounts')"
  />
</template>
