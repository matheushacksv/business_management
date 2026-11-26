<script setup lang="ts">
import type { TabGroup } from '~/composables/usePageTabs'
// Page frame: dashboard panel + navbar (title, actions) + optional tabs (sibling routes) + optional toolbar (filters)
const props = defineProps<{ title: string; id?: string; tabs?: TabGroup }>()

const groups = usePageTabs()
const tabItems = computed(() => props.tabs ? groups.value[props.tabs].items : [])
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
      <UDashboardToolbar v-if="tabItems.length > 1" :ui="{ root: 'border-default' }">
        <UNavigationMenu :items="tabItems" highlight class="-mx-1 flex-1" />
      </UDashboardToolbar>
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
