<script setup lang="ts">
// Confirmation dialog opened through useConfirm(); emits close(true|false)
withDefaults(defineProps<{
  title: string
  description?: string
  confirmLabel?: string
  color?: 'error' | 'warning' | 'primary'
  icon?: string
}>(), { confirmLabel: 'Excluir', color: 'error', icon: 'i-lucide-trash-2' })
const emit = defineEmits<{ close: [confirmed: boolean] }>()
</script>

<template>
  <UModal :title="title" :description="description" :ui="{ content: 'max-w-md', footer: 'justify-end' }"
          @update:open="(open: boolean) => !open && emit('close', false)">
    <template #footer>
      <UButton label="Cancelar" color="neutral" variant="ghost" @click="emit('close', false)" />
      <UButton :label="confirmLabel" :color="color" :icon="icon" autofocus @click="emit('close', true)" />
    </template>
  </UModal>
</template>
