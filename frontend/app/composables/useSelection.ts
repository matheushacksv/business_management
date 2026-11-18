import { h, resolveComponent } from 'vue'
import type { TableColumn } from '@nuxt/ui'

/** Checkbox column for UTable; picks are kept by id, so they survive paging and filters. */
export function useSelection<T extends { id?: number | null }>(pageRows: () => T[]) {
  const UCheckbox = resolveComponent('UCheckbox')
  const picked = ref(new Map<number, T>()) as Ref<Map<number, T>>

  function set(rows: T[], on: boolean) {
    const next = new Map(picked.value)
    for (const r of rows) on ? next.set(r.id!, r) : next.delete(r.id!)
    picked.value = next
  }

  const column: TableColumn<T> = {
    id: 'pick',
    header: () => {
      const rows = pageRows()
      const n = rows.filter(r => picked.value.has(r.id!)).length
      return h(UCheckbox, {
        modelValue: n && n === rows.length ? true : n ? 'indeterminate' : false,
        'onUpdate:modelValue': (v: unknown) => set(rows, v === true),
        'aria-label': 'Selecionar página',
      })
    },
    // stopPropagation: ticking the box must not open the row
    cell: ({ row }) => h('div', { onClick: (e: Event) => e.stopPropagation() }, h(UCheckbox, {
      modelValue: picked.value.has(row.original.id!),
      'onUpdate:modelValue': (v: unknown) => set([row.original], v === true),
      'aria-label': 'Selecionar',
    })),
    meta: { class: { th: 'w-8', td: 'w-8' } },
  }

  const rows = computed(() => [...picked.value.values()])
  const ids = computed(() => [...picked.value.keys()])
  const clear = () => { picked.value = new Map() }
  return { picked, rows, ids, column, clear }
}
