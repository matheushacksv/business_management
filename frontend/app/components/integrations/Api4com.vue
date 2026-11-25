<script setup lang="ts">
import type { components } from '~/types/api'

type Line = components['schemas']['PhoneLineOut']

// Each user calls with their own API4COM login: token created here, password not kept
const { api, unwrap, notifyError, notifySuccess } = useApi()
const confirm = useConfirm()
const auth = useAuth()

const lines = ref<Line[]>([])
const users = ref<{ label: string; value: number }[]>([])
const load = () => unwrap(api.GET('/api/integrations/api4com')).then(l => (lines.value = l)).catch(notifyError)
load()
unwrap(api.GET('/api/user')).then(list => (users.value = list.filter(u => u.is_active)
  .map(u => ({ label: u.name || u.email, value: u.id! })))).catch(notifyError)

const form = reactive({ user_id: undefined as number | undefined, email: '', password: '', saving: false })
async function connect() {
  form.saving = true
  try {
    await unwrap(api.PUT('/api/integrations/api4com/{user_id}', {
      params: { path: { user_id: form.user_id! } }, body: { email: form.email, password: form.password },
    }))
    notifySuccess('Telefonia conectada')
    Object.assign(form, { user_id: undefined, email: '', password: '' })
    await load()
    auth.loadMe()
  } catch (e) {
    notifyError(e)
  } finally {
    form.saving = false
  }
}
async function disconnect(l: Line) {
  if (!await confirm({ title: `Desconectar ${l.name}?`, confirmLabel: 'Desconectar', color: 'error' })) return
  try {
    await unwrap(api.DELETE('/api/integrations/api4com/{user_id}', { params: { path: { user_id: l.user_id } } }))
    await load()
    auth.loadMe()
  } catch (e) {
    notifyError(e)
  }
}
const edit = (l: Line) => Object.assign(form, { user_id: l.user_id, email: l.email, password: '' })
</script>

<template>
  <SPanel title="API4COM">
    <form class="grid gap-4 md:grid-cols-4" @submit.prevent="connect">
      <UFormField label="Usuário do sistema">
        <USelectMenu v-model="form.user_id" :items="users" value-key="value" class="w-full" />
      </UFormField>
      <UFormField label="E-mail na API4COM">
        <UInput v-model="form.email" type="email" autocomplete="off" class="w-full" />
      </UFormField>
      <UFormField label="Senha na API4COM">
        <UInput v-model="form.password" type="password" autocomplete="new-password" class="w-full" />
      </UFormField>
      <div class="flex items-end">
        <UButton type="submit" label="Conectar" icon="i-lucide-plug" :loading="form.saving"
                 :disabled="!form.user_id || !form.email || !form.password" />
      </div>
    </form>

    <ul class="mt-4 flex flex-col divide-y divide-muted">
      <li v-for="l in lines" :key="l.user_id" class="flex items-center gap-3 py-2 text-sm">
        <UIcon name="i-lucide-phone" class="size-4 text-muted" />
        <div class="min-w-0 flex-1">
          <p class="text-highlighted">{{ l.name }}</p>
          <p class="text-xs text-dimmed">{{ l.email }} · ramal {{ l.extension }}</p>
        </div>
        <UBadge :label="l.valid ? 'Conectado' : 'Reconectar'" :color="l.valid ? 'success' : 'error'" variant="subtle" />
        <UButton icon="i-lucide-pencil" size="xs" color="neutral" variant="ghost" aria-label="Reconectar" @click="edit(l)" />
        <UButton icon="i-lucide-unplug" size="xs" color="neutral" variant="ghost" aria-label="Desconectar" @click="disconnect(l)" />
      </li>
    </ul>
  </SPanel>
</template>
