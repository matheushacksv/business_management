import type { NavigationMenuItem } from '@nuxt/ui'

export type TabGroup = 'dunning' | 'legal' | 'catalog' | 'team'

// Sibling pages shown as tabs under one menu entry (AppPage `tabs`); also listed in Ctrl+K
export function usePageTabs() {
  const auth = useAuth()
  return computed<Record<TabGroup, { label: string; items: NavigationMenuItem[] }>>(() => {
    const keep = (list: (NavigationMenuItem | false)[]) => list.filter(Boolean) as NavigationMenuItem[]
    return {
      dunning: { label: 'Configurar cobrança', items: keep([
        auth.can('dunning') && { label: 'Etapas', to: '/dunning/stages' },
        auth.can('dunning') && { label: 'Cadência', to: '/dunning/cadence' },
      ]) },
      legal: { label: 'Configurar jurídico', items: keep([
        auth.can('legal') && { label: 'Etapas', to: '/legal/stages' },
        !!auth.me.value?.is_admin && { label: 'Checklist', to: '/legal/checklist' },
      ]) },
      catalog: { label: 'Catálogo', items: keep([
        auth.can('sales') && { label: 'Produtos', to: '/sales/products' },
        auth.can('sales') && { label: 'Planos', to: '/sales/plans' },
      ]) },
      team: { label: 'Equipe', items: keep([
        auth.can('sales') && { label: 'Vendedores', to: '/sales/salespeople' },
        auth.can('sales') && { label: 'Comissões', to: '/sales/commissions' },
      ]) },
    }
  })
}
