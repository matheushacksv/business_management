import type { Action } from '~/composables/useAuth'

// Every page needs a session, except /login. Page meta `permission: ['module', 'action']`
// sends users without it to the home page (the API would answer 403 anyway).
export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth()
  const isLogin = to.path === '/login'

  if (!auth.access.value && !auth.refreshToken.value) {
    return isLogin ? undefined : navigateTo({ path: '/login', query: { next: to.fullPath } })
  }
  if (!auth.me.value) {
    try {
      await auth.loadMe()
    } catch {
      return auth.logout()
    }
  }
  if (isLogin) return navigateTo('/')

  const permission = to.meta.permission as [string, Action?] | undefined
  if (permission && !auth.can(permission[0], permission[1] ?? 'view')) {
    return navigateTo('/')
  }
})
