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
