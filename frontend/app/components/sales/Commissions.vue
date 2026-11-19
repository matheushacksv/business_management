<script setup lang="ts">
import type { components } from '~/types/api'

type Commission = components['schemas']['CommissionOut']
type Kind = components['schemas']['CommissionKind']
const props = defineProps<{ saleId: number }>()

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const lookups = useLookups()
lookups.ensure('salespeople').catch(notifyError)
const canChange = computed(() => auth.can('sales', 'change'))

const items = ref<Commission[]>([])
async function load() {
  try {
    items.value = await unwrap(api.GET('/api/sale/{sale_id}/commissions', { params: { path: { sale_id: props.saleId } } }))
  } catch (e) {
    notifyError(e)
  }
}
watch(() => props.saleId, load, { immediate: true })

const total = computed(() => items.value.reduce((s, c) => s + Number(c.amount), 0))
const isPercent = (kind: string) => PERCENT_COMMISSION_KINDS.includes(kind)
const kindItems = Object.entries(LABELS.commissionKind).map(([value, label]) => ({ label, value }))
const people = computed(() => lookups.options.salespeople.value)

// New line
const form = reactive({ kind: 'seller' as Kind, salesperson_id: undefined as number | undefined, value: 10, description: '' })
watch(() => form.kind, k => { form.value = isPercent(k) ? 10 : 0 })
const saving = ref(false)
async function add() {
  if (!form.salesperson_id || !form.value) return
  saving.value = true
  try {
    await unwrap(api.POST('/api/sale/{sale_id}/commissions', {
      params: { path: { sale_id: props.saleId } },
      body: {
        kind: form.kind, salesperson_id: form.salesperson_id, description: form.description,
        ...(isPercent(form.kind) ? { percent: form.value.toFixed(2) } : { fixed_amount: form.value.toFixed(2) }),
      },
    }))
    form.salesperson_id = undefined
    form.description = ''
    await load()
  } catch (e) {
    notifyError(e)
  } finally {
    saving.value = false
  }
}

async function remove(c: Commission) {
  if (!await confirm({ title: `Remover comissão de ${c.salesperson_name}?`, confirmLabel: 'Remover', color: 'error' })) return
  try {
    await unwrap(api.DELETE('/api/commission/{commission_id}', { params: { path: { commission_id: c.id } } }))
    await load()
  } catch (e) {
    notifyError(e)
  }
}

async function setValue(c: Commission, value: number | null) {
  if (!value) return
  try {
    await unwrap(api.PATCH('/api/commission/{commission_id}', {
      params: { path: { commission_id: c.id } },
      body: isPercent(c.kind) ? { percent: value.toFixed(2) } : { fixed_amount: value.toFixed(2) },
    }))
  } catch (e) {
    notifyError(e)
  }
  await load()
}

// Split one total equally among the unpaid lines of the same kind (cents go to the last one)
const split = reactive({ open: false, kind: '' as string, total: 10 })
const splitLines = computed(() => items.value.filter(c => c.kind === split.kind && !c.payment_id))
// ponytail: only % kinds split equally; fixed kinds (CRM 500 + 250) are typed per person
const kindsToSplit = computed(() => PERCENT_COMMISSION_KINDS
  .filter(k => items.value.filter(c => c.kind === k && !c.payment_id).length > 1))
function openSplit(kind: string) {
  const lines = items.value.filter(c => c.kind === kind && !c.payment_id)
  split.kind = kind
  split.total = lines.reduce((s, c) => s + Number(isPercent(kind) ? c.percent : c.fixed_amount), 0)
  split.open = true
}
async function applySplit() {
  const lines = splitLines.value
  const cents = Math.round(split.total * 100)
  const each = Math.floor(cents / lines.length)
  try {
    await Promise.all(lines.map((c, i) => {
      const value = ((i === lines.length - 1 ? cents - each * (lines.length - 1) : each) / 100).toFixed(2)
      return unwrap(api.PATCH('/api/commission/{commission_id}', {
        params: { path: { commission_id: c.id } },
        body: isPercent(c.kind) ? { percent: value } : { fixed_amount: value },
      }))
    }))
    split.open = false
  } catch (e) {
    notifyError(e)
  }
  await load()
}
</script>

