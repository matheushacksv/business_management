<script setup lang="ts">
// SORA badges: semantic tint (10-20% fill) + colored text
const props = defineProps<{ kind: 'type' | 'status' | 'sale' | 'invoice' | 'situation'; value?: string | null }>()

const map: Record<string, Record<string, { label: string; color: 'success' | 'error' | 'primary' | 'neutral' | 'warning' }>> = {
  type: {
    inflow: { label: 'Entrada', color: 'success' },
    outflow: { label: 'Saída', color: 'error' },
  },
  status: {
    planned: { label: 'Previsto', color: 'primary' },
    realized: { label: 'Realizado', color: 'success' },
  },
  sale: {
    active: { label: 'Ativa', color: 'primary' },
    completed: { label: 'Concluída', color: 'success' },
    canceled: { label: 'Cancelada', color: 'neutral' },
  },
  // Customer traffic light (PDF 15)
  situation: {
    ok: { label: 'Regularizado', color: 'success' },
    attention: { label: 'Atenção', color: 'warning' },
    critical: { label: 'Crítico', color: 'error' },
  },
  invoice: {
    missing_invoice: { label: 'Sem nota', color: 'warning' },
    missing_attachment: { label: 'Sem arquivo', color: 'primary' },
    done: { label: 'Completa', color: 'success' },
  },
}

const item = computed(() => map[props.kind]?.[props.value ?? ''] ?? { label: props.value ?? '—', color: 'neutral' as const })
</script>

<template>
  <UBadge :label="item.label" :color="item.color" variant="subtle" size="sm" />
</template>
