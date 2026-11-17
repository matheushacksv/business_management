<script setup lang="ts">
import type { components } from '~/types/api'

type Contact = components['schemas']['ContactOut']

// Contact registration in a modal (opens on top of other modals, e.g. the transaction form).
// With `contact` it edits that contact instead of creating one.
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ initialName?: string; contact?: Contact | null }>()
const emit = defineEmits<{ created: [contact: Contact]; saved: [contact: Contact] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const blank = () => ({ name: '', company_name: '', document: '', email: '', phone: '' })
const state = reactive(blank())
const saving = ref(false)

// Every opening starts clean, with the name typed in the search
watch(open, (isOpen) => {
  if (!isOpen) return
  const c = props.contact
  Object.assign(state, blank(), c
    ? { name: c.name, company_name: c.company_name, document: c.document, email: c.email, phone: c.phone }
    : { name: props.initialName?.trim() ?? '' })
})

async function save() {
  if (!state.name.trim()) {
    notifyError('Informe o nome.', 'Campo obrigatório')
    return
  }
  saving.value = true
  try {
    if (props.contact) {
      const contact = await unwrap(api.PATCH('/api/contact/{contact_id}', {
        params: { path: { contact_id: props.contact.id! } }, body: { ...state },
      }))
      notifySuccess('Contato atualizado')
      emit('saved', contact)
    } else {
      const contact = await unwrap(api.POST('/api/contact', { body: { ...state, notes: '' } }))
      notifySuccess('Contato cadastrado')
      emit('created', contact)
    }
    open.value = false
  } catch (e) {
    notifyError(e)  // e.g. CPF/CNPJ already registered, invalid e-mail
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UModal v-model:open="open" :title="contact ? 'Editar cliente/fornecedor' : 'Novo cliente/fornecedor'" :ui="{ content: 'max-w-lg' }">
    <template #body>
      <form class="grid gap-4 sm:grid-cols-2" @submit.prevent.stop="save">
        <UFormField label="Nome" required class="sm:col-span-2">
          <UInput v-model="state.name" autofocus class="w-full" />
        </UFormField>
        <UFormField label="Razão social">
          <UInput v-model="state.company_name" class="w-full" />
        </UFormField>
        <UFormField label="CPF/CNPJ">
          <UInput v-model="state.document" placeholder="Com ou sem pontuação" class="w-full" />
        </UFormField>
        <UFormField label="E-mail">
          <UInput v-model="state.email" type="email" class="w-full" />
        </UFormField>
        <UFormField label="Telefone">
          <UInput v-model="state.phone" type="tel" class="w-full" />
        </UFormField>
        <div class="flex justify-end gap-2 sm:col-span-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="open = false" />
          <UButton type="submit" :label="contact ? 'Salvar' : 'Cadastrar'" :loading="saving" />
        </div>
      </form>
    </template>
  </UModal>
</template>
