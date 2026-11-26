import type { components } from '~/types/api'

type Stage = components['schemas']['StageOut']

/** Funnel stages and the users who can be responsible, loaded once per page. */
export function useDunning() {
  const { api, unwrap, notifyError } = useApi()
  const stages = ref<Stage[]>([])
  const assignees = ref<{ label: string; value: number }[]>([])
  Promise.all([
    unwrap(api.GET('/api/dunning/stage')),
    unwrap(api.GET('/api/dunning/assignees')),
  ]).then(([s, a]) => {
    stages.value = s
    assignees.value = a.map(u => ({ label: u.name || u.email, value: u.id }))
  }).catch(notifyError)
  return { stages, assignees }
}

/** Toast once per user for cards that closed by themselves (paid) in the last week: mine, or all for managers. */
export async function notifyPaidOff(view: () => void) {
  const me = useAuth().me.value
  if (!me?.id || import.meta.server) return
  const { api, unwrap } = useApi()
  const everyone = me.is_admin || me.is_superuser || me.role === 'manager'
  const key = `dunning-paid-seen:${me.id}`
  const seen = new Set<number>(JSON.parse(localStorage.getItem(key) ?? '[]'))
  const since = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10)
  const cards = await unwrap(api.GET('/api/dunning/card', { params: { query: { outcome: 'resolved', assignee_id: everyone ? undefined : me.id } } }))
  const fresh = cards.filter(c => (c.closed_at ?? '') >= since && !seen.has(c.id))
  if (!fresh.length) return
  localStorage.setItem(key, JSON.stringify([...seen, ...fresh.map(c => c.id)].slice(-500)))
  useToast().add({
    title: fresh.length === 1 ? `${fresh[0]!.contact_name} pagou e saiu da cobrança` : `${fresh.length} clientes pagaram e saíram da cobrança`,
    icon: 'i-lucide-badge-check', color: 'success', duration: 10000,
    actions: [{ label: 'Ver resolvidos', variant: 'outline', onClick: view }],
  })
}
