<script setup lang="ts">
import type { components } from '~/types/api'

type Config = components['schemas']['BlingConfigOut']
type State = Omit<Config, 'percent'> & { percent: number; client_secret: string; saving: boolean; natures: { label: string; value: number }[] }

const { api, unwrap, notifyError, notifySuccess } = useApi()
const route = useRoute()
const router = useRouter()

const toState = (c: Config): State => ({ ...c, percent: Number(c.percent), client_secret: '', saving: false, natures: [] })
const configs = ref<State[]>([])
async function load() {
  configs.value = (await unwrap(api.GET('/api/integrations/bling'))).map(toState)
  configs.value.filter(c => c.connected).forEach(loadNatures)
}
load().catch(notifyError)

// Back from Bling's authorization screen: ?bling=ok | error message
const result = route.query.bling
if (result) {
  result === 'ok' ? notifySuccess('Bling autorizado') : notifyError(String(result))
  router.replace({ query: { ...route.query, bling: undefined } })
}

async function loadNatures(c: State) {
  try {
    c.natures = (await unwrap(api.GET('/api/integrations/bling/{company_id}/natures', { params: { path: { company_id: c.company_id } } })))
      .map(n => ({ label: n.name, value: n.id }))
  } catch (e) {
    notifyError(e)
  }
}

async function save(c: State) {
  c.saving = true
  try {
    const saved = await unwrap(api.PUT('/api/integrations/bling/{company_id}', {
      params: { path: { company_id: c.company_id } },
      body: { client_id: c.client_id, client_secret: c.client_secret || null, nature_id: c.nature_id ?? null,
              nature_name: c.natures.find(n => n.value === c.nature_id)?.label ?? c.nature_name, percent: String(c.percent) },
    }))
    Object.assign(c, toState(saved), { natures: c.natures })
    notifySuccess('Salvo')
  } catch (e) {
    notifyError(e)
  } finally {
    c.saving = false
  }
}

async function authorize(c: State) {
  try {
    location.href = (await unwrap(api.POST('/api/integrations/bling/{company_id}/authorize', { params: { path: { company_id: c.company_id } } }))).url
  } catch (e) {
    notifyError(e)
  }
}

const redirectUrl = computed(() => `${location.origin}/api/integrations/bling/callback`)
const webhookUrl = (c: State) => `${location.origin}/api/webhooks/bling/${c.company_id}`
const copy = (text: string) => navigator.clipboard.writeText(text).then(() => notifySuccess('Copiado'))
</script>

<template>
  <SPanel v-for="c in configs" :key="c.company_id" :title="`Bling · ${c.company_name}`">
    <template #actions>
      <UBadge :label="c.connected ? 'Autorizado' : 'Não autorizado'" :color="c.connected ? 'success' : 'neutral'" variant="subtle" />
    </template>
    <div class="grid gap-4 md:grid-cols-3">
      <UFormField label="Client ID">
        <UInput v-model="c.client_id" autocomplete="off" class="w-full" />
      </UFormField>
      <UFormField label="Client Secret">
        <UInput v-model="c.client_secret" type="password" autocomplete="new-password" :placeholder="c.has_secret ? '••••••••' : ''" class="w-full" />
      </UFormField>
      <UFormField label="NF de produto (% da parcela)">
        <UInputNumber v-model="c.percent" :min="0.01" :max="100" :step="0.01" class="w-full" />
      </UFormField>
      <UFormField label="Natureza de operação" class="md:col-span-2">
        <USelect :model-value="c.nature_id ?? undefined" :items="c.natures.length ? c.natures : (c.nature_id ? [{ label: c.nature_name, value: c.nature_id }] : [])"
                 :disabled="!c.connected" placeholder="Autorize para listar" class="w-full"
                 @update:model-value="(v: any) => (c.nature_id = v ?? null)" />
      </UFormField>
      <UFormField label="Link de redirecionamento">
        <UInput :model-value="redirectUrl" readonly class="w-full">
          <template #trailing>
            <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar link" @click="copy(redirectUrl)" />
          </template>
        </UInput>
      </UFormField>
      <UFormField label="Webhook (URL)" class="md:col-span-3">
        <UInput :model-value="webhookUrl(c)" readonly class="w-full">
          <template #trailing>
            <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar URL" @click="copy(webhookUrl(c))" />
          </template>
        </UInput>
      </UFormField>
    </div>
    <div class="mt-4 flex gap-2">
      <UButton label="Salvar" icon="i-lucide-check" :loading="c.saving" @click="save(c)" />
      <UButton :label="c.connected ? 'Autorizar de novo' : 'Autorizar no Bling'" icon="i-lucide-key-round" color="neutral" variant="outline"
               :disabled="!c.client_id || !c.has_secret" @click="authorize(c)" />
    </div>
  </SPanel>
</template>
