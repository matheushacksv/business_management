<script setup lang="ts">
import { h } from 'vue'
import type { components } from '~/types/api'

type Contact = components['schemas']['ContactOut']
definePageMeta({ permission: ['contacts', 'view'] })
const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const canMerge = computed(() => auth.can('contacts', 'change') && auth.can('contacts', 'delete'))

// Merge the picked contacts into the one chosen to stay
const merge = reactive({ open: false, keep: undefined as number | undefined, rows: [] as Contact[], done: () => {}, saving: false })
function openMerge(rows: Contact[], done: () => void) {
  Object.assign(merge, { open: true, keep: rows[0]?.id ?? undefined, rows, done })
}
async function confirmMerge() {
  merge.saving = true
  try {
    await unwrap(api.POST('/api/contact/{contact_id}/merge', {
      params: { path: { contact_id: merge.keep! } },
      body: { source_ids: merge.rows.map(r => r.id!).filter(id => id !== merge.keep) },
    }))
    notifySuccess(`${merge.rows.length} contatos mesclados`)
    merge.open = false
    merge.done()
  } catch (e) {
    notifyError(e)
  } finally {
    merge.saving = false
  }
}

const SStatusBadge = resolveComponent('SStatusBadge')
const columns = [
  { accessorKey: 'name', header: 'Nome' },
  { accessorKey: 'company_name', header: 'Razão social' },
  { accessorKey: 'document', header: 'CPF/CNPJ' },
  { accessorKey: 'email', header: 'E-mail' },
  { accessorKey: 'phone', header: 'Telefone' },
  { accessorKey: 'situation', header: 'Situação',
    cell: ({ row }: any) => row.original.situation ? h(SStatusBadge, { kind: 'situation', value: row.original.situation }) : null },
]
const situation = ref<string>()
const situationItems = [
  { label: 'Regularizado', value: 'ok' }, { label: 'Atenção', value: 'attention' }, { label: 'Crítico', value: 'critical' },
]
const fields = [
  { key: 'name', label: 'Nome', required: true, span: 2 as const },
  { key: 'company_name', label: 'Razão social' },
  { key: 'document', label: 'CPF/CNPJ' },
  { key: 'email', label: 'E-mail', type: 'email' as const },
  { key: 'phone', label: 'Telefone' },
  { key: 'postal_code', label: 'CEP' },
  { key: 'address_number', label: 'Número' },
  { key: 'address_complement', label: 'Complemento' },
  { key: 'address_district', label: 'Bairro' },
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
    :selectable="canMerge" :row-filter="situation ? (c) => c.situation === situation : undefined"
  >
    <template #toolbar>
      <USelect v-model="situation" :items="situationItems" placeholder="Situação" class="w-40" />
      <UButton v-if="situation" icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Limpar situação" @click="situation = undefined" />
    </template>
    <template #bulk="{ rows, clear, reload }">
      <UButton label="Mesclar" icon="i-lucide-merge" size="sm" variant="soft" :disabled="rows.length < 2"
               @click="openMerge(rows as Contact[], () => { clear(); reload() })" />
      <UModal v-model:open="merge.open" title="Mesclar contatos">
        <template #body>
          <URadioGroup v-model="merge.keep" legend="Manter" :items="merge.rows.map(r => ({ label: r.name, description: r.company_name || r.document || undefined, value: r.id! }))" />
        </template>
        <template #footer>
          <div class="flex w-full justify-end gap-2">
            <UButton label="Cancelar" color="neutral" variant="ghost" @click="merge.open = false" />
            <UButton label="Mesclar" color="warning" :loading="merge.saving" :disabled="!merge.keep" @click="confirmMerge" />
          </div>
        </template>
      </UModal>
    </template>
  </AppCrud>
</template>
