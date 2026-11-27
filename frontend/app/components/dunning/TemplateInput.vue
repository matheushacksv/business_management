<script setup lang="ts">
// Message of a cadence step: textarea + "Inserir campo" menu that puts {placeholders} where the cursor is
const model = defineModel<string>({ default: '' })
const area = ref<{ textareaRef: HTMLTextAreaElement | null } | null>(null)

function insert(token: string) {
  const el = area.value?.textareaRef
  const at = el ? el.selectionStart : model.value.length
  model.value = model.value.slice(0, at) + token + model.value.slice(el ? el.selectionEnd : at)
  nextTick(() => { el?.focus(); el?.setSelectionRange(at + token.length, at + token.length) })
}
const items = TEMPLATE_VARIABLES.map(v => ({ label: v.label, suffix: v.value, onSelect: () => insert(v.value) }))
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <UDropdownMenu :items="items" :content="{ align: 'start' }">
      <UButton label="Inserir campo" icon="i-lucide-braces" trailing-icon="i-lucide-chevron-down" size="xs" color="neutral"
               variant="outline" class="self-start" />
    </UDropdownMenu>
    <UTextarea ref="area" v-model="model" :rows="4" autoresize class="w-full" />
  </div>
</template>
