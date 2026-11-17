<script setup lang="ts">
import type { components } from '~/types/api'

type Case = components['schemas']['CaseOut']
type Comment = components['schemas']['CommentOut']
type Transaction = components['schemas']['TransactionOut']
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ caseId: number | null }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const canChange = computed(() => auth.can('legal', 'change'))

const item = ref<Case | null>(null)
const comments = ref<Comment[]>([])
const installments = ref<Transaction[]>([])
const tab = ref('summary')
const editing = ref(false)
const tabs = [
  { label: 'Resumo', value: 'summary', icon: 'i-lucide-file-text' },
  { label: 'Andamento', value: 'comments', icon: 'i-lucide-messages-square' },
  { label: 'Parcelas', value: 'installments', icon: 'i-lucide-calendar-range' },
]

async function load() {
  if (!props.caseId) return
  const path = { case_id: props.caseId }
  try {
    ;[item.value, comments.value, installments.value] = await Promise.all([
      unwrap(api.GET('/api/collection-case/{case_id}', { params: { path } })),
      unwrap(api.GET('/api/collection-case/{case_id}/comments', { params: { path } })),
      unwrap(api.GET('/api/collection-case/{case_id}/transactions', { params: { path } })),
    ])
  } catch (e) {
    notifyError(e)
  }
}
watch(() => [props.caseId, open.value], () => {
  if (open.value) { item.value = null; tab.value = 'summary'; editing.value = false; load() }
}, { immediate: true })

const text = ref('')
const sending = ref(false)
async function addComment() {
  if (!text.value.trim() || !item.value) return
  sending.value = true
  try {
    await unwrap(api.POST('/api/collection-case/{case_id}/comments', {
      params: { path: { case_id: item.value.id! } }, body: { text: text.value },
    }))
    text.value = ''
    await load()
    emit('changed')
  } catch (e) {
    notifyError(e)
  } finally {
    sending.value = false
  }
}

async function saved() {
  editing.value = false
  await load()
  emit('changed')
}

