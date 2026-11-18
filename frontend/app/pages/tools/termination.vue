<script setup lang="ts">
const state = reactive(structuredClone(TERMINATION_DEFAULTS))
const result = computed(() => calcTermination(state))
watch(() => state.planKey, key => { state.contracted = { ...PLANS[key]!.scope } })

const installments = ref(1)
const firstDue = ref('')
const message = ref('')
watch(() => terminationMessage(result.value, state, installments.value, firstDue.value), text => { message.value = text }, { immediate: true })

function reset() {
  Object.assign(state, structuredClone(TERMINATION_DEFAULTS))
  installments.value = 1
  firstDue.value = ''
}

const money = { step: 0.01, min: 0, increment: false, decrement: false, locale: 'pt-BR', formatOptions: { style: 'currency', currency: 'BRL' } } as const
const percent = { step: 1, min: 0, max: 100, increment: false, decrement: false } as const

const COUNTS = ['advisory', 'success', 'booklets', 'trafficMonths'] as const
const FLAGS = ['onboarding', 'scripts', 'group', 'community', 'lives', 'adp', 'crm', 'landing'] as const
const planItems = Object.entries(PLANS).map(([value, p]) => ({ label: p.label, value }))
const contractItems = computed(() => [
  { label: `Novo · multa ${formatMoney(state.fines.new)}`, value: 'new' },
  { label: `Antigo · multa ${formatMoney(state.fines.old)}`, value: 'old' },
])
const fineValue = computed(() => state.fines[state.contractType] * state.finePct / 100)
const today = new Date().toLocaleDateString('pt-BR')
const printPage = () => window.print()
</script>

