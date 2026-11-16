<script setup lang="ts">
import type { components } from '~/types/api'

type Invoice = components['schemas']['InvoiceOut']
const props = defineProps<{ transactionId: number; editable?: boolean }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const invoices = ref<Invoice[]>([])
const loading = ref(false)
const editing = ref<number | null>(null)
const form = reactive({ done: false, number: '', issue_date: '' as string, notes: '' })

const kinds = [
  { label: 'NF de Serviço', value: 'service' },
  { label: 'NF de Produto', value: 'product' },
]
const missingKinds = computed(() => kinds.filter(k => !invoices.value.some(i => i.kind === k.value)))

async function load() {
  loading.value = true
  try {
    invoices.value = await unwrap(api.GET('/api/invoice', { params: { query: { transaction_id: props.transactionId } } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}

async function requireInvoice(kind: string) {
  try {
    await unwrap(api.POST('/api/invoice', { body: { transaction_id: props.transactionId, kind: kind as 'service' | 'product', done: false, number: '', notes: '' } }))
    await load()
  } catch (e) {
    notifyError(e)
  }
}

function edit(invoice: Invoice) {
  editing.value = invoice.id!
  Object.assign(form, {
    done: invoice.done, number: invoice.number ?? '', issue_date: invoice.issue_date ?? '', notes: invoice.notes ?? '',
  })
}

async function save(invoice: Invoice) {
  try {
    await unwrap(api.PATCH('/api/invoice/{invoice_id}', {
      params: { path: { invoice_id: invoice.id! } },
      body: { done: form.done, number: form.number, issue_date: form.issue_date || null, notes: form.notes },
    }))
    editing.value = null
    notifySuccess('Nota atualizada')
    await load()
  } catch (e) {
    notifyError(e)
  }
}

async function remove(invoice: Invoice) {
  if (!confirm('Remover a exigência desta nota?')) return
  try {
    await unwrap(api.DELETE('/api/invoice/{invoice_id}', { params: { path: { invoice_id: invoice.id! } } }))
    await load()
  } catch (e) {
    notifyError(e)
  }
}

watch(() => props.transactionId, load, { immediate: true })
</script>

<template>
  <div class="space-y-4">
    <USkeleton v-if="loading" class="h-16 w-full" />
    <p v-else-if="!invoices.length" class="text-sm text-dimmed">Este lançamento não exige nota fiscal.</p>

    <div v-for="invoice in invoices" :key="invoice.id!" class="rounded-xl ring ring-default p-4 space-y-3">
      <div class="flex items-center gap-2">
        <UIcon name="i-lucide-receipt-text" class="size-4 text-primary" />
        <p class="font-medium text-highlighted text-sm">{{ LABELS.invoiceKind[invoice.kind] }}</p>
        <UBadge
          :label="invoice.done ? (invoice.direction === 'receive' ? 'Recebida' : 'Emitida') : (invoice.direction === 'receive' ? 'A receber' : 'A emitir')"
          :color="invoice.done ? 'success' : 'warning'" variant="subtle" size="sm" />
        <div class="ms-auto flex gap-1" v-if="editable && editing !== invoice.id">
          <UButton icon="i-lucide-pencil" color="neutral" variant="ghost" size="sm" aria-label="Editar" @click="edit(invoice)" />
          <UButton icon="i-lucide-trash-2" color="error" variant="ghost" size="sm" aria-label="Remover" @click="remove(invoice)" />
        </div>
      </div>

      <div v-if="editing === invoice.id" class="grid gap-3 sm:grid-cols-2">
        <USwitch v-model="form.done" :label="invoice.direction === 'receive' ? 'Nota recebida' : 'Nota emitida'" class="sm:col-span-2" />
        <UFormField label="Número" :required="form.done && invoice.direction === 'issue'">
          <UInput v-model="form.number" class="w-full" />
        </UFormField>
        <UFormField label="Data de emissão" :required="form.done">
          <UInput v-model="form.issue_date" type="date" class="w-full" />
        </UFormField>
        <UFormField label="Observações" class="sm:col-span-2">
          <UTextarea v-model="form.notes" :rows="2" class="w-full" />
        </UFormField>
        <div class="flex justify-end gap-2 sm:col-span-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="editing = null" />
          <UButton label="Salvar" @click="save(invoice)" />
        </div>
      </div>
      <p v-else-if="invoice.number || invoice.issue_date" class="text-xs text-muted">
        Nº {{ invoice.number || '—' }} · {{ formatDate(invoice.issue_date) }}
      </p>

      <AppAttachments target="invoice" :target-id="invoice.id!" :editable="editable" />
    </div>

    <div v-if="editable && missingKinds.length" class="flex flex-wrap gap-2">
      <UButton
        v-for="kind in missingKinds" :key="kind.value"
        :label="`Exigir ${kind.label}`" icon="i-lucide-plus" color="neutral" variant="outline" size="sm"
        @click="requireInvoice(kind.value)"
      />
    </div>
  </div>
</template>
