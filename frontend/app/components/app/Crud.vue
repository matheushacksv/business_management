<script setup lang="ts" generic="T extends { id?: number | null }">
// Generic list + create/edit modal for the simple registers (contacts, subgroups, accounts...).
import type { TableColumn } from '@nuxt/ui'
import type { Action } from '~/composables/useAuth'

export interface CrudField {
  key: string
  label: string
  type?: 'text' | 'email' | 'password' | 'money' | 'number' | 'select' | 'multiselect' | 'switch' | 'textarea' | 'tags'
  options?: { label: string; value: unknown }[]
  required?: boolean | ((state: Record<string, any>) => boolean)  // function: depends on other fields
  createOnly?: boolean      // hidden when editing
  readonlyOnEdit?: boolean  // shown but locked when editing
  placeholder?: string
  hint?: string
  span?: 2
  step?: number             // number fields: decimals allowed
  default?: unknown         // initial value when creating
}

const props = defineProps<{
  title: string
  tabs?: import('~/composables/usePageTabs').TabGroup
  module: string
  singular: string
  columns: TableColumn<T>[]
  fields: CrudField[]
  load: () => Promise<T[]>
  create?: (data: Record<string, any>) => Promise<unknown>
  update?: (id: number, data: Record<string, any>) => Promise<unknown>
  remove?: (id: number) => Promise<unknown>
  toForm?: (row: T) => Record<string, any>   // row -> form values (defaults to same keys)
  searchKeys?: string[]                        // client-side search over these keys
  rowTo?: (row: T) => string                   // clicking a row opens this page instead of the edit modal
  selectable?: boolean                         // checkbox column + #bulk slot (actions over the picked rows)
  rowFilter?: (row: T) => boolean              // extra client-side filter (e.g. a select in #toolbar)
}>()
const emit = defineEmits<{ changed: [] }>()

const { notifyError, notifySuccess } = useApi()
const confirm = useConfirm()
const auth = useAuth()
const can = (action: Action) => auth.can(props.module, action)

const rows = ref<T[]>([]) as Ref<T[]>
const loading = ref(false)
const search = ref('')

async function reload() {
  loading.value = true
  try { rows.value = await props.load() } catch (e) { notifyError(e) } finally { loading.value = false }
}
onMounted(reload)
defineExpose({ reload })

const filtered = computed(() => {
  const term = search.value.trim().toLowerCase()
  const base = props.rowFilter ? rows.value.filter(props.rowFilter) : rows.value
  if (!term || !props.searchKeys) return base
  return base.filter(r => props.searchKeys!.some(k => String((r as any)[k] ?? '').toLowerCase().includes(term)))
})

// Client-side pages: the API returns every row (small lists), but rendering hundreds of
// table rows at once is what makes the screen slow.
// ponytail: move to server-side pagination if a list reaches the thousands
const PAGE_SIZE = 50
const page = ref(1)
watch(search, () => { page.value = 1 })
watch(() => filtered.value.length, (n) => { page.value = Math.min(page.value, Math.max(1, Math.ceil(n / PAGE_SIZE))) })
const pageRows = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))

const selection = useSelection<T>(() => pageRows.value)
const tableColumns = computed(() => props.selectable ? [selection.column, ...props.columns] : props.columns)

// Form modal
const open = ref(false)
const editingId = ref<number | null>(null)
const state = reactive<Record<string, any>>({})
const saving = ref(false)
const isRequired = (f: CrudField) => typeof f.required === 'function' ? f.required(state) : !!f.required
const visibleFields = computed(() => props.fields.filter(f => !(editingId.value && f.createOnly)))

function blank(field: CrudField) {
  if (field.default !== undefined) return field.default
  return field.type === 'multiselect' || field.type === 'tags' ? [] : field.type === 'switch' ? false : field.type === 'money' || field.type === 'number' ? 0 : field.type === 'select' ? undefined : ''
}

function openCreate() {
  editingId.value = null
  for (const f of props.fields) state[f.key] = blank(f)
  open.value = true
}

function openEdit(row: T) {
  if (!props.update || !can('change')) return
  editingId.value = row.id!
  const values = props.toForm ? props.toForm(row) : (row as Record<string, any>)
  for (const f of props.fields) state[f.key] = values[f.key] ?? blank(f)
  open.value = true
}

