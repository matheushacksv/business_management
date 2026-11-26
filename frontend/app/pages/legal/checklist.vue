<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Item = components['schemas']['ChecklistItemOut']
definePageMeta({ permission: ['users', 'change'] })
const { api, unwrap } = useApi()

const AUTO: Record<string, string> = {
  customer_data: 'Cadastro do cliente completo', contract: 'Contrato anexado na venda', amounts: 'Valores informados',
  attempts: 'Tentativas de cobrança registradas', responsible: 'Responsável jurídico definido',
}
const columns = [
  { accessorKey: 'position', header: '#' },
  { accessorKey: 'label', header: 'Item' },
  { accessorKey: 'auto', header: 'Marcação', cell: ({ row }: any) => row.original.auto ? AUTO[row.original.auto] : 'Manual' },
  { accessorKey: 'required', header: 'Obrigatório', cell: ({ row }: any) => (row.original.required ? 'Sim' : 'Não') },
  { accessorKey: 'active', header: 'Situação', cell: ({ row }: any) => h('span', { class: row.original.active ? 'text-success' : 'text-dimmed' }, row.original.active ? 'Ativo' : 'Inativo') },
]
const fields = [
  { key: 'label', label: 'Item', required: true, span: 2 as const },
  { key: 'auto', label: 'Marcação', type: 'select' as const, options: [{ label: 'Manual', value: '' }, ...Object.entries(AUTO).map(([value, label]) => ({ label, value }))], default: '' },
  { key: 'position', label: 'Ordem', type: 'number' as const },
  { key: 'required', label: 'Obrigatório', type: 'switch' as const, default: true },
  { key: 'active', label: 'Ativo', type: 'switch' as const, default: true },
]
const body = (d: Record<string, any>) => ({ label: d.label, auto: d.auto ?? '', position: Number(d.position ?? 0), required: !!d.required, active: !!d.active })
</script>

<template>
  <AppCrud
    title="Configurar jurídico" tabs="legal" module="users" singular="Item"
    :columns="columns" :fields="fields" :search-keys="['label']"
    :load="() => unwrap(api.GET('/api/legal-checklist-item')) as Promise<Item[]>"
    :create="(d) => unwrap(api.POST('/api/legal-checklist-item', { body: body(d) as any }))"
    :update="(id, d) => unwrap(api.PUT('/api/legal-checklist-item/{item_id}', { params: { path: { item_id: id } }, body: body(d) as any }))"
    :remove="(id) => unwrap(api.DELETE('/api/legal-checklist-item/{item_id}', { params: { path: { item_id: id } } }))"
  />
</template>
