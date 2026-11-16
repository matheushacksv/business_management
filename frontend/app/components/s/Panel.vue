<script setup lang="ts">
// SORA glass panel (no backdrop-filter; see main.css)
// padded defaults to TRUE: a missing boolean prop is `false` in Vue, so it needs an explicit default
withDefaults(defineProps<{ title?: string; description?: string; padded?: boolean }>(), { padded: true })
</script>

<template>
  <section class="s-panel" :class="padded ? 'p-5' : ''">
    <header v-if="title || $slots.actions" class="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 v-if="title" class="font-display text-base font-semibold tracking-tight text-highlighted">{{ title }}</h2>
        <p v-if="description" class="mt-0.5 text-xs text-muted">{{ description }}</p>
      </div>
      <slot name="actions" />
    </header>
    <slot />
  </section>
</template>
