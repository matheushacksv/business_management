// Shared report filters (company / status), serialized the way the API expects.
export function useReportFilters() {
  const company_id = ref<number[]>([])
  const status = ref<'all' | 'realized' | 'planned'>('all')

  const query = computed(() => ({
    ...(company_id.value.length ? { company_id: company_id.value } : {}),
    ...(status.value !== 'all' ? { status: [status.value] } : {}),
  }))

  const statusOptions = [
    { label: 'Previsto + realizado', value: 'all' },
    { label: 'Somente realizado', value: 'realized' },
    { label: 'Somente previsto', value: 'planned' },
  ]
  return { company_id, status, query, statusOptions }
}
