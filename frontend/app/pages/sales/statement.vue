<script setup lang="ts">
import type { components } from '~/types/api'

type Statement = components['schemas']['StatementOut']
definePageMeta({ permission: ['sales', 'view'] })

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const route = useRoute()
const router = useRouter()
const lookups = useLookups()
lookups.ensure('companies', 'salespeople', 'subgroups').catch(notifyError)

// Month = payment month (commissions of the previous month's sales), as on the commissions page
const monthItems = monthOptions()
const filters = reactive({
  salesperson: route.query.salesperson ? Number(route.query.salesperson) : undefined as number | undefined,
  month: String(route.query.month ?? today().slice(0, 7)),
})
watch(filters, f => router.replace({ query: { salesperson: f.salesperson, month: f.month } }))

const data = ref<Statement | null>(null)
const loading = ref(false)
async function load() {
  if (!filters.salesperson) return (data.value = null)
  loading.value = true
  try {
    data.value = await unwrap(api.GET('/api/commission/statement', {
      params: { query: { salesperson_id: filters.salesperson, month: `${filters.month}-01` } },
    }))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
watch(filters, load, { immediate: true })

const salary = computed(() => Number(data.value?.salary ?? 0))

// Public link: new token + password each time (the previous link stops working)
const share = reactive({ open: false, loading: false, url: '', password: '', expires: '' })
async function createShare() {
  share.loading = true
  try {
    const r = await unwrap(api.POST('/api/commission/statement/share', {
      body: { salesperson_id: filters.salesperson!, month: `${filters.month}-01` },
    }))
    Object.assign(share, { open: true, url: `${location.origin}/s/${r.token}`, password: r.password, expires: r.expires_at })
  } catch (e) {
    notifyError(e)
  } finally {
    share.loading = false
  }
}
const copy = (text: string) => navigator.clipboard.writeText(text).then(() => notifySuccess('Copiado'))

// Pay what is still open: fixed pay (one outflow) + pending commissions (one outflow per company)
const pendingCommissions = computed(() => (data.value?.commissions ?? []).filter(c => !c.payment_id))
const salaryOpen = computed(() => !!data.value && !data.value.salary_payment_id && salary.value > 0)
const canPay = computed(() => auth.can('sales', 'change') && auth.can('transactions', 'create'))
const subgroupItems = computed(() => (lookups.cache.value.subgroups ?? [])
  .filter(s => !INFLOW_GROUPS.includes(s.group) && s.group !== 'transfer')
  .map(s => ({ label: s.name, value: s.id!, description: lookups.groupLabel(s.group) })))
const findSubgroup = (re: RegExp) => (lookups.cache.value.subgroups ?? []).find(s => re.test(s.name))?.id ?? undefined
const pay = reactive({
  open: false, saving: false, date: today(),
  company_id: undefined as number | undefined,
  salary_subgroup_id: undefined as number | undefined,
  commission_subgroup_id: undefined as number | undefined,
})
function openPay() {
  pay.date = today()
  pay.company_id ??= lookups.cache.value.companies?.[0]?.id ?? undefined
  pay.salary_subgroup_id ??= findSubgroup(/sal[aá]rio|fixo|folha|pr[oó]-?labore/i)
  pay.commission_subgroup_id ??= findSubgroup(/comiss/i)
  pay.open = true
}
const payReady = computed(() => !!pay.date
  && (!salaryOpen.value || (pay.company_id && pay.salary_subgroup_id))
  && (!pendingCommissions.value.length || pay.commission_subgroup_id))
async function confirmPay() {
  pay.saving = true
  try {
    if (salaryOpen.value) {
      await unwrap(api.POST('/api/salary/pay', { body: {
        salesperson_id: filters.salesperson!, month: `${filters.month}-01`, date: pay.date,
        company_id: pay.company_id!, subgroup_id: pay.salary_subgroup_id!,
      } }))
    }
    if (pendingCommissions.value.length) {
      await unwrap(api.POST('/api/commission/pay', { body: {
        ids: pendingCommissions.value.map(c => c.id), date: pay.date, subgroup_id: pay.commission_subgroup_id!,
      } }))
    }
    notifySuccess('Pagamento lançado')
    pay.open = false
  } catch (e) {
    notifyError(e)
  } finally {
    pay.saving = false
    load()
  }
}
const openTotal = computed(() => (salaryOpen.value ? salary.value : 0)
  + pendingCommissions.value.reduce((s, c) => s + Number(c.amount), 0))
const printPage = () => window.print()
</script>

<template>
  <AppPage title="Demonstrativo">
    <template #actions>
      <UButton v-if="auth.can('sales', 'change')" label="Link público" icon="i-lucide-link" color="neutral" variant="outline"
               :disabled="!data" :loading="share.loading" @click="createShare" />
      <UButton label="Imprimir" icon="i-lucide-printer" color="neutral" variant="outline" :disabled="!data" @click="printPage" />
      <UButton v-if="canPay && openTotal > 0" :label="`Pagar ${formatMoney(openTotal)}`" icon="i-lucide-banknote" @click="openPay" />
    </template>
    <template #toolbar>
      <USelectMenu v-model="filters.salesperson" :items="lookups.options.salespeople.value" value-key="value"
                   placeholder="Profissional" class="w-56" />
      <USelect v-model="filters.month" :items="monthItems" class="w-32" aria-label="Mês de pagamento" />
    </template>

    <SalesStatementSheet v-if="data" :data="data" :loading="loading" />
    <p v-else-if="!filters.salesperson" class="text-sm text-dimmed">Selecione um profissional.</p>

    <UModal v-model:open="pay.open" :title="`Pagar ${formatMoney(openTotal)}`">
      <template #body>
        <div class="grid gap-3 sm:grid-cols-2">
          <UFormField label="Data do pagamento">
            <UInput v-model="pay.date" type="date" class="w-full" />
          </UFormField>
          <template v-if="salaryOpen">
            <UFormField label="Empresa do fixo">
              <USelectMenu v-model="pay.company_id" :items="lookups.options.companies.value" value-key="value" class="w-full" />
            </UFormField>
            <UFormField label="Subgrupo do fixo">
              <USelectMenu v-model="pay.salary_subgroup_id" :items="subgroupItems" value-key="value" class="w-full" />
            </UFormField>
          </template>
          <UFormField v-if="pendingCommissions.length" label="Subgrupo das comissões">
            <USelectMenu v-model="pay.commission_subgroup_id" :items="subgroupItems" value-key="value" class="w-full" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Cancelar" color="neutral" variant="ghost" @click="pay.open = false" />
          <UButton label="Pagar" :loading="pay.saving" :disabled="!payReady" @click="confirmPay" />
        </div>
      </template>
    </UModal>
    <UModal v-model:open="share.open" title="Link público">
      <template #body>
        <div class="flex flex-col gap-3">
          <UFormField label="Link">
            <UInput :model-value="share.url" readonly class="w-full">
              <template #trailing>
                <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar link" @click="copy(share.url)" />
              </template>
            </UInput>
          </UFormField>
          <UFormField label="Senha">
            <UInput :model-value="share.password" readonly class="w-full font-mono">
              <template #trailing>
                <UButton icon="i-lucide-copy" color="neutral" variant="link" size="sm" aria-label="Copiar senha" @click="copy(share.password)" />
              </template>
            </UInput>
          </UFormField>
          <p class="text-xs text-muted">Expira em {{ formatDate(share.expires) }}</p>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton label="Copiar link e senha" icon="i-lucide-copy" @click="copy(`${share.url}\nSenha: ${share.password}`)" />
        </div>
      </template>
    </UModal>
  </AppPage>
</template>