async function remove() {
  if (!item.value) return
  const ok = await confirm({
    title: 'Excluir caso de cobrança?',
    description: 'As parcelas vinculadas continuam lançadas e voltam para a DRE e o fluxo de caixa.',
    confirmLabel: 'Excluir', color: 'error', icon: 'i-lucide-trash-2',
  })
  if (!ok) return
  try {
    await unwrap(api.DELETE('/api/collection-case/{case_id}', { params: { path: { case_id: item.value.id! } } }))
    notifySuccess('Caso excluído')
    open.value = false
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}

// Imported cases come without the required fields: flag it
const incomplete = computed(() => !!item.value && (!item.value.client_company || !item.value.contact_info
  || !item.value.delivered || !item.value.summary || !item.value.drive_link
  || item.value.proposal_amount == null || item.value.paid_amount == null))
</script>

<template>
  <USlideover v-model:open="open" :title="item?.contact_name ?? 'Caso de cobrança'"
              :description="item ? `${LABELS.caseStage[item.stage]} · ${item.company_name}` : undefined"
              :ui="{ content: 'max-w-2xl' }">
    <template #body>
      <USkeleton v-if="!item" class="h-40 w-full" />
      <div v-else class="space-y-5">
        <div class="s-panel grid grid-cols-2 gap-3 p-4 text-xs sm:grid-cols-4">
          <div><p class="text-dimmed">Devido (em aberto)</p><p class="font-display text-lg text-error tabular">{{ formatMoney(item.open_amount) }}</p></div>
          <div><p class="text-dimmed">Recebido (parcelas)</p><p class="font-display text-lg text-success tabular">{{ formatMoney(item.received_amount) }}</p></div>
          <div><p class="text-dimmed">Valor da proposta</p><p class="text-highlighted tabular">{{ item.proposal_amount != null ? formatMoney(item.proposal_amount) : '—' }}</p></div>
          <div><p class="text-dimmed">Pago pelo cliente</p><p class="text-highlighted tabular">{{ item.paid_amount != null ? formatMoney(item.paid_amount) : '—' }}</p></div>
        </div>

        <UAlert v-if="incomplete && !editing" color="warning" variant="subtle" icon="i-lucide-triangle-alert"
                title="Caso incompleto" description="Preencha os campos obrigatórios (veio da planilha)." />

        <UTabs v-model="tab" :items="tabs" :content="false" size="sm" class="w-full" />

        <template v-if="tab === 'summary'">
          <LegalForm v-if="editing" :item="item" @saved="saved" @cancel="editing = false" />
          <template v-else>
            <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div>
                <dt class="text-xs text-dimmed">Cliente</dt>
                <dd><NuxtLink :to="`/registers/contacts/${item.contact_id}`" class="text-primary hover:underline">{{ item.contact_name }}</NuxtLink></dd>
              </div>
              <div><dt class="text-xs text-dimmed">Empresa</dt><dd>{{ item.client_company || '—' }}</dd></div>
              <div><dt class="text-xs text-dimmed">Contato</dt><dd>{{ item.contact_info || '—' }}</dd></div>
              <div>
                <dt class="text-xs text-dimmed">Link do drive</dt>
                <dd><a v-if="item.drive_link" :href="item.drive_link" target="_blank" rel="noopener" class="text-primary hover:underline">Abrir pasta</a><span v-else>—</span></dd>
              </div>
              <div class="col-span-2"><dt class="text-xs text-dimmed">O que foi entregue</dt><dd class="whitespace-pre-line">{{ item.delivered || '—' }}</dd></div>
              <div class="col-span-2"><dt class="text-xs text-dimmed">Resumo da situação</dt><dd class="whitespace-pre-line">{{ item.summary || '—' }}</dd></div>
              <div v-if="item.agreement" class="col-span-2"><dt class="text-xs text-dimmed">Acordo ou sentença</dt><dd class="whitespace-pre-line">{{ item.agreement }}</dd></div>
            </dl>
            <div class="flex gap-2">
              <UButton v-if="canChange" label="Editar" icon="i-lucide-pencil" @click="editing = true" />
              <UButton v-if="auth.can('legal', 'delete')" label="Excluir" icon="i-lucide-trash-2" color="error" variant="ghost" @click="remove" />
            </div>
          </template>
        </template>

        <template v-else-if="tab === 'comments'">
          <form class="flex flex-col gap-2" @submit.prevent="addComment">
            <UTextarea v-model="text" :rows="2" autoresize placeholder="Comentário ou observação do andamento…" class="w-full" />
            <UButton type="submit" label="Comentar" icon="i-lucide-send" :loading="sending" :disabled="!text.trim()" class="self-end" />
          </form>
          <ul class="space-y-3">
            <li v-for="c in comments" :key="c.id!" class="s-panel p-3 text-sm">
              <p class="mb-1 text-xs text-dimmed">{{ c.author_name ?? 'Sistema' }} · {{ new Date(c.created_at!).toLocaleString('pt-BR') }}</p>
              <p class="whitespace-pre-line">{{ c.text }}</p>
            </li>
          </ul>
        </template>

        <template v-else>
          <ul v-if="installments.length" class="divide-y divide-muted rounded-xl ring ring-default">
            <li v-for="t in installments" :key="t.id!" class="flex items-center gap-3 px-3 py-2 text-sm">
              <span class="w-24 text-muted tabular">{{ formatDate(t.date) }}</span>
              <span class="flex-1 truncate">{{ t.reference || t.subgroup_name }}</span>
              <SStatusBadge kind="status" :value="t.status" />
              <SMoney :value="t.amount" class="w-28 text-right" />
            </li>
          </ul>
          <p v-else class="text-sm text-dimmed">Nenhuma parcela vinculada.</p>
          <p class="text-xs text-dimmed">Parcelas previstas ficam fora da DRE e do fluxo de caixa. Ao marcar como realizada (em Lançamentos), voltam a contar.</p>
        </template>
      </div>
    </template>
  </USlideover>
</template>
