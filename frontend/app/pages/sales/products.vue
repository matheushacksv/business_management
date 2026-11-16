<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Product = components['schemas']['ProductOut']
definePageMeta({ permission: ['sales', 'view'] })
const { api, unwrap } = useApi()
const lookups = useLookups()

const columns = [
  { accessorKey: 'name', header: 'Produto/serviço' },
  { accessorKey: 'active', header: 'Situação', cell: ({ row }: any) => h('span', { class: row.original.active ? 'text-success' : 'text-dimmed' }, row.original.active ? 'Ativo' : 'Inativo') },
]
const fields = [
  { key: 'name', label: 'Nome', required: true },
  { key: 'active', label: 'Ativo', type: 'switch' as const },
]
</script>

<template>
  <AppCrud
    title="Produtos" module="sales" singular="Produto"
    :columns="columns" :fields="fields" :search-keys="['name']"
    :load="() => unwrap(api.GET('/api/product', { params: { query: {} } })) as Promise<Product[]>"
    :create="(d) => unwrap(api.POST('/api/product', { body: { name: d.name } }))"
    :update="(id, d) => unwrap(api.PATCH('/api/product/{product_id}', { params: { path: { product_id: id } }, body: d }))"
    :remove="(id) => unwrap(api.DELETE('/api/product/{product_id}', { params: { path: { product_id: id } } }))"
    @changed="lookups.refresh('products')"
  />
</template>
