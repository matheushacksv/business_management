<script setup lang="ts">
import { h, resolveComponent } from 'vue'
import type { components } from '~/types/api'

type User = components['schemas']['UserOut']
definePageMeta({ permission: ['users', 'view'] })
const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const lookups = useLookups()
await lookups.ensure('companies')
const UBadge = resolveComponent('UBadge')
const crud = ref()

const companyNames = (ids: number[]) =>
  ids.map(id => lookups.cache.value.companies?.find(c => c.id === id)?.name).filter(Boolean).join(', ') || '—'

const columns = [
  { accessorKey: 'email', header: 'E-mail', cell: ({ row }: any) => h('div', [
    h('p', { class: 'text-highlighted' }, row.original.email),
    row.original.name ? h('p', { class: 'text-xs text-dimmed' }, row.original.name) : null,
  ]) },
  { accessorKey: 'role', header: 'Perfil', cell: ({ row }: any) => (row.original.is_superuser ? 'Superusuário' : LABELS.role[row.original.role]) },
  { accessorKey: 'company_ids', header: 'Empresas', cell: ({ row }: any) => companyNames(row.original.company_ids) },
  { accessorKey: 'is_active', header: 'Situação', cell: ({ row }: any) => h(UBadge, {
    label: row.original.is_active ? 'Ativo' : 'Desativado', color: row.original.is_active ? 'success' : 'neutral', variant: 'subtle', size: 'sm',
  }) },
]
const fields = computed(() => [
  { key: 'email', label: 'E-mail', type: 'email' as const, required: true, createOnly: true, span: 2 as const },
  { key: 'password', label: 'Senha', type: 'password' as const, required: true, createOnly: true },
  { key: 'repeat_password', label: 'Repita a senha', type: 'password' as const, required: true, createOnly: true },
  { key: 'name', label: 'Nome' },
  { key: 'role', label: 'Perfil', type: 'select' as const, options: ROLE_OPTIONS, required: true },
  { key: 'company_ids', label: 'Empresas que pode acessar', type: 'multiselect' as const, options: lookups.options.companies.value,
    span: 2 as const, hint: 'Administradores acessam todas' },
])

async function deactivate(id: number | null, close: () => void, reload: () => void) {
  if (!id || !confirm('Desativar este usuário? Ele perde o acesso imediatamente.')) return
  try {
    await unwrap(api.POST('/api/user/deactivate/{user_id}', { params: { path: { user_id: id } } }))
    notifySuccess('Usuário desativado')
    close()
    reload()
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <AppCrud
    ref="crud"
    title="Usuários" module="users" singular="Usuário"
    :columns="columns" :fields="fields" :search-keys="['email', 'name']"
    :to-form="(u: User) => ({ ...u, name: u.name ?? '' })"
    :load="() => unwrap(api.GET('/api/user')) as Promise<User[]>"
    :create="(d) => unwrap(api.POST('/api/user', { body: d as any }))"
    :update="(id, d) => unwrap(api.PATCH('/api/user/{user_id}', { params: { path: { user_id: id } }, body: d as any }))"
  >
    <template #form-actions="{ id, close, reload }">
      <UButton v-if="id && id !== auth.me.value?.id && auth.can('users', 'delete')" label="Desativar" icon="i-lucide-user-x"
               color="warning" variant="ghost" @click="deactivate(id, close, reload)" />
    </template>
  </AppCrud>
</template>
