// API4COM click-to-call: the Webphone rings first, then the customer. The webhook fills the call in,
// so it is polled until it ends (max 5 min) and `onEnded` refreshes whatever shows it. Never locks: call again anytime.
export function usePhoneCall() {
  const { api, unwrap, notifyError, notifySuccess } = useApi()
  const calling = ref(false)
  let poll: ReturnType<typeof setInterval> | undefined
  onBeforeUnmount(() => clearInterval(poll))

  async function call(target: { activity_id: number } | { contact_id: number }, onEnded: () => void) {
    calling.value = true
    try {
      const c = 'activity_id' in target
        ? await unwrap(api.POST('/api/dunning/activity/{activity_id}/call', { params: { path: target } }))
        : await unwrap(api.POST('/api/contact/{contact_id}/call', { params: { path: target } }))
      notifySuccess('Chamando: atenda no Webphone')
      onEnded()  // shows the new call as "chamando…"
      clearInterval(poll)
      const until = Date.now() + 5 * 60_000
      poll = setInterval(async () => {
        const now = await unwrap(api.GET('/api/call/{call_id}', { params: { path: { call_id: c.id } } })).catch(() => null)
        if (!now || now.ended_at || Date.now() > until) {
          clearInterval(poll)
          onEnded()
        }
      }, 5000)
    } catch (e) {
      notifyError(e)
    } finally {
      calling.value = false
    }
  }
  return { calling, call }
}

export const callLabel = (c: { answered_at?: string | null; ended_at?: string | null; duration?: number | null }) => c.answered_at
  ? `${Math.floor((c.duration ?? 0) / 60)}:${String((c.duration ?? 0) % 60).padStart(2, '0')}`
  : c.ended_at ? 'não atendida' : 'chamando…'