<template>
  <AppPage title="Rescisão contratual">
    <template #actions>
      <UButton label="Novo cálculo" icon="i-lucide-rotate-ccw" color="neutral" variant="outline" @click="reset" />
    </template>

    <div class="grid items-start gap-4 lg:grid-cols-[1fr_26rem]">
      <div class="flex flex-col gap-4">
        <SPanel title="Cliente">
          <div class="grid gap-4 sm:grid-cols-2">
            <UFormField label="Razão social / nome" class="sm:col-span-2">
              <UInput v-model="state.client" class="w-full" />
            </UFormField>
            <UFormField label="CPF/CNPJ">
              <UInput v-model="state.document" class="w-full" />
            </UFormField>
            <UFormField label="Data da solicitação">
              <UInput v-model="state.requestDate" type="date" class="w-full" />
            </UFormField>
            <UFormField label="Solicitante" class="sm:col-span-2">
              <UInput v-model="state.requester" class="w-full" />
            </UFormField>
          </div>
        </SPanel>

        <SPanel title="Contrato">
          <div class="grid gap-4 sm:grid-cols-2">
            <UFormField label="Valor total">
              <UInputNumber v-model="state.total" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Valor já pago">
              <UInputNumber v-model="state.paid" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Versão do contrato">
              <USelect v-model="state.contractType" :items="contractItems" class="w-full" />
            </UFormField>
            <div class="flex flex-col gap-2">
              <USwitch v-model="state.chargeFine" label="Cobrar multa" />
              <div v-if="state.chargeFine" class="flex items-center gap-3">
                <USlider v-model="state.finePct" :min="0" :max="100" :step="5" class="flex-1" />
                <span class="w-32 text-right text-sm tabular text-highlighted">{{ state.finePct }}% · {{ formatMoney(fineValue) }}</span>
              </div>
            </div>
          </div>
        </SPanel>

        <SPanel title="Plano contratado">
          <template #actions>
            <USelect v-model="state.planKey" :items="planItems" size="sm" class="w-40" />
          </template>
          <div class="grid gap-4 sm:grid-cols-4">
            <UFormField v-for="key in COUNTS" :key="key" :label="SCOPE_LABELS[key]">
              <UInputNumber v-model="state.contracted[key]" :min="0" class="w-full" />
            </UFormField>
          </div>
          <div class="mt-4 grid gap-2 sm:grid-cols-2">
            <UCheckbox v-for="key in FLAGS" :key="key" v-model="state.contracted[key]" :label="SCOPE_LABELS[key]" />
          </div>
        </SPanel>

        <SPanel title="Entregue até o cancelamento">
          <div class="grid gap-4 sm:grid-cols-4">
            <template v-for="key in COUNTS" :key="key">
              <UFormField v-if="state.contracted[key]" :label="`${SCOPE_LABELS[key]} (de ${state.contracted[key]})`">
                <UInputNumber v-model="state.delivered[key]" :min="0" :max="state.contracted[key]" class="w-full" />
              </UFormField>
            </template>
          </div>
          <div class="mt-4 grid gap-2 sm:grid-cols-2">
            <template v-for="key in FLAGS" :key="key">
              <UCheckbox v-if="state.contracted[key]" v-model="state.delivered[key]" :label="SCOPE_LABELS[key]" />
            </template>
          </div>
        </SPanel>

        <SPanel title="Parâmetros">
          <div class="grid gap-4 sm:grid-cols-4">
            <UFormField label="Curso ADP">
              <UInputNumber v-model="state.prices.adp" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="CRM">
              <UInputNumber v-model="state.prices.crm" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Landing page">
              <UInputNumber v-model="state.prices.landing" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Tráfego por mês">
              <UInputNumber v-model="state.prices.trafficMonthly" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Multa contrato novo">
              <UInputNumber v-model="state.fines.new" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Multa contrato antigo">
              <UInputNumber v-model="state.fines.old" v-bind="money" class="w-full" />
            </UFormField>
          </div>
          <div class="mt-4 grid gap-4 sm:grid-cols-4">
            <UFormField label="Peso assessorias (%)">
              <UInputNumber v-model="state.weights.advisory" v-bind="percent" class="w-full" />
            </UFormField>
            <UFormField label="Peso Sucesso do Cliente (%)">
              <UInputNumber v-model="state.weights.success" v-bind="percent" class="w-full" />
            </UFormField>
            <UFormField label="Peso scripts (%)">
              <UInputNumber v-model="state.weights.scripts" v-bind="percent" class="w-full" />
            </UFormField>
            <UFormField label="Peso apostilas (%)">
              <UInputNumber v-model="state.weights.booklets" v-bind="percent" class="w-full" />
            </UFormField>
          </div>
        </SPanel>
      </div>

      <div class="flex flex-col gap-4 lg:sticky lg:top-0">
        <SPanel title="Resultado">
          <template #actions>
            <UButton icon="i-lucide-printer" color="neutral" variant="ghost" size="sm" aria-label="Imprimir" @click="printPage" />
          </template>
          <p class="text-sm text-muted">Saldo devedor final</p>
          <p class="font-display text-3xl font-semibold tracking-tight tabular text-highlighted">{{ formatMoney(result.due) }}</p>

          <table class="mt-4 w-full text-sm tabular">
            <tbody>
              <tr class="border-b border-muted"><td class="py-1.5 text-toned">Serviços entregues</td><td class="py-1.5 text-right">{{ formatMoney(result.delivered) }}</td></tr>
              <tr class="border-b border-muted"><td class="py-1.5 text-toned">Multa</td><td class="py-1.5 text-right">{{ formatMoney(result.fine) }}</td></tr>
              <tr class="border-b border-muted"><td class="py-1.5 text-highlighted">Total devido</td><td class="py-1.5 text-right text-highlighted">{{ formatMoney(result.delivered + result.fine) }}</td></tr>
              <tr class="border-b border-muted"><td class="py-1.5 text-toned">Já pago</td><td class="py-1.5 text-right text-success">− {{ formatMoney(result.paid) }}</td></tr>
              <tr><td class="pt-2 font-semibold text-highlighted">Saldo devedor final</td><td class="pt-2 text-right font-semibold text-highlighted">{{ formatMoney(result.due) }}</td></tr>
            </tbody>
          </table>

          <div class="mt-4 grid grid-cols-2 gap-3">
            <UFormField label="Parcelas">
              <UInputNumber v-model="installments" :min="1" :max="36" class="w-full" />
            </UFormField>
            <UFormField label="1º vencimento">
              <UInput v-model="firstDue" type="date" class="w-full" />
            </UFormField>
          </div>
          <p class="mt-2 text-sm text-toned tabular">{{ installments }}x de {{ formatMoney(result.due / installments) }}</p>
        </SPanel>

        <SPanel title="Entregáveis">
          <table class="w-full text-sm tabular">
            <tbody>
              <tr v-for="(r, i) in result.rows" :key="i" class="border-b border-muted last:border-0">
                <td class="py-1.5">
                  <UIcon :name="r.delivered ? 'i-lucide-check' : 'i-lucide-x'" class="me-1.5 size-3.5 align-[-2px]"
                         :class="r.delivered ? 'text-success' : 'text-error'" />{{ r.label }}
                </td>
                <td class="py-1.5 text-right whitespace-nowrap" :class="r.delivered ? '' : 'text-dimmed'">
                  {{ r.value === null ? 'Incluso' : formatMoney(r.value) }}
                </td>
              </tr>
            </tbody>
          </table>
        </SPanel>
      </div>
    </div>

    <SPanel title="Conclusão">
      <UTextarea v-model="message" :rows="10" autoresize class="w-full" />
    </SPanel>

    <Teleport to="body">
      <div class="s-print hidden print:block">
        <h1>Relatório de rescisão contratual</h1>
        <h2>Dados do cliente</h2>
        <table>
          <tbody>
            <tr><td>Empresa</td><td>{{ state.client || '—' }}</td></tr>
            <tr><td>CPF/CNPJ</td><td>{{ state.document || '—' }}</td></tr>
            <tr><td>Solicitante</td><td>{{ state.requester || '—' }}</td></tr>
            <tr><td>Data da solicitação</td><td>{{ formatDate(state.requestDate) }}</td></tr>
            <tr><td>Plano</td><td>{{ PLANS[state.planKey]?.label }} · contrato {{ state.contractType === 'new' ? 'novo' : 'antigo' }}</td></tr>
          </tbody>
        </table>
        <h2>Valores do contrato</h2>
        <table>
          <tbody>
            <tr><td>Valor total</td><td>{{ formatMoney(result.total) }}</td></tr>
            <tr><td>Valor pago</td><td>{{ formatMoney(result.paid) }}</td></tr>
            <tr><td>Saldo devedor</td><td>{{ formatMoney(result.balance) }}</td></tr>
          </tbody>
        </table>
        <h2>Entregáveis</h2>
        <table>
          <tbody>
            <tr v-for="(r, i) in result.rows" :key="i">
              <td>{{ r.delivered ? '✓' : '✗' }} {{ r.label }}<small>{{ r.delivered ? 'Entregue' : 'Não entregue' }}</small></td>
              <td>{{ r.value === null ? 'Incluso' : formatMoney(r.value) }}</td>
            </tr>
            <tr><td><b>Total entregue</b></td><td><b>{{ formatMoney(result.delivered) }}</b></td></tr>
            <tr><td><b>Total não entregue</b></td><td><b>{{ formatMoney(result.notDelivered) }}</b></td></tr>
          </tbody>
        </table>
        <h2>Resumo financeiro</h2>
        <table>
          <tbody>
            <tr><td>Serviços entregues</td><td>{{ formatMoney(result.delivered) }}</td></tr>
            <tr>
              <td>{{ !state.chargeFine ? 'Multa dispensada' : state.finePct < 100 ? `Multa contratual (${state.finePct}% cobrado)` : 'Multa contratual' }}</td>
              <td>{{ formatMoney(result.fine) }}</td>
            </tr>
            <tr><td>Total devido</td><td>{{ formatMoney(result.delivered + result.fine) }}</td></tr>
            <tr><td>Valor pago pelo cliente</td><td>− {{ formatMoney(result.paid) }}</td></tr>
            <tr class="total"><td>Saldo devedor final</td><td>{{ formatMoney(result.due) }}</td></tr>
          </tbody>
        </table>
        <h2>Conclusão</h2>
        <p class="text">{{ message }}</p>
        <footer>O Henriquecedor · gerado em {{ today }}</footer>
      </div>
    </Teleport>
  </AppPage>
</template>
