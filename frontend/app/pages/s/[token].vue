<script setup lang="ts">
import type { components } from '~/types/api'

definePageMeta({ layout: 'auth', public: true })
useHead({ meta: [{ name: 'robots', content: 'noindex' }] })

const { api, unwrap, notifyError } = useApi()
const token = String(useRoute().params.token)
const password = ref('')
const loading = ref(false)
const data = ref<components['schemas']['StatementOut'] | null>(null)

async function open() {
  loading.value = true
  try {
    data.value = await unwrap(api.POST('/api/public/statement/{token}', {
      params: { path: { token } }, body: { password: password.value },
    }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
const printPage = () => window.print()
</script>

<template>
  <div v-if="data" class="w-full max-w-4xl py-8 flex flex-col gap-4">
    <div class="flex justify-end">
      <UButton label="Imprimir" icon="i-lucide-printer" color="neutral" variant="outline" @click="printPage" />
    </div>
    <SalesStatementSheet :data="data" />
  </div>
  <form v-else class="s-panel w-full max-w-sm p-6 flex flex-col gap-4" @submit.prevent="open">
    <h1 class="font-display text-xl font-semibold">Demonstrativo</h1>
    <UFormField label="Senha">
      <UInput v-model="password" type="password" autocomplete="off" autofocus class="w-full" />
    </UFormField>
    <UButton type="submit" label="Abrir" block :loading="loading" :disabled="!password" />
  </form>
</template>
