<script setup lang="ts">
defineProps<{ count: number }>()
defineEmits<{ clear: [] }>()
</script>

<template>
  <div v-if="count"
       class="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-full bg-(--s-solid) py-1.5 ps-4 pe-1.5 shadow-lg ring ring-default">
    <span class="text-sm whitespace-nowrap text-highlighted tabular">{{ count.toLocaleString('pt-BR') }} selecionado(s)</span>
    <slot />
    <UButton icon="i-lucide-x" color="neutral" variant="ghost" size="sm" aria-label="Limpar seleção" @click="$emit('clear')" />
  </div>
</template>
