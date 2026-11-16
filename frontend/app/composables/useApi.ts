import createClient from 'openapi-fetch'
import type { paths } from '~/types/api'

/** Error carrying the API's readable message (400/403/404 detail or 422 field errors). */
export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message)
  }
}

export function errorMessage(body: any, status: number): string {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => (typeof d === 'string' ? d : `${(d.loc ?? []).filter((x: any) => x !== 'body').join('.')}: ${d.msg}`))
      .join('\n')
  }
  return { 401: 'Sessão expirada', 403: 'Sem permissão', 404: 'Não encontrado' }[status] ?? 'Erro inesperado'
}

let client: ReturnType<typeof createClient<paths>> | null = null

export function useApi() {
  const auth = useAuth()
  const toast = useToast()
  const base = useRuntimeConfig().public.apiBase

  /** fetch with the access token; on 401 refreshes once and retries; still 401 -> login. */
  async function authFetch(input: Request): Promise<Response> {
    const retry = input.clone()
    const send = (req: Request) => {
      if (auth.access.value) req.headers.set('Authorization', `Bearer ${auth.access.value}`)
      return globalThis.fetch(req)
    }
    const response = await send(input)
    if (response.status !== 401) return response
    if (await auth.refresh()) {
      const again = await send(retry)
      if (again.status !== 401) return again
    }
    auth.logout()
    return response
  }

  client ??= createClient<paths>({ baseUrl: base, fetch: authFetch })

  /**
   * Await an openapi-fetch call and return its data, or throw ApiError.
   *   const tx = await unwrap(api.GET('/api/transaction/{transaction_id}', {...}))
   */
  async function unwrap<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
    const { data, error, response } = await call
    if (!response.ok) throw new ApiError(response.status, errorMessage(error, response.status), error)
    return data as T
  }

  function notifyError(error: unknown, title = 'Não foi possível concluir') {
    const description = error instanceof ApiError ? error.message : String(error)
    toast.add({ title, description, color: 'error', icon: 'i-lucide-circle-alert' })
  }

  function notifySuccess(title: string) {
    toast.add({ title, color: 'success', icon: 'i-lucide-check' })
  }

  /** Raw authenticated request, for multipart uploads and file downloads. */
  async function raw(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await authFetch(new Request(`${base}${path}`, init))
    if (!response.ok) {
      const body = await response.json().catch(() => undefined)
      throw new ApiError(response.status, errorMessage(body, response.status), body)
    }
    return response
  }

  async function download(path: string, fallbackName = 'arquivo') {
    const response = await raw(path)
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName
    const url = URL.createObjectURL(await response.blob())
    const link = Object.assign(document.createElement('a'), { href: url, download: decodeURIComponent(name) })
    link.click()
    URL.revokeObjectURL(url)
  }

  return { api: client, unwrap, raw, download, notifyError, notifySuccess }
}
