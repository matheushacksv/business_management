<script setup lang="ts">
import { z } from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

definePageMeta({ layout: 'auth' })

const schema = z.object({
  email: z.email('E-mail inválido'),
  password: z.string().min(1, 'Informe a senha'),
})
type Schema = z.output<typeof schema>

const state = reactive<Partial<Schema>>({ email: '', password: '' })
const loading = ref(false)
const error = ref('')
const route = useRoute()
const auth = useAuth()

async function onSubmit(event: FormSubmitEvent<Schema>) {
  loading.value = true
  error.value = ''
  try {
    await auth.login(event.data.email, event.data.password)
    await navigateTo((route.query.next as string) || '/')
  } catch (e: any) {
    error.value = e?.response?.status === 401 ? 'E-mail ou senha incorretos' : 'Não foi possível entrar. Tente novamente.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <UColorModeButton color="neutral" variant="ghost" class="fixed top-4 right-4" />
  <div class="w-full max-w-sm s-enter">
    <div class="mb-8 text-center">
      <SLogo class="mx-auto mb-6 h-12 w-auto" />
      <h1 class="font-display text-3xl font-semibold tracking-tight text-highlighted">Financeiro</h1>
      <p class="mt-2 text-sm text-muted">Grupo Enriquecedor</p>
    </div>

    <div class="s-panel p-6">
      <UForm :schema="schema" :state="state" class="space-y-4" @submit="onSubmit">
        <UFormField name="email" label="E-mail">
          <UInput v-model="state.email" type="email" autocomplete="username" icon="i-lucide-mail" class="w-full" autofocus />
        </UFormField>
        <UFormField name="password" label="Senha">
          <UInput v-model="state.password" type="password" autocomplete="current-password" icon="i-lucide-lock" class="w-full" />
        </UFormField>

        <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />

        <UButton type="submit" block size="lg" :loading="loading" label="Entrar" class="rounded-full" />
      </UForm>
    </div>
  </div>
</template>
