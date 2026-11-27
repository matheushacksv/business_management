<script setup lang="ts">
import type { components } from '~/types/api'

type Cadence = components['schemas']['CadenceOut']
type Step = components['schemas']['StepIO']
definePageMeta({ permission: ['dunning', 'view'] })
const { api, unwrap, notifyError, notifySuccess } = useApi()
const auth = useAuth()
const confirm = useConfirm()
const canChange = computed(() => auth.can('dunning', 'change'))
const { stages } = useDunning()

// Installments due before this date stay out of the funnel
const startDate = ref('')
let config = {} as { critical_days: number, attention_days: number, legal_critical: boolean }
unwrap(api.GET('/api/dunning/config')).then((c) => {
  startDate.value = c.start_date ?? ''
  config = c
}).catch(notifyError)
async function saveStart() {
  try {
    await unwrap(api.PUT('/api/dunning/config', { body: { ...config, start_date: startDate.value || null } }))
    notifySuccess('Data de início salva')
  } catch (e) {
    notifyError(e)
  }
}

// One cadence per stage; its steps run one at a time (next one created when the previous is done)
const cadences = ref<Cadence[]>([])
const loading = ref(false)
async function load() {
  loading.value = true
  try {
    cadences.value = await unwrap(api.GET('/api/dunning/cadence'))
  } catch (e) {
    notifyError(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

const kindItems = Object.entries(DUNNING_LABELS.activityKind).map(([value, label]) => ({ label, value }))
const stageItems = computed(() => stages.value.map(s => ({ label: s.name, value: s.id })))
const after = (s: Step, i: number) => s.interval_days === 0
  ? (i === 0 ? 'ao entrar na etapa' : 'no mesmo dia')
  : `${s.interval_days} dia(s) ${i === 0 ? 'após entrar na etapa' : 'após o anterior'}`

const newStep = (): Step => ({ id: null, kind: 'message', title: '', template: '', interval_days: 0, active: true })
const editor = reactive({ open: false, saving: false, id: null as number | null, name: '', stage_id: undefined as number | undefined,
  skip_weekends: true, skip_holidays: true, active: true, steps: [] as Step[] })
function edit(c?: Cadence) {
  Object.assign(editor, c
    ? { open: true, id: c.id, name: c.name, stage_id: c.stage_id, skip_weekends: c.skip_weekends, skip_holidays: c.skip_holidays,
        active: c.active, steps: c.steps.map(s => ({ ...s })) }
    : { open: true, id: null, name: '', stage_id: undefined, skip_weekends: true, skip_holidays: true, active: true, steps: [newStep()] })
}
function moveStep(i: number, to: number) {
  const [step] = editor.steps.splice(i, 1)
  editor.steps.splice(to, 0, step!)
}
const ready = computed(() => !!editor.name.trim() && !!editor.stage_id && editor.steps.length > 0 && editor.steps.every(s => s.title.trim()))
async function save() {
  editor.saving = true
  const body = { name: editor.name, stage_id: editor.stage_id!, skip_weekends: editor.skip_weekends, skip_holidays: editor.skip_holidays,
    active: editor.active, steps: editor.steps }
  try {
    await unwrap(editor.id
      ? api.PUT('/api/dunning/cadence/{cadence_id}', { params: { path: { cadence_id: editor.id } }, body })
      : api.POST('/api/dunning/cadence', { body }))
    notifySuccess('Cadência salva')
    editor.open = false
    await load()
  } catch (e) {
    notifyError(e)
  } finally {
    editor.saving = false
  }
}
async function remove() {
  if (!await confirm({ title: 'Excluir cadência?', description: 'Os cards dessa etapa deixam de receber atividades automáticas.', confirmLabel: 'Excluir', color: 'error' })) return
  try {
    await unwrap(api.DELETE('/api/dunning/cadence/{cadence_id}', { params: { path: { cadence_id: editor.id! } } }))
    editor.open = false
    await load()
  } catch (e) {
    notifyError(e)
  }
}
</script>

<template>
  <AppPage title="Configurar cobrança" tabs="dunning">
    <template #actions>
      <UFormField label="Cobrar atrasos a partir de" orientation="horizontal" class="items-center">
        <UInput v-model="startDate" type="date" :disabled="!canChange" class="w-40" @change="saveStart" />
      </UFormField>
      <UButton v-if="canChange" label="Nova cadência" icon="i-lucide-plus" class="rounded-full" @click="edit()" />
    </template>

    <div class="grid gap-4 lg:grid-cols-2" :class="{ 'opacity-70': loading }">
      <SPanel v-for="c in cadences" :key="c.id" :title="c.name">
        <template #actions>
          <UButton v-if="canChange" label="Editar" icon="i-lucide-pencil" size="xs" color="neutral" variant="outline" @click="edit(c)" />
        </template>
        <div class="mb-3 flex flex-wrap gap-1.5">
          <UBadge :label="`Etapa: ${c.stage_name}`" variant="subtle" />
          <UBadge v-if="!c.active" label="Inativa" color="neutral" variant="subtle" />
          <UBadge v-if="c.skip_weekends" label="Pula fins de semana" color="neutral" variant="outline" />
          <UBadge v-if="c.skip_holidays" label="Pula feriados" color="neutral" variant="outline" />
        </div>
        <ol class="divide-y divide-muted text-sm">
          <li v-for="(s, i) in c.steps" :key="s.id!" class="flex items-center gap-3 py-1.5" :class="{ 'opacity-50': !s.active }">
            <span class="w-5 text-dimmed tabular">{{ i + 1 }}.</span>
            <span class="min-w-0 flex-1 truncate text-highlighted">{{ s.title }}</span>
            <span class="text-xs text-dimmed">{{ DUNNING_LABELS.activityKind[s.kind] }} · {{ after(s, i) }}</span>
          </li>
        </ol>
      </SPanel>
      <p v-if="!loading && !cadences.length" class="text-sm text-dimmed">Nenhuma cadência.</p>
    </div>

    <UModal v-model:open="editor.open" :title="editor.id ? 'Editar cadência' : 'Nova cadência'" :ui="{ content: 'sm:max-w-3xl' }">
      <template #body>
        <form id="cadence-form" class="flex flex-col gap-4" @submit.prevent="save">
          <div class="grid gap-4 sm:grid-cols-2">
            <UFormField label="Nome" required>
              <UInput v-model="editor.name" class="w-full" />
            </UFormField>
            <UFormField label="Inicia na etapa" required>
              <USelect v-model="editor.stage_id" :items="stageItems" class="w-full" />
            </UFormField>
          </div>
          <div class="flex flex-wrap gap-x-6 gap-y-2">
            <USwitch v-model="editor.skip_weekends" label="Pular fins de semana" />
            <USwitch v-model="editor.skip_holidays" label="Pular feriados" />
            <USwitch v-model="editor.active" label="Ativa" />
          </div>

          <div v-for="(s, i) in editor.steps" :key="i" class="flex flex-col gap-3 rounded-lg p-3 ring ring-default">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium text-highlighted">Passo {{ i + 1 }}</span>
              <USwitch v-model="s.active" size="sm" label="Ativo" class="ms-3" />
              <div class="ms-auto flex gap-1">
                <UButton icon="i-lucide-arrow-up" size="xs" color="neutral" variant="ghost" aria-label="Subir" :disabled="i === 0"
                         @click="moveStep(i, i - 1)" />
                <UButton icon="i-lucide-arrow-down" size="xs" color="neutral" variant="ghost" aria-label="Descer"
                         :disabled="i === editor.steps.length - 1" @click="moveStep(i, i + 1)" />
                <UButton icon="i-lucide-trash-2" size="xs" color="error" variant="ghost" aria-label="Remover passo"
                         :disabled="editor.steps.length === 1" @click="editor.steps.splice(i, 1)" />
              </div>
            </div>
            <div class="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)_12rem]">
              <UFormField label="Tipo">
                <USelect v-model="s.kind" :items="kindItems" class="w-full" />
              </UFormField>
              <UFormField label="Atividade" required>
                <UInput v-model="s.title" class="w-full" />
              </UFormField>
              <UFormField :label="i === 0 ? 'Dias após entrar na etapa' : 'Dias após o anterior'">
                <UInputNumber v-model="s.interval_days" :min="0" :max="365" class="w-full" />
              </UFormField>
            </div>
            <UFormField label="Mensagem">
              <DunningTemplateInput v-model="s.template" />
            </UFormField>
          </div>
          <UButton label="Adicionar passo" icon="i-lucide-plus" color="neutral" variant="outline" class="self-start"
                   @click="editor.steps.push(newStep())" />
        </form>
      </template>
      <template #footer>
        <div class="flex w-full items-center gap-2">
          <UButton v-if="editor.id && auth.can('dunning', 'delete')" label="Excluir" icon="i-lucide-trash-2" color="error" variant="ghost"
                   @click="remove" />
          <UButton label="Cancelar" color="neutral" variant="ghost" class="ms-auto" @click="editor.open = false" />
          <UButton type="submit" form="cadence-form" label="Salvar" :loading="editor.saving" :disabled="!ready || !canChange" />
        </div>
      </template>
    </UModal>
  </AppPage>
</template>
