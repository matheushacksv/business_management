<script setup lang="ts">
const state = reactive(structuredClone(PROFIT_DEFAULTS))
const result = computed(() => calcProfit(state))
const reset = () => Object.assign(state, structuredClone(PROFIT_DEFAULTS))

const money = { step: 0.01, min: 0, increment: false, decrement: false, locale: 'pt-BR', formatOptions: { style: 'currency', currency: 'BRL' } } as const
const percent = { step: 0.01, min: 0, max: 100, increment: false, decrement: false, locale: 'pt-BR', formatOptions: { maximumFractionDigits: 2 } } as const

const { notifySuccess } = useApi()
function copy() {
  const r = result.value
  const lines = r.lines.flatMap((l, i) => [
    `(-) ${l.label} [${l.detail}]: ${formatMoney(l.value)}`,
    ...(i === 0 ? [`Valor após imposto: ${formatMoney(r.afterTax)}`] : []),
  ])
  navigator.clipboard.writeText([
    'LUCRO LÍQUIDO DO CONTRATO', '', `Valor bruto: ${formatMoney(r.gross)}`, ...lines, '',
    `Total de descontos: ${formatMoney(r.costs)}`, `VALOR LÍQUIDO: ${formatMoney(r.net)} (${formatPercent(r.margin)})`,
  ].join('\n')).then(() => notifySuccess('Resumo copiado'))
}
const today = new Date().toLocaleDateString('pt-BR')
const printPage = () => window.print()
</script>

