<script setup lang="ts">
import type { components } from '~/types/api'

type Contact = components['schemas']['ContactOut']

// Contact registration in a modal (opens on top of other modals, e.g. the transaction form).
// With `contact` it edits that contact instead of creating one.
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ initialName?: string; contact?: Contact | null }>()
const emit = defineEmits<{ created: [contact: Contact]; saved: [contact: Contact] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const blank = () => ({ name: '', kind: 'supplier' as 'customer' | 'supplier', company_name: '', document: '', email: '', phone: '', postal_code: '', address_number: '', address_complement: '', address_district: '' })
const state = reactive(blank())
const saving = ref(false)
const customer = computed(() => state.kind === 'customer')

// Every opening starts clean, with the name typed in the search
watch(open, (isOpen) => {
  if (!isOpen) return
  const c = props.contact
  Object.assign(state, blank(), c
    ? { name: c.name, kind: c.kind, company_name: c.company_name, document: c.document, email: c.email, phone: c.phone,
        postal_code: c.postal_code, address_number: c.address_number, address_complement: c.address_complement, address_district: c.address_district }
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
        <UFormField label="Nome" required>
          <UInput v-model="state.name" autofocus class="w-full" />
        </UFormField>
        <UFormField label="Tipo" required>
          <USelect v-model="state.kind" :items="[{ label: 'Cliente', value: 'customer' }, { label: 'Fornecedor', value: 'supplier' }]" class="w-full" />
        </UFormField>
        <UFormField label="Razão social">
          <UInput v-model="state.company_name" class="w-full" />
        </UFormField>
        <UFormField label="CPF/CNPJ" :required="customer">
          <UInput v-model="state.document" placeholder="Com ou sem pontuação" class="w-full" />
        </UFormField>
        <UFormField label="E-mail" :required="customer">
          <UInput v-model="state.email" type="email" class="w-full" />
        </UFormField>
        <UFormField label="Telefone">
          <UInput v-model="state.phone" type="tel" class="w-full" />
        </UFormField>
        <UFormField label="CEP" :required="customer">
          <UInput v-model="state.postal_code" inputmode="numeric" maxlength="9" class="w-full"
                  @update:model-value="(v: any) => (state.postal_code = String(v).replace(/\D/g, '').slice(0, 8))" />
        </UFormField>
        <UFormField label="Número" :required="customer">
          <UInput v-model="state.address_number" class="w-full" />
        </UFormField>
        <UFormField label="Complemento">
          <UInput v-model="state.address_complement" class="w-full" />
        </UFormField>
        <UFormField label="Bairro" :required="customer">
          <UInput v-model="state.address_district" class="w-full" />
        </UFormField>
        <div class="flex justify-end gap-2 sm:col-span-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="open = false" />
          <UButton type="submit" :label="contact ? 'Salvar' : 'Cadastrar'" :loading="saving" />
        </div>
      </form>
    </template>
  </UModal>
</template>
