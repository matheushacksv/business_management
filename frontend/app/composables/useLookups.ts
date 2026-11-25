import type { components } from '~/types/api'

type S = components['schemas']
export interface Option { label: string; value: number | string; description?: string; group?: string }

interface Lookups {
  companies?: S['CompanyOut'][]
  subgroups?: S['SubgroupOut'][]
  groups?: { value: string; label: string }[]
  accounts?: S['AccountOut'][]
  products?: S['ProductOut'][]
  plans?: S['PlanOut'][]
  salespeople?: S['SalespersonOut'][]
  users?: S['UserOut'][]
}

/**
 * Small reference lists (companies, subgroups...) fetched once and cached for the session.
 * Contacts are NOT here: there are hundreds, the selects search them on the server.
 */
export function useLookups() {
  const { api, unwrap } = useApi()
  const cache = useState<Lookups>('lookups', () => ({}))
  const pending: Partial<Record<keyof Lookups, Promise<unknown>>> = {}

  const loaders: { [K in keyof Lookups]-?: () => Promise<NonNullable<Lookups[K]>> } = {
    companies: () => unwrap(api.GET('/api/company')),
    subgroups: () => unwrap(api.GET('/api/subgroup', { params: { query: {} } })),
    groups: () => unwrap(api.GET('/api/groups')) as Promise<{ value: string; label: string }[]>,
    accounts: () => unwrap(api.GET('/api/account', { params: { query: {} } })),
    products: () => unwrap(api.GET('/api/product', { params: { query: {} } })),
    plans: () => unwrap(api.GET('/api/plan', { params: { query: {} } })),
    salespeople: () => unwrap(api.GET('/api/salesperson', { params: { query: {} } })),
    users: () => unwrap(api.GET('/api/user')),
  }

  async function ensure<K extends keyof Lookups>(...keys: K[]) {
    await Promise.all(keys.map(async (key) => {
      if (cache.value[key]) return
      pending[key] ??= loaders[key]().then((data) => { cache.value = { ...cache.value, [key]: data } })
      try { await pending[key] } finally { delete pending[key] }
    }))
  }

  /** Call after creating/editing an item of that list. */
  async function refresh(key: keyof Lookups) {
    cache.value = { ...cache.value, [key]: undefined }
    await ensure(key)
  }

  const options = {
    companies: computed<Option[]>(() => (cache.value.companies ?? []).map(c => ({ label: c.name, value: c.id! }))),
    subgroups: computed<Option[]>(() => (cache.value.subgroups ?? []).map(s => ({
      label: s.name, value: s.id!, description: groupLabel(s.group), group: s.group,
    }))),
    groups: computed<Option[]>(() => cache.value.groups ?? []),
    accounts: computed<Option[]>(() => (cache.value.accounts ?? []).map(a => ({ label: a.name, value: a.id!, company: a.company }) as Option)),
    products: computed<Option[]>(() => (cache.value.products ?? []).map(p => ({ label: p.name, value: p.id! }))),
    plans: computed<Option[]>(() => (cache.value.plans ?? []).map(p => ({ label: p.name, value: p.id! }))),
    salespeople: computed<Option[]>(() => (cache.value.salespeople ?? []).map(p => ({ label: p.name, value: p.id! }))),
    users: computed<Option[]>(() => (cache.value.users ?? []).map(u => ({ label: u.name || u.email, value: u.id! }))),
  }

  function groupLabel(value?: string | null) {
    return cache.value.groups?.find(g => g.value === value)?.label ?? value ?? ''
  }

  return { cache, ensure, refresh, options, groupLabel }
}
