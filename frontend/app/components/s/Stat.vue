<script setup lang="ts">
// SORA "Statistic": big number + caption
defineProps<{
  label: string
  value: string
  hint?: string
  icon?: string
  tone?: 'default' | 'success' | 'error' | 'primary'
  loading?: boolean
}>()

const tones = {
  default: 'text-highlighted',
  success: 'text-success',
  error: 'text-error',
  primary: 'text-primary',
}
</script>

<template>
  <div class="s-panel p-5">
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted">{{ label }}</p>
      <span v-if="icon" class="size-8 rounded-lg bg-sky-500/10 ring ring-sky-500/20 grid place-items-center">
        <UIcon :name="icon" class="size-4 text-primary" />
      </span>
    </div>
    <USkeleton v-if="loading" class="mt-3 h-9 w-40" />
    <p v-else class="mt-2 font-display text-3xl font-semibold tracking-tight tabular" :class="tones[tone ?? 'default']">
      {{ value }}
    </p>
    <p v-if="hint" class="mt-1 text-xs text-dimmed">{{ hint }}</p>
  </div>
</template>
