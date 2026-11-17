import type { components } from '~/types/api'

export type Me = components['schemas']['MeOut']
export type Action = 'view' | 'create' | 'change' | 'delete'

// The session lives in httpOnly cookies set by Django (/api/auth/*): JavaScript never
// touches the tokens. The browser sends them on every same-origin /api request.

let refreshing: Promise<boolean> | null = null

export function useAuth() {
  const me = useState<Me | null>('me', () => null)
  const base = useRuntimeConfig().public.apiBase

  async function login(email: string, password: string) {
    await $fetch(`${base}/api/auth/login`, { method: 'POST', body: { email, password } })
    // ponytail: drop the old JS-readable token cookies (pre-httpOnly sessions); remove after a while
    for (const name of ['gp_access', 'gp_refresh']) useCookie(name).value = null
    await loadMe()
  }

  /** One refresh at a time, shared by every request that got a 401. */
  function refresh(): Promise<boolean> {
    refreshing ??= $fetch(`${base}/api/auth/refresh`, { method: 'POST' })
      .then(() => true)
      .catch(() => false)
      .finally(() => { refreshing = null })
    return refreshing
  }

  async function loadMe() {
    me.value = await $fetch<Me>(`${base}/api/me`).catch(async (error) => {
      if (error?.response?.status === 401 && (await refresh())) return $fetch<Me>(`${base}/api/me`)
      throw error
    })
  }

  async function logout() {
    await $fetch(`${base}/api/auth/logout`, { method: 'POST' }).catch(() => {})
    me.value = null
    useState('lookups').value = {}
    return navigateTo('/login')
  }

  /** Mirrors the backend matrix (/api/me permissions) to hide what the user can't do. */
  function can(module: string, action: Action = 'view'): boolean {
    return !!me.value?.permissions?.[module]?.includes(action)
  }

  return { me, login, logout, refresh, loadMe, can }
}
