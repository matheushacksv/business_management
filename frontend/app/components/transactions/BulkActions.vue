<script setup lang="ts">
import type { components } from '~/types/api'

type Transaction = components['schemas']['TransactionOut']
type Change = components['schemas']['BulkUpdateTransactions']
const props = defineProps<{ rows: Transaction[] }>()
const emit = defineEmits<{ done: []; clear: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const lookups = useLookups()
lookups.ensure('companies', 'subgroups').catch(notifyError)

const ids = computed(() => props.rows.map(r => r.id!))
const total = computed(() => props.rows.reduce((s, r) => s + (r.type === 'inflow' ? 1 : -1) * Number(r.amount), 0))
const busy = ref(false)

async function apply(change: Omit<Change, 'ids'>) {
  busy.value = true
  try {
    const { affected } = await unwrap(api.POST('/api/transaction/bulk-update', { body: { ids: ids.value, ...change } }))
    notifySuccess(`${affected} lançamento(s) alterado(s)`)
    editOpen.value = false
    emit('done')
  } catch (e) {
    notifyError(e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  const n = ids.value.length
  if (!await confirm({ title: `Excluir ${n} lançamento(s)?`, description: 'Esta ação não pode ser desfeita.', confirmLabel: 'Excluir', color: 'error' })) return
  busy.value = true
  try {
    const { affected } = await unwrap(api.POST('/api/transaction/bulk-delete', { body: { ids: ids.value } }))
    notifySuccess(`${affected} lançamento(s) excluído(s)`)
    emit('done')
  } catch (e) {
    notifyError(e)
  } finally {
    busy.value = false
  }
}

// Edit modal: one field at a time
const FIELDS = computed(() => [
  { label: 'Subgrupo', value: 'subgroup_id' },
  { label: 'Cliente/Fornecedor', value: 'contact_id' },
  { label: 'Empresa', value: 'company_id' },
  { label: 'Data', value: 'date' },
  { label: 'Adiantar/adiar dias', value: 'shift_days' },
  ...(auth.can('sales', 'change') ? [{ label: 'Venda', value: 'sale_id' }] : []),
])
const editOpen = ref(false)
const field = ref<keyof Omit<Change, 'ids'>>('subgroup_id')
const value = ref<any>(null)
watch(field, () => { value.value = field.value === 'shift_days' ? 30 : null })
const nullable = computed(() => field.value === 'contact_id' || field.value === 'sale_id')
const ready = computed(() => nullable.value || (value.value !== null && value.value !== '' && value.value !== 0))
function openEdit() {
  field.value = 'subgroup_id'
  value.value = null
  editOpen.value = true
}

// Sales of the selected contacts first; typing searches all
const saleSearch = ref('')
const sales = ref<{ label: string; value: number }[]>([])
let timer: ReturnType<typeof setTimeout> | undefined
async function loadSales() {
  const contacts = [...new Set(props.rows.map(r => r.contact).filter(Boolean))] as number[]
  const query = saleSearch.value ? { search: saleSearch.value } : contacts.length ? { contact_id: contacts } : {}
  try {
    const data = await unwrap(api.GET('/api/sale', { params: { query: { ...query, ordering: '-date' } as any } }))
    sales.value = data.items.map(s => ({
      label: `${s.contact_name ?? '—'} · ${formatDate(s.date)} · ${formatMoney(s.amount)}`, value: s.id!,
    }))
  } catch (e) {
    notifyError(e)
  }
}
watch(saleSearch, () => { clearTimeout(timer); timer = setTimeout(loadSales, 250) })
watch(field, f => { if (f === 'sale_id') loadSales() })
</script>

<template>
  <AppBulkBar :count="rows.length" @clear="emit('clear')">
    <span class="text-sm tabular whitespace-nowrap" :class="total < 0 ? 'text-error' : 'text-success'">{{ formatMoney(total) }}</span>
    <template v-if="auth.can('transactions', 'change')">
      <UButton label="Realizado" icon="i-lucide-check-check" size="sm" variant="soft" :loading="busy" @click="apply({ status: 'realized' })" />
      <UButton label="Previsto" icon="i-lucide-clock" size="sm" color="neutral" variant="soft" :loading="busy" @click="apply({ status: 'planned' })" />
      <UButton label="Editar" icon="i-lucide-pencil" size="sm" color="neutral" variant="soft" @click="openEdit" />
    </template>
    <UButton v-if="auth.can('transactions', 'delete')" icon="i-lucide-trash-2" size="sm" color="error" variant="ghost"
             aria-label="Excluir" :loading="busy" @click="remove" />
  </AppBulkBar>

  <UModal v-model:open="editOpen" :title="`Editar ${rows.length} lançamento(s)`">
    <template #body>
      <div class="flex flex-col gap-3">
        <UFormField label="Campo">
          <USelect v-model="field" :items="FIELDS" class="w-full" />
        </UFormField>
        <UFormField label="Novo valor">
          <USelectMenu v-if="field === 'subgroup_id'" v-model="value" :items="lookups.options.subgroups.value" value-key="value" class="w-full" />
          <AppContactSelect v-else-if="field === 'contact_id'" v-model="value" />
          <USelect v-else-if="field === 'company_id'" v-model="value" :items="lookups.options.companies.value" class="w-full" />
          <UInput v-else-if="field === 'date'" v-model="value" type="date" class="w-full" />
          <UInputNumber v-else-if="field === 'shift_days'" v-model="value" class="w-full" />
          <USelectMenu v-else-if="field === 'sale_id'" v-model="value" v-model:search-term="saleSearch" :items="sales"
                       value-key="value" ignore-filter clear placeholder="Buscar venda" class="w-full" />
        </UFormField>
      </div>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton label="Cancelar" color="neutral" variant="ghost" @click="editOpen = false" />
        <UButton label="Aplicar" :loading="busy" :disabled="!ready" @click="apply({ [field]: value ?? null })" />
      </div>
    </template>
  </UModal>
</template>
