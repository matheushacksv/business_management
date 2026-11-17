<script setup lang="ts">
import type { components } from '~/types/api'

type Contact = components['schemas']['ContactOut']
definePageMeta({ permission: ['contacts', 'view'] })
const { api, unwrap } = useApi()

const columns = [
  { accessorKey: 'name', header: 'Nome' },
  { accessorKey: 'company_name', header: 'Razão social' },
  { accessorKey: 'document', header: 'CPF/CNPJ' },
  { accessorKey: 'email', header: 'E-mail' },
  { accessorKey: 'phone', header: 'Telefone' },
]
const fields = [
  { key: 'name', label: 'Nome', required: true, span: 2 as const },
  { key: 'company_name', label: 'Razão social' },
  { key: 'document', label: 'CPF/CNPJ', hint: 'Com ou sem pontuação' },
  { key: 'email', label: 'E-mail', type: 'email' as const },
  { key: 'phone', label: 'Telefone' },
]
</script>

<template>
  <AppCrud
    title="Clientes e fornecedores" module="contacts" singular="Contato"
    :columns="columns" :fields="fields" :row-to="(c) => `/registers/contacts/${c.id}`" :search-keys="['name', 'company_name', 'document', 'email']"
    :load="() => unwrap(api.GET('/api/contact', { params: { query: {} } })) as Promise<Contact[]>"
    :create="(d) => unwrap(api.POST('/api/contact', { body: d as any }))"
    :update="(id, d) => unwrap(api.PATCH('/api/contact/{contact_id}', { params: { path: { contact_id: id } }, body: d }))"
    :remove="(id) => unwrap(api.DELETE('/api/contact/{contact_id}', { params: { path: { contact_id: id } } }))"
  />
</template>