async function save() {
  const missing = visibleFields.value.filter(f => isRequired(f) && (state[f.key] === '' || state[f.key] === undefined || state[f.key] === null))
  if (missing.length) {
    notifyError(`Preencha: ${missing.map(f => f.label).join(', ')}`, 'Campos obrigatórios')
    return
  }
  const data: Record<string, any> = {}
  for (const f of visibleFields.value) {
    if (editingId.value && f.readonlyOnEdit) continue
    data[f.key] = f.type === 'money' ? Number(state[f.key] ?? 0).toFixed(2) : state[f.key]
  }
  saving.value = true
  try {
    if (editingId.value) await props.update!(editingId.value, data)
    else await props.create!(data)
    notifySuccess(editingId.value ? `${props.singular} atualizado(a)` : `${props.singular} criado(a)`)
    open.value = false
    await reload()
    emit('changed')
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}

async function destroy() {
  if (!editingId.value || !await confirm({ title: `Excluir ${props.singular.toLowerCase()}?`, description: 'Esta ação não pode ser desfeita.' })) return
  try {
    await props.remove!(editingId.value)
    notifySuccess(`${props.singular} excluído(a)`)
    open.value = false
    await reload()
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <AppPage :title="title" :tabs="tabs">
    <template #actions>
      <slot name="actions" />
      <UButton v-if="create && can('create')" :label="`Novo(a) ${singular.toLowerCase()}`" icon="i-lucide-plus"
               class="rounded-full" @click="openCreate" />
    </template>
    <template v-if="searchKeys || $slots.toolbar" #toolbar>
      <UInput v-if="searchKeys" v-model="search" icon="i-lucide-search" placeholder="Buscar…" class="w-72" />
      <slot name="toolbar" />
    </template>

    <slot name="summary" :rows="filtered" />
    <div class="s-panel overflow-hidden">
      <UTable :data="pageRows" :columns="tableColumns" :loading="loading" sticky :empty="`Nenhum registro`"
              class="max-h-[calc(100dvh-14rem)]" @select="(_: Event, row: any) => rowTo ? navigateTo(rowTo(row.original)) : openEdit(row.original)" />
    </div>
    <div class="flex items-center justify-between text-sm text-muted">
      <span>{{ filtered.length.toLocaleString('pt-BR') }} registro(s)</span>
      <UPagination v-if="filtered.length > PAGE_SIZE" v-model:page="page" :total="filtered.length" :items-per-page="PAGE_SIZE" />
    </div>

    <AppBulkBar v-if="selectable" :count="selection.ids.value.length" @clear="selection.clear">
      <slot name="bulk" :rows="selection.rows.value" :clear="selection.clear" :reload="reload" />
    </AppBulkBar>

    <UModal v-model:open="open" :title="editingId ? `Editar ${singular.toLowerCase()}` : `Novo(a) ${singular.toLowerCase()}`"
            :ui="{ content: 'max-w-xl' }">
      <template #body>
        <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="save">
          <UFormField v-for="f in visibleFields" :key="f.key" :label="f.label" :required="isRequired(f)" :hint="f.hint"
                      :class="f.span === 2 || f.type === 'textarea' || f.type === 'tags' ? 'sm:col-span-2' : ''">
            <USelect v-if="f.type === 'select'" v-model="state[f.key]" :items="(f.options as any)" :placeholder="f.placeholder"
                     :disabled="!!editingId && f.readonlyOnEdit" class="w-full" />
            <USelectMenu v-else-if="f.type === 'multiselect'" v-model="state[f.key]" :items="(f.options as any)" value-key="value"
                         multiple :placeholder="f.placeholder" class="w-full" />
            <USwitch v-else-if="f.type === 'switch'" v-model="state[f.key]" />
            <UInputTags v-else-if="f.type === 'tags'" v-model="state[f.key]" :placeholder="f.placeholder" class="w-full" />
            <UTextarea v-else-if="f.type === 'textarea'" v-model="state[f.key]" :rows="3" class="w-full" />
            <UInputNumber v-else-if="f.type === 'money'" v-model="state[f.key]" :step="0.01" :increment="false" :decrement="false"
                          :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
            <UInputNumber v-else-if="f.type === 'number'" v-model="state[f.key]" :step="f.step" class="w-full" />
            <UInput v-else v-model="state[f.key]" :type="f.type ?? 'text'" :placeholder="f.placeholder"
                    :disabled="!!editingId && f.readonlyOnEdit" class="w-full" />
          </UFormField>

          <div class="flex items-center gap-2 sm:col-span-2 pt-2">
            <UButton v-if="editingId && remove && can('delete')" label="Excluir" icon="i-lucide-trash-2" color="error"
                     variant="ghost" @click="destroy" />
            <slot name="form-actions" :id="editingId" :close="() => (open = false)" :reload="reload" />
            <UButton label="Cancelar" color="neutral" variant="ghost" class="ms-auto" @click="open = false" />
            <UButton type="submit" :label="editingId ? 'Salvar' : 'Criar'" :loading="saving" />
          </div>
        </form>
      </template>
    </UModal>
  </AppPage>
</template>