<template>
  <AppPage title="Lucro do contrato">
    <template #actions>
      <UButton label="Novo cálculo" icon="i-lucide-rotate-ccw" color="neutral" variant="outline" @click="reset" />
    </template>

    <div class="grid items-start gap-4 lg:grid-cols-[1fr_24rem]">
      <div class="flex flex-col gap-4">
        <SPanel title="Contrato">
          <div class="grid gap-4 sm:grid-cols-2">
            <UFormField label="Valor bruto">
              <UInputNumber v-model="state.gross" v-bind="money" class="w-full" />
            </UFormField>
            <UFormField label="Imposto (%)">
              <UInputNumber v-model="state.taxPct" v-bind="percent" class="w-full" />
            </UFormField>
          </div>
        </SPanel>

        <SPanel title="Equipe e comissões">
          <div class="flex flex-col gap-4">
            <div class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state.scheduling.on" label="Agendamento" class="sm:pb-2" />
              <UFormField v-if="state.scheduling.on" label="Valor">
                <UInputNumber v-model="state.scheduling.value" v-bind="money" class="w-full" />
              </UFormField>
            </div>
            <div v-for="[key, label] in ([['advisor', 'Assessor'], ['closer', 'Closer']] as const)" :key="key"
                 class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state[key].on" :label="label" class="sm:pb-2" />
              <template v-if="state[key].on">
                <UFormField label="Comissão após imposto (%)">
                  <UInputNumber v-model="state[key].pct" v-bind="percent" class="w-full" />
                </UFormField>
                <UFormField label="Nome">
                  <UInput v-model="state[key].name" class="w-full" />
                </UFormField>
              </template>
            </div>
          </div>
        </SPanel>

        <SPanel title="Serviços incluídos">
          <div class="flex flex-col gap-4">
            <div class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state.crm.on" label="Implementação de CRM" class="sm:pb-2" />
              <UFormField v-if="state.crm.on" label="Custo">
                <UInputNumber v-model="state.crm.value" v-bind="money" class="w-full" />
              </UFormField>
            </div>
            <div class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state.traffic.on" label="Tráfego pago" class="sm:pb-2" />
              <template v-if="state.traffic.on">
                <UFormField label="Meses">
                  <UInputNumber v-model="state.traffic.months" :min="1" class="w-full" />
                </UFormField>
                <UFormField label="Custo por mês">
                  <UInputNumber v-model="state.traffic.monthly" v-bind="money" class="w-full" />
                </UFormField>
              </template>
            </div>
            <div class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state.success.on" label="Sucesso do Cliente" class="sm:pb-2" />
              <UFormField v-if="state.success.on" label="Custo">
                <UInputNumber v-model="state.success.value" v-bind="money" class="w-full" />
              </UFormField>
            </div>
          </div>
        </SPanel>

        <SPanel title="Indicação">
          <div class="flex flex-col gap-4">
            <USwitch v-model="state.referral.on" label="Veio de indicação" />
            <div v-if="state.referral.on" class="grid gap-4 sm:grid-cols-3">
              <UFormField label="Bonificação">
                <USelect v-model="state.referral.kind" :items="[{ label: 'Porcentagem', value: 'pct' }, { label: 'Valor fixo / brinde', value: 'fixed' }]" class="w-full" />
              </UFormField>
              <template v-if="state.referral.kind === 'pct'">
                <UFormField label="Percentual (%)">
                  <UInputNumber v-model="state.referral.pct" v-bind="percent" class="w-full" />
                </UFormField>
                <UFormField label="Sobre">
                  <USelect v-model="state.referral.base" :items="[{ label: 'Valor bruto', value: 'gross' }, { label: 'Valor após imposto', value: 'net' }]" class="w-full" />
                </UFormField>
              </template>
              <template v-else>
                <UFormField label="Valor">
                  <UInputNumber v-model="state.referral.value" v-bind="money" class="w-full" />
                </UFormField>
                <UFormField label="Descrição">
                  <UInput v-model="state.referral.description" class="w-full" />
                </UFormField>
              </template>
              <UFormField label="Quem indicou">
                <UInput v-model="state.referral.name" class="w-full" />
              </UFormField>
            </div>
          </div>
        </SPanel>

        <SPanel title="Aquisição e estrutura">
          <div class="flex flex-col gap-4">
            <div class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state.cac.on" label="CAC" class="sm:pb-2" />
              <UFormField v-if="state.cac.on" label="CAC por cliente">
                <UInputNumber v-model="state.cac.value" v-bind="money" class="w-full" />
              </UFormField>
            </div>
            <div class="grid items-end gap-4 sm:grid-cols-3">
              <USwitch v-model="state.overhead.on" label="Rateio da estrutura" class="sm:pb-2" />
              <template v-if="state.overhead.on">
                <UFormField label="Forma">
                  <USelect v-model="state.overhead.kind" :items="[{ label: '% do bruto', value: 'pct' }, { label: 'Valor fixo', value: 'fixed' }]" class="w-full" />
                </UFormField>
                <UFormField v-if="state.overhead.kind === 'pct'" label="Percentual (%)">
                  <UInputNumber v-model="state.overhead.pct" v-bind="percent" class="w-full" />
                </UFormField>
                <UFormField v-else label="Valor">
                  <UInputNumber v-model="state.overhead.value" v-bind="money" class="w-full" />
                </UFormField>
              </template>
            </div>
          </div>
        </SPanel>

        <SPanel title="Outros custos">
          <template #actions>
            <UButton label="Adicionar" icon="i-lucide-plus" size="sm" color="neutral" variant="outline"
                     @click="state.others.push({ description: '', value: 0 })" />
          </template>
          <div class="flex flex-col gap-2">
            <div v-for="(o, i) in state.others" :key="i" class="flex gap-2">
              <UInput v-model="o.description" placeholder="Descrição" class="flex-1" />
              <UInputNumber v-model="o.value" v-bind="money" class="w-40" />
              <UButton icon="i-lucide-x" color="neutral" variant="ghost" aria-label="Remover" @click="state.others.splice(i, 1)" />
            </div>
          </div>
        </SPanel>
      </div>

      <SPanel title="Resultado" class="lg:sticky lg:top-0">
        <template #actions>
          <div class="flex gap-1">
            <UButton icon="i-lucide-copy" color="neutral" variant="ghost" size="sm" aria-label="Copiar resumo" @click="copy" />
            <UButton icon="i-lucide-printer" color="neutral" variant="ghost" size="sm" aria-label="Imprimir" @click="printPage" />
          </div>
        </template>
        <p class="text-sm text-muted">Valor líquido</p>
        <p class="font-display text-3xl font-semibold tracking-tight tabular" :class="result.net < 0 ? 'text-error' : 'text-success'">
          {{ formatMoney(result.net) }}
        </p>
        <p class="text-sm text-muted tabular">{{ formatPercent(result.margin) }} do bruto</p>

        <table class="mt-4 w-full text-sm tabular">
          <tbody>
            <tr class="border-b border-default">
              <td class="py-2 text-highlighted">Valor bruto</td>
              <td class="py-2 text-right text-highlighted">{{ formatMoney(result.gross) }}</td>
            </tr>
            <template v-for="(l, i) in result.lines" :key="i">
              <tr class="border-b border-muted">
                <td class="py-1.5">
                  <p class="text-toned">(−) {{ l.label }}</p>
                  <p class="text-xs text-dimmed">{{ l.detail }}</p>
                </td>
                <td class="py-1.5 text-right text-error whitespace-nowrap">− {{ formatMoney(l.value) }}</td>
              </tr>
              <tr v-if="i === 0" class="border-b border-default">
                <td class="py-2 text-highlighted">Após imposto</td>
                <td class="py-2 text-right text-highlighted">{{ formatMoney(result.afterTax) }}</td>
              </tr>
            </template>
            <tr>
              <td class="pt-3 font-semibold text-highlighted">Total de descontos</td>
              <td class="pt-3 text-right font-semibold text-error">{{ formatMoney(result.costs) }}</td>
            </tr>
          </tbody>
        </table>
      </SPanel>
    </div>

    <Teleport to="body">
      <div class="s-print hidden print:block">
        <h1>Lucro líquido do contrato</h1>
        <table>
          <tbody>
            <tr><td>Valor bruto</td><td>{{ formatMoney(result.gross) }}</td></tr>
            <template v-for="(l, i) in result.lines" :key="i">
              <tr><td>(−) {{ l.label }}<small>{{ l.detail }}</small></td><td>− {{ formatMoney(l.value) }}</td></tr>
              <tr v-if="i === 0"><td><b>Valor após imposto</b></td><td><b>{{ formatMoney(result.afterTax) }}</b></td></tr>
            </template>
            <tr><td><b>Total de descontos</b></td><td><b>{{ formatMoney(result.costs) }}</b></td></tr>
            <tr class="total"><td>Valor líquido ({{ formatPercent(result.margin) }})</td><td>{{ formatMoney(result.net) }}</td></tr>
          </tbody>
        </table>
        <footer>O Henriquecedor · {{ today }}</footer>
      </div>
    </Teleport>
  </AppPage>
</template>
