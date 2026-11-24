<script setup lang="ts">
import type { components } from '~/types/api'

type Investment = components['schemas']['InvestmentOut']
type Movement = components['schemas']['MovementOut']

const props = defineProps<{ investment: Investment }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const lookups = useLookups()
lookups.ensure('accounts').catch(notifyError)
const canChange = computed(() => auth.can('investments', 'change'))

const items = ref<Movement[]>([])
async function load() {
  try {
    items.value = await unwrap(api.GET('/api/investment/{investment_id}/movements', { params: { path: { investment_id: props.investment.id! } } }))
  } catch (e) {
    notifyError(e)
  }
}
watch(() => props.investment.id, load, { immediate: true })

const KINDS = Object.entries(LABELS.movementKind).map(([value, label]) => ({ label, value }))
const form = reactive({ date: today(), kind: 'application', amount: 0, account_id: undefined as number | undefined, notes: '', saving: false })
const cash = computed(() => props.investment.holder === 'company' && form.kind !== 'balance')
const accounts = computed(() => lookups.options.accounts.value.filter(a => (a as any).company === props.investment.company_id))

async function add() {
  form.saving = true
  try {
    await unwrap(api.POST('/api/investment/{investment_id}/movements', {
      params: { path: { investment_id: props.investment.id! } },
      body: { date: form.date, kind: form.kind as any, amount: form.amount.toFixed(2), notes: form.notes,
              account_id: cash.value ? form.account_id ?? null : null },
    }))
    Object.assign(form, { amount: 0, notes: '' })
    notifySuccess('Movimento lançado')
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  } finally {
    form.saving = false
  }
}

async function remove(m: Movement) {
  if (!await confirm({ title: 'Excluir movimento?', description: m.transaction_id ? 'O lançamento no caixa também é excluído.' : undefined })) return
  try {
    await unwrap(api.DELETE('/api/investment-movement/{movement_id}', { params: { path: { movement_id: m.id! } } }))
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <SStat label="Aplicado" :value="formatMoney(Number(investment.applied) - Number(investment.redeemed))" />
      <SStat label="Saldo" :value="formatMoney(investment.balance)" tone="primary" />
      <SStat label="Rendimento" :value="formatMoney(investment.yield_amount)" :tone="Number(investment.yield_amount) < 0 ? 'error' : 'success'" />
      <SStat label="Rendimento %" :value="investment.yield_percent == null ? '—' : `${Number(investment.yield_percent).toLocaleString('pt-BR')}%`" />
    </div>

    <form v-if="canChange" class="grid gap-3 sm:grid-cols-6 items-end" @submit.prevent="add">
      <UFormField label="Data" class="sm:col-span-1">
        <UInput v-model="form.date" type="date" class="w-full" />
      </UFormField>
      <UFormField label="Tipo" class="sm:col-span-2">
        <USelect v-model="form.kind" :items="KINDS" class="w-full" />
      </UFormField>
      <UFormField :label="form.kind === 'balance' ? 'Saldo' : 'Valor'" class="sm:col-span-1">
        <UInputNumber v-model="form.amount" :step="0.01" :min="0" :increment="false" :decrement="false"
                      :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
      </UFormField>
      <UFormField v-if="cash" label="Conta" class="sm:col-span-2">
        <USelect v-model="form.account_id" :items="accounts" placeholder="Sem lançamento no caixa" class="w-full" />
      </UFormField>
      <UFormField label="Observação" class="sm:col-span-5">
        <UInput v-model="form.notes" class="w-full" />
      </UFormField>
      <UButton type="submit" label="Lançar" icon="i-lucide-plus" :loading="form.saving" :disabled="form.kind !== 'balance' && !form.amount" />
    </form>

    <div class="rounded-xl ring ring-default overflow-hidden">
      <table class="w-full text-sm">
        <thead class="text-xs text-muted">
          <tr>
            <th class="px-3 py-2 text-left font-medium">Data</th>
            <th class="px-3 py-2 text-left font-medium">Tipo</th>
            <th class="px-3 py-2 text-right font-medium">Valor</th>
            <th class="px-3 py-2 text-left font-medium">Conta</th>
            <th class="px-3 py-2 text-left font-medium">Observação</th>
            <th />
          </tr>
        </thead>
        <tbody class="divide-y divide-muted">
          <tr v-for="m in items" :key="m.id!">
            <td class="px-3 py-1.5 tabular whitespace-nowrap">{{ formatDate(m.date) }}</td>
            <td class="px-3 py-1.5">{{ LABELS.movementKind[m.kind] }}</td>
            <td class="px-3 py-1.5 text-right tabular" :class="{ 'text-success': m.kind === 'application', 'text-error': m.kind === 'redemption' }">
              {{ formatMoney(m.amount) }}
            </td>
            <td class="px-3 py-1.5 text-muted">{{ m.account_name ?? '—' }}</td>
            <td class="px-3 py-1.5 text-muted">{{ m.notes || '—' }}</td>
            <td class="px-3 py-1.5 text-right">
              <UButton v-if="canChange" icon="i-lucide-trash-2" color="neutral" variant="ghost" size="xs" aria-label="Excluir movimento" @click="remove(m)" />
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="6" class="px-3 py-4 text-center text-muted">Nenhum movimento</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
