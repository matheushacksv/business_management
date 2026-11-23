<script setup lang="ts">
import type { components } from '~/types/api'

type Config = components['schemas']['AsaasConfigOut']

const { api, unwrap, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
lookups.ensure('accounts').catch(notifyError)

const NUMBERS = ['fine_percent', 'interest_percent', 'invoice_percent', 'iss_rate'] as const
type State = Omit<Config, (typeof NUMBERS)[number]> & Record<(typeof NUMBERS)[number], number> & { api_key: string; saving: boolean }
const toState = (c: Config) => ({ ...c, ...Object.fromEntries(NUMBERS.map(k => [k, Number(c[k])])), api_key: '', saving: false }) as unknown as State
const configs = ref<State[]>([])
unwrap(api.GET('/api/integrations/asaas')).then(list => (configs.value = list.map(toState))).catch(notifyError)

const webhookUrl = computed(() => `${location.origin}/api/webhooks/asaas`)
const copy = (text: string) => navigator.clipboard.writeText(text).then(() => notifySuccess('Copiado'))
const accountsOf = (companyId: number) => (lookups.cache.value.accounts ?? [])
  .filter(a => a.company === companyId).map(a => ({ label: a.name, value: a.id! }))

async function save(c: State) {
  c.saving = true
  try {
    const saved = await unwrap(api.PUT('/api/integrations/asaas/{company_id}', {
      params: { path: { company_id: c.company_id } },
      body: {
        api_key: c.api_key || null, sandbox: c.sandbox, account_id: c.account_id ?? null,
        ...Object.fromEntries(NUMBERS.map(k => [k, String(c[k])])) as Record<(typeof NUMBERS)[number], string>,
        service_id: c.service_id, service_name: c.service_name, description_template: c.description_template,
      },
    }))
    Object.assign(c, toState(saved))
    notifySuccess('Salvo')
  } catch (e) {
    notifyError(e)
  } finally {
    c.saving = false
  }
}
</script>

<template>
  <SPanel v-for="c in configs" :key="c.company_id" :title="`Asaas · ${c.company_name}`">
    <template #actions>
      <UBadge v-if="c.has_key" :label="c.sandbox ? 'Sandbox' : 'Produção'" :color="c.sandbox ? 'warning' : 'success'" variant="subtle" />
    </template>
    <div class="grid gap-4 md:grid-cols-3">
      <UFormField label="Chave da API" class="md:col-span-2">
        <UInput v-model="c.api_key" type="password" autocomplete="off" :placeholder="c.has_key ? '••••••••' : ''" class="w-full" />
      </UFormField>
      <UFormField label="Ambiente">
        <USelect v-model="c.sandbox" :items="[{ label: 'Sandbox', value: true }, { label: 'Produção', value: false }]" class="w-full" />
      </UFormField>
      <UFormField label="Conta de recebimento">
        <USelect :model-value="c.account_id ?? undefined" :items="accountsOf(c.company_id)" placeholder="Nenhuma" class="w-full"
                 @update:model-value="(v: any) => (c.account_id = v ?? null)" />
      </UFormField>
      <UFormField label="Multa (%)">
        <UInputNumber v-model="c.fine_percent" :min="0" :max="100" :step="0.01" class="w-full" />
      </UFormField>
      <UFormField label="Juros ao mês (%)">
        <UInputNumber v-model="c.interest_percent" :min="0" :max="100" :step="0.01" class="w-full" />
      </UFormField>
      <UFormField label="NFS-e (% da parcela)">
        <UInputNumber v-model="c.invoice_percent" :min="0" :max="100" :step="0.01" class="w-full" />
      </UFormField>
      <UFormField label="ISS (%)">
        <UInputNumber v-model="c.iss_rate" :min="0" :max="100" :step="0.01" class="w-full" />
      </UFormField>
      <UFormField label="ID do serviço municipal">
        <UInput v-model="c.service_id" class="w-full" />
      </UFormField>
      <UFormField label="Serviço municipal" class="md:col-span-3">
        <UInput v-model="c.service_name" class="w-full" />
      </UFormField>
      <UFormField label="Descrição da NFS-e" class="md:col-span-3">
        <UTextarea v-model="c.description_template" :rows="2" autoresize class="w-full" />
      </UFormField>
      <template v-if="c.webhook_token">
        <UFormField label="Webhook (URL)">
          <UInput :model-value="webhookUrl" readonly class="w-full">
            <template #trailing>
              <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar URL" @click="copy(webhookUrl)" />
            </template>
          </UInput>
        </UFormField>
        <UFormField label="Token de autenticação" class="md:col-span-2">
          <UInput :model-value="c.webhook_token" readonly class="w-full font-mono">
            <template #trailing>
              <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar token" @click="copy(c.webhook_token)" />
            </template>
          </UInput>
        </UFormField>
      </template>
    </div>
    <UButton label="Salvar" icon="i-lucide-check" class="mt-4" :loading="c.saving" @click="save(c)" />
  </SPanel>
</template>
