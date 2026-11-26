<script setup lang="ts">
import type { components } from '~/types/api'

type Check = components['schemas']['CheckOut']
type Case = components['schemas']['CaseOut']
const props = defineProps<{ item: Case }>()
const emit = defineEmits<{ changed: [] }>()

const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const canChange = computed(() => auth.can('legal', 'change'))
const path = computed(() => ({ case_id: props.item.id! }))

const checks = ref<Check[]>([])
const people = ref<{ label: string; value: number }[]>([])
const load = () => unwrap(api.GET('/api/collection-case/{case_id}/checklist', { params: { path: path.value } }))
  .then(c => (checks.value = c)).catch(notifyError)
watch(() => props.item, load, { immediate: true })
unwrap(api.GET('/api/collection-case/responsibles'))
  .then(list => (people.value = list.map(p => ({ label: p.name, value: p.id })))).catch(notifyError)

const notes = reactive<Record<number, string>>({})
async function toggle(c: Check, done: boolean) {
  try {
    checks.value = await unwrap(api.PUT('/api/collection-case/{case_id}/checklist/{item_id}', {
      params: { path: { ...path.value, item_id: c.item_id } }, body: { done, note: notes[c.item_id] ?? '' },
    }))
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}
async function setResponsible(id: number | null) {
  try {
    await unwrap(api.PATCH('/api/collection-case/{case_id}', { params: { path: path.value }, body: { responsible_id: id } }))
    emit('changed')
  } catch (e) {
    notifyError(e)
  }
}
const pending = computed(() => checks.value.filter(c => c.required && !c.done).length)
</script>

<template>
  <div class="flex flex-col gap-4">
    <UFormField label="Responsável jurídico">
      <USelect :model-value="item.responsible_id ?? undefined" :items="people" :disabled="!canChange" placeholder="Nenhum" class="w-full sm:w-80"
               @update:model-value="(v: any) => setResponsible(v ?? null)" />
    </UFormField>
    <UBadge :label="pending ? `Faltam ${pending} item(ns) obrigatório(s)` : 'Checklist completo'"
            :color="pending ? 'warning' : 'success'" variant="subtle" class="self-start" />
    <ul class="divide-y divide-muted rounded-xl ring ring-default">
      <li v-for="c in checks" :key="c.item_id" class="flex items-start gap-3 px-3 py-2.5 text-sm">
        <UCheckbox :model-value="c.done" :disabled="(!!c.auto && c.done && !c.checked_at) || !canChange" class="mt-0.5"
                   @update:model-value="(v: any) => toggle(c, !!v)" />
        <div class="min-w-0 flex-1">
          <p :class="c.done ? 'text-highlighted' : ''">
            {{ c.label }}<span v-if="c.required" class="text-error"> *</span>
          </p>
          <p v-if="c.auto && c.done && !c.checked_at" class="text-xs text-dimmed">Automático</p>
          <p v-else-if="c.done" class="text-xs text-dimmed">
            {{ c.checked_by_name }} · {{ formatDateTime(c.checked_at!) }}<template v-if="c.note"> · {{ c.note }}</template>
          </p>
          <UInput v-else-if="canChange" v-model="notes[c.item_id]" size="xs" placeholder="Observação" class="mt-1 w-full" />
        </div>
      </li>
    </ul>
  </div>
</template>
