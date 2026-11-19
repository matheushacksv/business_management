<script setup lang="ts">
import type { components } from '~/types/api'

definePageMeta({ permission: ['dunning', 'view'] })
const { api, unwrap, notifyError } = useApi()

const monthItems = monthOptions()
const month = ref(today().slice(0, 7))
const data = ref<components['schemas']['ProductivityOut'] | null>(null)
const loading = ref(false)
async function load() {
  const [y, m] = month.value.split('-').map(Number)
  const end = new Date(y!, m!, 0).getDate()
  loading.value = true
  try {
    data.value = await unwrap(api.GET('/api/dunning/productivity', {
      params: { query: { start: `${month.value}-01`, end: `${month.value}-${String(end).padStart(2, '0')}` } },
    }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(month, load, { immediate: true })
</script>

<template>
  <AppPage title="Produtividade da cobrança">
    <template #toolbar>
      <USelect v-model="month" :items="monthItems" class="w-32" aria-label="Mês" />
    </template>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <SStat label="Em atraso agora" :value="formatMoney(data?.overdue_amount)" :loading="loading" icon="i-lucide-alarm-clock" />
      <SStat label="Cards abertos" :value="String(data?.open_cards ?? 0)" :loading="loading" icon="i-lucide-columns-3" />
      <SStat label="Resolvidos no mês" :value="String(data?.resolved ?? 0)" tone="success" :loading="loading" icon="i-lucide-check-check" />
      <SStat label="Ao jurídico no mês" :value="String(data?.to_legal ?? 0)" :loading="loading" icon="i-lucide-scale" />
    </div>

    <div class="s-panel overflow-hidden">
      <table class="w-full text-sm tabular">
        <thead>
          <tr class="border-b border-default text-xs text-muted">
            <th class="px-4 py-2 text-left font-medium">Responsável</th>
            <th class="px-4 py-2 text-right font-medium">Concluídas</th>
            <th class="px-4 py-2 text-right font-medium">Mensagens</th>
            <th class="px-4 py-2 text-right font-medium">Ligações</th>
            <th class="px-4 py-2 text-right font-medium">Sem retorno</th>
            <th class="px-4 py-2 text-right font-medium">Pendentes</th>
            <th class="px-4 py-2 text-right font-medium">Atrasadas</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in data?.people ?? []" :key="p.user_id ?? 0" class="border-b border-muted">
            <td class="px-4 py-2 text-highlighted">{{ p.name }}</td>
            <td class="px-4 py-2 text-right text-success">{{ p.done }}</td>
            <td class="px-4 py-2 text-right">{{ p.messages }}</td>
            <td class="px-4 py-2 text-right">{{ p.calls }}</td>
            <td class="px-4 py-2 text-right" :class="{ 'text-warning': p.no_answer }">{{ p.no_answer }}</td>
            <td class="px-4 py-2 text-right">{{ p.pending }}</td>
            <td class="px-4 py-2 text-right" :class="{ 'text-error': p.late }">{{ p.late }}</td>
          </tr>
          <tr v-if="!data?.people.length"><td colspan="7" class="px-4 py-6 text-center text-dimmed">Nenhuma atividade</td></tr>
        </tbody>
      </table>
    </div>
  </AppPage>
</template>
