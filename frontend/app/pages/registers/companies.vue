<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { components } from '~/types/api'

type Company = components['schemas']['CompanyOut']
definePageMeta({ permission: ['companies', 'view'] })
const { api, unwrap } = useApi()
const lookups = useLookups()
const SMoney = resolveComponent('SMoney')

const formatCnpj = (v: string) => (/^\d{14}$/.test(v) ? v.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5') : v)
const columns = [
  { accessorKey: 'name', header: 'Empresa' },
  { accessorKey: 'cnpj', header: 'CNPJ', cell: ({ row }: any) => formatCnpj(row.original.cnpj) },
  { accessorKey: 'initial_balance', header: 'Saldo inicial', cell: ({ row }: any) => h(SMoney, { value: row.original.initial_balance, signed: true }) },
  { accessorKey: 'tax_rate', header: 'Imposto', cell: ({ row }: any) => `${Number(row.original.tax_rate).toLocaleString('pt-BR')}%` },
]
const fields = [
  { key: 'name', label: 'Nome', required: true, span: 2 as const },
  { key: 'cnpj', label: 'CNPJ', required: true },
  { key: 'initial_balance', label: 'Saldo inicial', type: 'money' as const },
  { key: 'tax_rate', label: 'Imposto (%)', type: 'number' as const, step: 0.01, default: 10 },
]
</script>

<template>
  <AppCrud
    title="Empresas" module="companies" singular="Empresa"
    :columns="columns" :fields="fields" :search-keys="['name', 'cnpj']"
    :to-form="(c: Company) => ({ ...c, initial_balance: Number(c.initial_balance), tax_rate: Number(c.tax_rate) })"
    :load="() => unwrap(api.GET('/api/company')) as Promise<Company[]>"
    :create="(d) => unwrap(api.POST('/api/company', { body: d as any }))"
    :update="(id, d) => unwrap(api.PATCH('/api/company/{company_id}', { params: { path: { company_id: id } }, body: d as any }))"
    :remove="(id) => unwrap(api.DELETE('/api/company/{company_id}', { params: { path: { company_id: id } } }))"
    @changed="lookups.refresh('companies')"
  />
</template>
