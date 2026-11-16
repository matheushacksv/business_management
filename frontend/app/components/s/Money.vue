<script setup lang="ts">
// Amount in BRL. `type` colors it like the spreadsheet: inflow green, outflow red.
const props = defineProps<{ value: string | number | null | undefined; type?: string | null; signed?: boolean }>()

const tone = computed(() => {
  if (props.type === 'inflow') return 'text-success'
  if (props.type === 'outflow') return 'text-error'
  if (props.signed && Number(props.value) < 0) return 'text-error'
  return ''
})
</script>

<template>
  <span class="tabular whitespace-nowrap" :class="tone">
    {{ type === 'outflow' ? '−' : '' }}{{ formatMoney(value) }}
  </span>
</template>
