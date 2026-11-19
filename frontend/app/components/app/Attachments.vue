<script setup lang="ts">
import type { components } from '~/types/api'

type Attachment = components['schemas']['AttachmentOut']
const props = defineProps<{ target: 'transaction' | 'contact' | 'invoice' | 'sale' | 'collection_case'; targetId: number; editable?: boolean }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, raw, download, notifyError, notifySuccess } = useApi()
const confirm = useConfirm()
const items = ref<Attachment[]>([])
const loading = ref(false)
const uploading = ref(false)
const file = ref<File | null>(null)

async function load() {
  loading.value = true
  try {
    items.value = await unwrap(api.GET('/api/attachment', { params: { query: { target: props.target, target_id: props.targetId } } }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}

watch(file, async (value) => {
  if (!value) return
  uploading.value = true
  try {
    const form = new FormData()
    form.append('target', props.target)
    form.append('target_id', String(props.targetId))
    form.append('file', value)
    await raw('/api/attachment', { method: 'POST', body: form })
    notifySuccess('Arquivo anexado')
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e, 'Falha no envio')
  } finally {
    uploading.value = false
    file.value = null
  }
})

async function remove(item: Attachment) {
  if (!await confirm({ title: 'Excluir anexo?', description: `O arquivo "${item.name}" será apagado.` })) return
  try {
    await unwrap(api.DELETE('/api/attachment/{attachment_id}', { params: { path: { attachment_id: item.id! } } }))
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

function size(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

watch(() => props.targetId, load, { immediate: true })
</script>

<template>
  <div class="space-y-3">
    <UFileUpload
      v-if="editable"
      v-model="file"
      :disabled="uploading"
      accept=".pdf,.png,.jpg,.jpeg,.webp,.heic,.xml,.xlsx,.xls,.csv,.doc,.docx,.txt"
      label="Solte o arquivo ou clique para enviar"
      icon="i-lucide-upload"
      class="w-full min-h-28"
    />

    <div v-if="loading" class="space-y-2">
      <USkeleton class="h-10 w-full" />
    </div>
    <p v-else-if="!items.length" class="text-sm text-dimmed">Nenhum arquivo anexado.</p>
    <ul v-else class="divide-y divide-muted rounded-xl ring ring-default">
      <li v-for="item in items" :key="item.id!" class="flex items-center gap-3 px-3 py-2">
        <UIcon name="i-lucide-file-text" class="size-4 text-primary shrink-0" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm text-highlighted">{{ item.name }}</p>
          <p class="text-xs text-dimmed">{{ size(item.size) }} · {{ formatDateTime(item.created_at) }}</p>
        </div>
        <UButton icon="i-lucide-download" color="neutral" variant="ghost" size="sm" aria-label="Baixar"
                 @click="download(`/api/attachment/${item.id}/download`, item.name).catch(notifyError)" />
        <UButton v-if="editable" icon="i-lucide-trash-2" color="error" variant="ghost" size="sm" aria-label="Excluir"
                 @click="remove(item)" />
      </li>
    </ul>
  </div>
</template>
