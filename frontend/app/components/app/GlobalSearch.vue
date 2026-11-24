<script setup lang="ts">
import type { CommandPaletteGroup, CommandPaletteItem, NavigationMenuItem } from '@nuxt/ui'

// Ctrl+K: menu pages (filtered here) + records (filtered by the API, only the modules the role can see)
const props = defineProps<{ menu: NavigationMenuItem[][] }>()
const { api, unwrap } = useApi()
const auth = useAuth()

const term = ref('')
const loading = ref(false)
const found = ref<CommandPaletteGroup<CommandPaletteItem>[]>([])
const LIMIT = 5

const pages = computed(() => props.menu.flat().flatMap(i => i.children?.length ? i.children.map(c => ({ ...c, label: `${i.label} · ${c.label}` })) : [i])
  .filter(i => i.to && i.type !== 'label')
  .map(i => ({ label: String(i.label), icon: (i.icon as string) || 'i-lucide-file', to: i.to as string })))

async function lookup(search: string) {
  const query = { search } as any
  const groups = await Promise.all([
    auth.can('contacts') && unwrap(api.GET('/api/contact', { params: { query } })).then(list => ({
      id: 'contacts', label: 'Clientes e fornecedores',
      items: list.slice(0, LIMIT).map(c => ({ label: c.name, suffix: c.document ?? undefined, icon: 'i-lucide-user', to: `/registers/contacts/${c.id}` })),
    })),
    auth.can('sales') && unwrap(api.GET('/api/sale', { params: { query } })).then(r => ({
      id: 'sales', label: 'Vendas',
      items: r.items.slice(0, LIMIT).map(s => ({ label: s.contact_name ?? `Venda #${s.id}`, suffix: `${formatDate(s.date)} · ${formatMoney(s.amount)}`,
        icon: 'i-lucide-handshake', to: `/sales?sale=${s.id}` })),
    })),
    auth.can('transactions') && unwrap(api.GET('/api/transaction', { params: { query } })).then(r => ({
      id: 'transactions', label: 'Lançamentos',
      items: r.items.slice(0, LIMIT).map(t => ({ label: t.contact_name ?? t.reference ?? t.subgroup_name, suffix: `${formatDate(t.date)} · ${formatMoney(t.amount)}`,
        icon: t.type === 'inflow' ? 'i-lucide-arrow-down-left' : 'i-lucide-arrow-up-right', to: `/transactions?transaction=${t.id}` })),
    })),
    auth.can('legal') && unwrap(api.GET('/api/collection-case', { params: { query } })).then(list => ({
      id: 'legal', label: 'Jurídico',
      items: list.slice(0, LIMIT).map(c => ({ label: c.contact_name, suffix: c.company_name, icon: 'i-lucide-scale', to: `/legal?case=${c.id}` })),
    })),
  ].map(p => p ? p.catch(() => null) : null))
  return groups.filter(g => g?.items.length).map(g => ({ ...g!, ignoreFilter: true }))
}

let timer: ReturnType<typeof setTimeout> | undefined
watch(term, (value) => {
  clearTimeout(timer)
  const search = value.trim()
  if (search.length < 2) {
    found.value = []
    return
  }
  timer = setTimeout(async () => {
    loading.value = true
    const groups = await lookup(search)
    if (term.value.trim() === search) found.value = groups  // drop answers to an older term
    loading.value = false
  }, 300)
})

const groups = computed(() => [{ id: 'pages', label: 'Páginas', items: pages.value }, ...found.value])
</script>

<template>
  <UDashboardSearch v-model:search-term="term" :groups="groups" :loading="loading" :color-mode="false"
                    placeholder="Buscar páginas, clientes, vendas, lançamentos…" />
</template>
