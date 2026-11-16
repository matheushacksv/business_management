<script setup lang="ts">
import type { components } from '~/types/api'

// Contact picker with server-side search (there are hundreds of contacts).
// "Create" opens the full registration modal; the new contact comes back selected.
const model = defineModel<number | null | undefined>()
const props = defineProps<{ initialLabel?: string | null; placeholder?: string }>()

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const search = ref('')
const items = ref<{ label: string; value: number; description?: string }[]>([])
const loading = ref(false)

// Keep the current value visible before any search
watchEffect(() => {
  if (model.value && props.initialLabel && !items.value.some(i => i.value === model.value)) {
    items.value = [{ label: props.initialLabel, value: model.value }, ...items.value]
  }
})

let timer: ReturnType<typeof setTimeout> | undefined
watch(search, (term) => {
  clearTimeout(timer)
  timer = setTimeout(() => load(term), 250)
})

async function load(term: string) {
  loading.value = true
  try {
    const contacts = await unwrap(api.GET('/api/contact', { params: { query: { search: term || undefined } } }))
    const selected = items.value.find(i => i.value === model.value)
    items.value = contacts.slice(0, 50).map(c => ({
      label: c.name, value: c.id!, description: c.company_name || c.document || undefined,
    }))
    if (selected && !items.value.some(i => i.value === selected.value)) items.value.unshift(selected)
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}

const canCreate = computed(() => auth.can('contacts', 'create'))
const creating = ref(false)
const newName = ref('')

function openCreate(name = '') {
  newName.value = name
  creating.value = true
}

function onCreated(contact: components['schemas']['ContactOut']) {
  items.value.unshift({
    label: contact.name, value: contact.id!, description: contact.company_name || contact.document || undefined,
  })
  model.value = contact.id!
}

onMounted(() => load(''))
</script>

<template>
  <div class="flex w-full gap-2">
    <USelectMenu
      v-model="model"
      v-model:search-term="search"
      :items="items"
      value-key="value"
      :loading="loading"
      ignore-filter
      :create-item="canCreate ? 'always' : false"
      :placeholder="placeholder ?? 'Buscar cliente/fornecedor'"
      :search-input="{ placeholder: 'Nome, razão social ou documento', icon: 'i-lucide-search' }"
      clear
      class="flex-1 min-w-0"
      @create="openCreate"
    />
    <UTooltip v-if="canCreate" text="Cadastrar novo">
      <UButton icon="i-lucide-user-plus" color="neutral" variant="outline" aria-label="Cadastrar cliente/fornecedor"
               @click="openCreate(search)" />
    </UTooltip>

    <AppContactFormModal v-model:open="creating" :initial-name="newName" @created="onCreated" />
  </div>
</template>
