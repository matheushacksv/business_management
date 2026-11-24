// Filters live in the URL: they survive going back, reload and can be shared as a link.
// Types come from the defaults; arrays of `*_id` are numbers. Other query keys (e.g. ?sale=) are kept.
export function useQueryFilters<T extends Record<string, unknown>>(filters: T) {
  const route = useRoute()
  const router = useRouter()
  const defaults = JSON.parse(JSON.stringify(filters)) as Record<string, unknown>
  const target = filters as Record<string, unknown>

  for (const [key, initial] of Object.entries(defaults)) {
    const raw = route.query[key]
    if (raw == null) continue
    const list = (Array.isArray(raw) ? raw : [raw]).map(String)
    if (Array.isArray(initial)) target[key] = key.endsWith('_id') ? list.map(Number) : list
    else target[key] = typeof initial === 'number' ? Number(list[0]) : list[0]
  }

  watch(filters, () => {
    const query = { ...route.query }
    for (const [key, initial] of Object.entries(defaults)) {
      const value = target[key]
      const empty = value == null || value === '' || (Array.isArray(value) && !value.length)
      // a cleared non-empty default (e.g. date_to = today) stays in the URL as '' so reload keeps it cleared
      if (JSON.stringify(value) === JSON.stringify(initial) || (empty && !initial)) delete query[key]
      else query[key] = Array.isArray(value) ? value.map(String) : String(value ?? '')
    }
    router.replace({ query })
  }, { deep: true })
}

// /page?<key>=<id> opens that record (global search, links from other screens); closing the drawer clears it
export function useQueryOpen(key: string, open: (id: number) => void, isOpen: Ref<boolean>) {
  const route = useRoute()
  const router = useRouter()
  watch(() => route.query[key], id => { if (id) open(Number(id)) }, { immediate: true })
  watch(isOpen, (value) => {
    if (!value && route.query[key]) router.replace({ query: { ...route.query, [key]: undefined } })
  })
}
