import type { components } from '~/types/api'

export type Me = components['schemas']['MeOut']
export type Action = 'view' | 'create' | 'change' | 'delete'

// ponytail: tokens in JS-readable cookies; move the refresh token to an httpOnly cookie
// set by Django before production (needs a small backend change)
const COOKIE = { maxAge: 60 * 60 * 24 * 7, sameSite: 'strict' as const, secure: !import.meta.dev }

let refreshing: Promise<boolean> | null = null

export function useAuth() {
  const config = useRuntimeConfig()
  const access = useCookie<string | null>('gp_access', COOKIE)
  const refreshToken = useCookie<string | null>('gp_refresh', COOKIE)
  const me = useState<Me | null>('me', () => null)

  const base = config.public.apiBase

  async function login(email: string, password: string) {
    const tokens = await $fetch<{ access: string; refresh: string }>(`${base}/api/token/pair`, {
      method: 'POST',
      body: { email, password },
    })
    access.value = tokens.access
    refreshToken.value = tokens.refresh
    await loadMe()
  }

  /** One refresh at a time, shared by every request that got a 401. */
  function refresh(): Promise<boolean> {
    if (!refreshToken.value) return Promise.resolve(false)
    refreshing ??= $fetch<{ access: string; refresh?: string }>(`${base}/api/token/refresh`, {
      method: 'POST',
      body: { refresh: refreshToken.value },
    })
      .then((tokens) => {
        access.value = tokens.access
        if (tokens.refresh) refreshToken.value = tokens.refresh
        return true
      })
      .catch(() => false)
      .finally(() => { refreshing = null })
    return refreshing
  }

  async function loadMe() {
    me.value = await $fetch<Me>(`${base}/api/me`, {
      headers: { Authorization: `Bearer ${access.value}` },
    }).catch(async (error) => {
      if (error?.response?.status === 401 && (await refresh())) {
        return $fetch<Me>(`${base}/api/me`, { headers: { Authorization: `Bearer ${access.value}` } })
      }
      throw error
    })
  }

  function logout() {
    access.value = null
    refreshToken.value = null
    me.value = null
    useState('lookups').value = {}
    return navigateTo('/login')
  }

  /** Mirrors the backend matrix (/api/me permissions) to hide what the user can't do. */
  function can(module: string, action: Action = 'view'): boolean {
    return !!me.value?.permissions?.[module]?.includes(action)
  }

  return { access, refreshToken, me, login, logout, refresh, loadMe, can }
}