<template>
  <div class="space-y-4">
    <ul v-if="items.length" class="divide-y divide-muted rounded-xl ring ring-default">
      <li v-for="c in items" :key="c.id" class="flex items-center gap-3 px-3 py-2 text-sm">
        <div class="min-w-0 flex-1">
          <p class="truncate text-highlighted">{{ c.salesperson_name }}</p>
          <p class="truncate text-xs text-dimmed">
            {{ LABELS.commissionKind[c.kind] }}{{ c.description ? ` · ${c.description}` : '' }}
          </p>
        </div>
        <template v-if="canChange && !c.payment_id">
          <UInputNumber v-if="isPercent(c.kind)" :model-value="Number(c.percent)" :min="0" :max="100" :step="0.01"
                        :increment="false" :decrement="false" size="xs" class="w-20" aria-label="Percentual"
                        @update:model-value="v => setValue(c, v)" />
          <UInputNumber v-else :model-value="Number(c.fixed_amount)" :min="0" :step="0.01" :increment="false" :decrement="false"
                        :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" size="xs" class="w-28"
                        aria-label="Valor" @update:model-value="v => setValue(c, v)" />
        </template>
        <span v-else-if="isPercent(c.kind)" class="text-xs text-muted tabular">{{ Number(c.percent).toLocaleString('pt-BR') }}%</span>
        <UBadge :label="c.payment_id ? 'Paga' : c.first_payment ? 'A pagar' : 'Aguardando cliente'"
                :color="c.payment_id ? 'success' : c.first_payment ? 'warning' : 'neutral'" variant="subtle" size="sm" />
        <span class="w-28 text-right tabular">{{ formatMoney(c.amount) }}</span>
        <UButton v-if="canChange && !c.payment_id" icon="i-lucide-trash-2" color="neutral" variant="ghost" size="xs"
                 aria-label="Remover" @click="remove(c)" />
      </li>
      <li class="flex items-center justify-between px-3 py-2 text-sm font-medium">
        <span>Total</span>
        <span class="tabular">{{ formatMoney(total) }}</span>
      </li>
    </ul>
    <p v-else class="text-sm text-dimmed">Nenhuma comissão.</p>

    <div v-if="canChange && kindsToSplit.length" class="flex flex-wrap gap-2">
      <UButton v-for="k in kindsToSplit" :key="k" :label="`Dividir ${LABELS.commissionKind[k]}`" icon="i-lucide-split"
               size="xs" color="neutral" variant="outline" @click="openSplit(k)" />
    </div>

    <SPanel v-if="canChange" title="Adicionar">
      <div class="grid gap-3 sm:grid-cols-2">
        <UFormField label="Tipo">
          <USelect v-model="form.kind" :items="kindItems" class="w-full" />
        </UFormField>
        <UFormField label="Profissional">
          <USelectMenu v-model="form.salesperson_id" :items="people" value-key="value" class="w-full" />
        </UFormField>
        <UFormField :label="isPercent(form.kind) ? 'Percentual (%)' : 'Valor'">
          <UInputNumber v-if="isPercent(form.kind)" v-model="form.value" :min="0" :max="100" :step="0.01" class="w-full" />
          <UInputNumber v-else v-model="form.value" :min="0" :step="0.01" :increment="false" :decrement="false"
                        :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
        </UFormField>
        <UFormField v-if="form.kind === 'other'" label="Descrição">
          <UInput v-model="form.description" class="w-full" />
        </UFormField>
      </div>
      <UButton label="Adicionar" icon="i-lucide-plus" class="mt-4" :loading="saving"
               :disabled="!form.salesperson_id || !form.value" @click="add" />
    </SPanel>

    <UModal v-model:open="split.open" :title="`Dividir ${LABELS.commissionKind[split.kind] ?? ''} entre ${splitLines.length}`">
      <template #body>
        <UFormField :label="isPercent(split.kind) ? 'Total (%)' : 'Total'">
          <UInputNumber v-if="isPercent(split.kind)" v-model="split.total" :min="0" :max="100" :step="0.01" class="w-full" />
          <UInputNumber v-else v-model="split.total" :min="0" :step="0.01" :increment="false" :decrement="false"
                        :format-options="{ style: 'currency', currency: 'BRL' }" locale="pt-BR" class="w-full" />
        </UFormField>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="split.open = false" />
          <UButton label="Dividir" :disabled="!split.total" @click="applySplit" />
        </div>
      </template>
    </UModal>
  </div>
</template>
