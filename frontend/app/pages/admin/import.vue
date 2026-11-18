<script setup lang="ts">
import type { components } from '~/types/api'

type Result = components['schemas']['ImportOut']
definePageMeta({ permission: ['users', 'view'] })  // admins only (the API checks is_admin)

const { raw, notifyError, notifySuccess } = useApi()
const lookups = useLookups()
await lookups.ensure('companies')

const file = ref<File | null>(null)
const defaultCompany = ref<number | undefined>()
const mapping = reactive<Record<string, number | undefined>>({})
const result = ref<Result | null>(null)
const busy = ref(false)
const step = computed(() => (result.value?.committed ? 3 : result.value ? 2 : 1))

async function send(commit: boolean) {
  if (!file.value || !defaultCompany.value) {
    notifyError('Escolha o arquivo e a empresa padrão.', 'Dados incompletos')
    return
  }
  const companies = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v))
  const form = new FormData()
  form.append('file', file.value)
  form.append('default_company_id', String(defaultCompany.value))
  form.append('companies', JSON.stringify(companies))
  form.append('commit', String(commit))
  busy.value = true
  try {
    result.value = await (await raw('/api/import', { method: 'POST', body: form })).json()
    for (const name of result.value!.company_names) if (!(name in mapping)) mapping[name] = undefined
    if (commit) notifySuccess('Importação concluída')
  } catch (e) {
    notifyError(e, commit ? 'Falha na importação' : 'Falha na prévia')
  } finally {
    busy.value = false
  }
}

const unmapped = computed(() => result.value?.company_names.filter(n => !mapping[n]) ?? [])
const skippedByReason = computed(() => {
  const counts: Record<string, number> = {}
  for (const s of result.value?.skipped ?? []) {
    const key = s.reason.startsWith('sales:') ? s.reason.split(': ').slice(0, 2).join(': ') : s.reason.split(':')[0]!
    counts[key] = (counts[key] ?? 0) + 1
  }
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
})
watch(file, () => { result.value = null })
</script>

<template>
  <AppPage title="Importar planilha">
    <UStepper :model-value="step - 1" disabled :items="[
      { title: 'Arquivo', icon: 'i-lucide-upload' },
      { title: 'Prévia e empresas', icon: 'i-lucide-scan-eye' },
      { title: 'Concluído', icon: 'i-lucide-check' },
    ]" class="max-w-2xl" />

    <SPanel title="1. Planilha">
      <div class="grid gap-4 sm:grid-cols-2">
        <UFileUpload v-model="file" accept=".xlsx" label="Solte o .xlsx aqui" icon="i-lucide-file-spreadsheet" class="min-h-32 sm:col-span-2" />
        <UFormField label="Empresa padrão" required>
          <USelect v-model="defaultCompany" :items="lookups.options.companies.value" placeholder="Escolha" class="w-full" />
        </UFormField>
        <div class="flex items-end">
          <UButton label="Gerar prévia" icon="i-lucide-scan-eye" :loading="busy && !result" :disabled="!file || !defaultCompany"
                   @click="send(false)" />
        </div>
      </div>
    </SPanel>

    <template v-if="result">
      <SPanel v-if="result.company_names.length" title="2. Empresas da planilha">
        <div class="grid gap-3 sm:grid-cols-2">
          <UFormField v-for="name in result.company_names" :key="name" :label="name" required>
            <USelect v-model="mapping[name]" :items="lookups.options.companies.value" placeholder="Escolha" class="w-full" />
          </UFormField>
        </div>
        <UButton v-if="!result.committed" label="Atualizar prévia" icon="i-lucide-refresh-cw" color="neutral" variant="outline"
                 class="mt-4" :loading="busy" :disabled="!!unmapped.length" @click="send(false)" />
      </SPanel>

      <div class="grid gap-4 sm:grid-cols-4">
        <SStat label="Lançamentos" :value="(result.committed ? result.transactions_created : result.transactions_found).toLocaleString('pt-BR')"
               :hint="result.committed ? 'importados' : 'na planilha'" icon="i-lucide-arrow-left-right" />
        <SStat label="Vendas" :value="(result.committed ? result.sales_created : result.sales_found).toLocaleString('pt-BR')"
               :hint="result.committed ? 'importadas' : 'na planilha'" icon="i-lucide-handshake" />
        <SStat label="Contatos novos" :value="String(result.contacts_created)" icon="i-lucide-contact" />
        <SStat label="Linhas puladas" :value="String(result.skipped.length)" tone="error" icon="i-lucide-circle-slash" />
      </div>

      <SPanel v-if="result.skipped.length" title="Linhas puladas">
        <ul class="mb-4 flex flex-wrap gap-2">
          <li v-for="[reason, n] in skippedByReason" :key="reason">
            <UBadge :label="`${reason}: ${n}`" color="neutral" variant="subtle" />
          </li>
        </ul>
        <div class="max-h-64 overflow-auto rounded-xl ring ring-default">
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="s in result.skipped" :key="`${s.row}-${s.reason}`" class="border-b border-muted last:border-0">
                <td class="px-3 py-1.5 text-dimmed tabular w-20">linha {{ s.row }}</td>
                <td class="px-3 py-1.5">{{ s.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SPanel>

      <SPanel v-if="!result.committed">
        <div class="flex flex-wrap items-center gap-3">
          <UIcon name="i-lucide-triangle-alert" class="size-5 text-amber-400" />
          <p class="flex-1 text-sm">
            A importação só roda com o banco vazio de lançamentos e vendas, e grava tudo de uma vez.
          </p>
          <UButton label="Importar agora" icon="i-lucide-database" class="rounded-full" :loading="busy"
                   :disabled="!!unmapped.length" @click="send(true)" />
        </div>
      </SPanel>
      <UAlert v-else color="success" variant="subtle" icon="i-lucide-circle-check" title="Importação concluída" />
    </template>
  </AppPage>
</template>
