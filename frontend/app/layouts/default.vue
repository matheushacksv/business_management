<script setup lang="ts">
import type { NavigationMenuItem, DropdownMenuItem } from '@nuxt/ui'

const auth = useAuth()

// Menu = only what the role can see (mirrors /api/me permissions)
const route = useRoute()
const keep = <T,>(list: (T | false | undefined)[]) => list.filter(Boolean) as T[]
const section = (label: string, list: (NavigationMenuItem | false)[]) => {
  const visible = keep(list)
  return visible.length ? [{ label, type: 'label' } as NavigationMenuItem, ...visible] : []
}
// Collapsible parent: closed by default, opens when the current route is inside it
const parent = (item: NavigationMenuItem, prefixes: string[], children: (NavigationMenuItem | false)[]) => {
  const visible = keep(children)
  return visible.length > 0 && { ...item, children: visible, defaultOpen: prefixes.some(p => route.path.startsWith(p)) }
}

const items = computed<NavigationMenuItem[][]>(() => {
  const can = auth.can
  const finance = [
    { label: 'Início', icon: 'i-lucide-layout-dashboard', to: '/' },
    ...section('Financeiro', [
      can('transactions') && { label: 'Lançamentos', icon: 'i-lucide-arrow-left-right', to: '/transactions' },
      can('transactions') && { label: 'Notas pendentes', icon: 'i-lucide-receipt-text', to: '/invoices' },
      parent({ label: 'Relatórios', icon: 'i-lucide-chart-column' }, ['/reports', '/sales/report'], [
        can('reports') && { label: 'DRE', to: '/reports/dre' },
        can('reports') && { label: 'Fluxo de caixa', to: '/reports/cash-flow' },
        can('reports') && can('sales') && { label: 'Vendido × recebido', to: '/sales/report' },
      ]),
    ]),
  ]

  const sales = section('Comercial', [
    can('sales') && { label: 'Vendas e contratos', icon: 'i-lucide-handshake', to: '/sales', exact: true },
    can('sales') && { label: 'Produtos', icon: 'i-lucide-package', to: '/sales/products' },
    can('sales') && { label: 'Vendedores', icon: 'i-lucide-user-round', to: '/sales/salespeople' },
  ])

  const legal = section('Jurídico', [
    can('legal') && { label: 'Cobranças', icon: 'i-lucide-scale', to: '/legal' },
  ])

  const settings = keep<NavigationMenuItem>([
    parent({ label: 'Cadastros', icon: 'i-lucide-folder-tree' }, ['/registers'], [
      can('contacts') && { label: 'Clientes e fornecedores', to: '/registers/contacts' },
      can('subgroups') && { label: 'Plano de contas', to: '/registers/subgroups' },
      can('accounts') && { label: 'Contas', to: '/registers/accounts' },
      can('companies') && { label: 'Empresas', to: '/registers/companies' },
    ]),
    !!auth.me.value?.is_admin && parent({ label: 'Administração', icon: 'i-lucide-settings' }, ['/admin'], [
      { label: 'Usuários', to: '/admin/users' },
      { label: 'Importar planilha', to: '/admin/import' },
      { label: 'Auditoria', to: '/admin/audit' },
    ]),
  ])

  return [finance, sales, legal, settings].filter(group => group.length)
})

const colorMode = useColorMode()
const setTheme = (value: 'dark' | 'light') => (e: Event) => {
  e.preventDefault()  // keep the menu open to see the change
  colorMode.preference = value
}

const userMenu = computed<DropdownMenuItem[][]>(() => [
  [{ label: auth.me.value?.email ?? '', type: 'label' }],
  [
    { label: 'Tema escuro', icon: 'i-lucide-moon', type: 'checkbox', checked: colorMode.value === 'dark', onSelect: setTheme('dark') },
    { label: 'Tema claro', icon: 'i-lucide-sun', type: 'checkbox', checked: colorMode.value === 'light', onSelect: setTheme('light') },
  ],
  [{ label: 'Sair', icon: 'i-lucide-log-out', onSelect: () => auth.logout() }],
])
</script>

<template>
  <UDashboardGroup unit="rem" storage="local">
    <UDashboardSidebar
      collapsible
      resizable
      :default-size="16"
      :min-size="13"
      :max-size="22"
      :ui="{ root: 'bg-(--s-sidebar) border-default', footer: 'border-t border-default' }"
    >
      <template #header="{ collapsed }">
        <NuxtLink to="/" class="flex w-full min-w-0 items-center gap-2 px-1 py-1">
          <SLogo class="shrink-0" :class="collapsed ? 'w-full h-auto' : 'h-6 w-auto'" />
          <span v-if="!collapsed" class="min-w-0 font-display leading-tight tracking-tight">
            <span class="block text-xs text-muted">Grupo</span>
            <span class="block truncate font-semibold text-highlighted">Enriquecedor</span>
          </span>
        </NuxtLink>
      </template>

      <template #default="{ collapsed }">
        <UNavigationMenu
          v-for="(group, i) in items"
          :key="i"
          :items="collapsed ? group.filter(item => item.type !== 'label') : group"
          :collapsed="collapsed"
          orientation="vertical"
          tooltip
          popover
          :class="i > 0 ? 'mt-2 pt-2 border-t border-default' : ''"
        />
      </template>

      <template #footer="{ collapsed }">
        <UDropdownMenu :items="userMenu" :content="{ align: 'start' }" class="w-full">
          <UButton
            color="neutral"
            variant="ghost"
            block
            :square="collapsed"
            icon="i-lucide-circle-user-round"
            :label="collapsed ? undefined : (auth.me.value?.name || auth.me.value?.email)"
            :class="collapsed ? '' : 'justify-start'"
          >
            <template v-if="!collapsed" #trailing>
              <UBadge :label="auth.me.value?.is_superuser ? 'Superusuário' : (LABELS.role[auth.me.value?.role ?? ''] ?? '')"
                      variant="subtle" size="sm" class="ms-auto" />
            </template>
          </UButton>
        </UDropdownMenu>
      </template>
    </UDashboardSidebar>

    <slot />
  </UDashboardGroup>
</template>
