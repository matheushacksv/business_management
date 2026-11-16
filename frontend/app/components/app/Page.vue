<script setup lang="ts">
// Page frame: dashboard panel + navbar (title, actions) + optional toolbar (filters)
defineProps<{ title: string; id?: string }>()
</script>

<template>
  <UDashboardPanel :id="id ?? title" :ui="{ body: 'gap-4 sm:gap-6' }">
    <template #header>
      <UDashboardNavbar :title="title" :ui="{ root: 'border-default', title: 'font-display tracking-tight' }">
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <slot name="actions" />
          <UColorModeButton color="neutral" variant="ghost" />
        </template>
      </UDashboardNavbar>
      <UDashboardToolbar v-if="$slots.toolbar" :ui="{ root: 'border-default py-2 h-auto' }">
        <div class="flex flex-wrap items-center gap-2 py-0.5">
          <slot name="toolbar" />
        </div>
      </UDashboardToolbar>
    </template>

    <template #body>
      <div class="s-enter flex flex-col gap-4 sm:gap-6">
        <slot />
      </div>
    </template>
  </UDashboardPanel>
</template>
