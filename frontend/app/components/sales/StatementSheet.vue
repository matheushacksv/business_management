<script setup lang="ts">
// Monthly statement of one professional (fixed pay + commissions), on screen and printable.
// Used by the internal page and the public link.
import type { components } from '~/types/api'

type Commission = components['schemas']['CommissionOut']
const props = defineProps<{ data: components['schemas']['StatementOut']; loading?: boolean }>()

const monthLabel = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(0, 4)}`
const salary = computed(() => Number(props.data.salary ?? 0))
const groups = computed(() => {
  const map = new Map<string, Commission[]>()
  for (const c of props.data.commissions ?? []) map.set(c.kind, [...(map.get(c.kind) ?? []), c])
  return [...map].map(([kind, rows]) => ({ kind, rows, total: rows.reduce((s, c) => s + Number(c.amount), 0) }))
})
const commissionsTotal = computed(() => groups.value.reduce((s, g) => s + g.total, 0))
const total = computed(() => salary.value + commissionsTotal.value)
const rule = (c: Commission) => c.percent != null
  ? `${Number(c.percent).toLocaleString('pt-BR')}% de ${formatMoney(c.sale_amount)} − ${Number(c.tax_rate).toLocaleString('pt-BR')}% imp.`
  : 'valor fixo'

</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="grid gap-3 sm:grid-cols-3">
      <SStat label="Fixo" :value="formatMoney(salary)" :loading="loading" icon="i-lucide-wallet" />
      <SStat :label="`Comissões · vendas de ${monthLabel(data.sales_month)}`" :value="formatMoney(commissionsTotal)"
             :loading="loading" icon="i-lucide-hand-coins" />
      <SStat label="Total a receber" :value="formatMoney(total)" tone="primary" :loading="loading" icon="i-lucide-sigma" />
    </div>

    <SPanel :title="`${data.salesperson.name} · ${monthLabel(data.month)}`">
      <table class="w-full text-sm tabular">
        <tbody>
          <tr class="border-b border-default">
            <td class="py-2 font-medium text-highlighted">Fixo</td>
            <td class="py-2" />
            <td class="py-2 text-right">
              <UBadge v-if="salary > 0" :label="data.salary_payment_id ? `Pago ${formatDate(data.salary_paid_on)}` : 'A pagar'"
                      :color="data.salary_payment_id ? 'success' : 'warning'" variant="subtle" size="sm" />
            </td>
            <td class="py-2 text-right text-highlighted">{{ formatMoney(salary) }}</td>
          </tr>
          <template v-for="g in groups" :key="g.kind">
            <tr class="border-b border-default">
              <td colspan="3" class="pt-4 pb-2 font-medium text-highlighted">{{ LABELS.commissionKind[g.kind] }}</td>
              <td class="pt-4 pb-2 text-right text-highlighted">{{ formatMoney(g.total) }}</td>
            </tr>
            <tr v-for="c in g.rows" :key="c.id" class="border-b border-muted">
              <td class="py-1.5 pl-3">
                <p class="text-toned">{{ c.contact_name ?? `Venda #${c.sale_id}` }}{{ c.description ? ` · ${c.description}` : '' }}</p>
                <p class="text-xs text-dimmed">{{ formatDate(c.sale_date) }} · {{ c.company_name }}</p>
              </td>
              <td class="py-1.5 text-right text-xs text-muted">{{ rule(c) }}</td>
              <td class="py-1.5 text-right">
                <UBadge :label="c.payment_id ? `Paga ${formatDate(c.paid_on)}` : 'A pagar'"
                        :color="c.payment_id ? 'success' : 'warning'" variant="subtle" size="sm" />
              </td>
              <td class="py-1.5 text-right">{{ formatMoney(c.amount) }}</td>
            </tr>
          </template>
          <tr>
            <td colspan="3" class="pt-4 font-semibold text-highlighted">Total</td>
            <td class="pt-4 text-right font-semibold text-highlighted">{{ formatMoney(total) }}</td>
          </tr>
        </tbody>
      </table>
    </SPanel>

    <Teleport to="body">
      <div class="s-print hidden print:block">
        <h1>Demonstrativo · {{ data.salesperson.name }}</h1>
        <p>Pagamento {{ monthLabel(data.month) }} · vendas de {{ monthLabel(data.sales_month) }}</p>
        <table>
          <tbody>
            <tr><td><b>Fixo</b></td><td><b>{{ formatMoney(salary) }}</b></td></tr>
          </tbody>
        </table>
        <template v-for="g in groups" :key="g.kind">
          <h2>{{ LABELS.commissionKind[g.kind] }}</h2>
          <table>
            <tbody>
              <tr v-for="c in g.rows" :key="c.id">
                <td>{{ c.contact_name ?? `Venda #${c.sale_id}` }}{{ c.description ? ` · ${c.description}` : '' }}<small>{{ formatDate(c.sale_date) }} · {{ c.company_name }} · {{ rule(c) }}</small></td>
                <td>{{ formatMoney(c.amount) }}</td>
              </tr>
              <tr><td><b>Subtotal</b></td><td><b>{{ formatMoney(g.total) }}</b></td></tr>
            </tbody>
          </table>
        </template>
        <table>
          <tbody>
            <tr class="total"><td>Total a receber</td><td>{{ formatMoney(total) }}</td></tr>
          </tbody>
        </table>
        <footer>O Henriquecedor · emitido em {{ new Date().toLocaleDateString('pt-BR') }}</footer>
      </div>
    </Teleport>
  </div>
</template>
