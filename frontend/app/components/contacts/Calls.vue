<script setup lang="ts">
import type { components } from '~/types/api'

const props = withDefaults(defineProps<{ contactId: number; phone?: string | null; button?: boolean }>(), { button: true })
const { api, unwrap, notifyError } = useApi()
const auth = useAuth()
const { calling, call } = usePhoneCall()

const calls = ref<components['schemas']['CallOut'][]>([])
const load = () => unwrap(api.GET('/api/contact/{contact_id}/calls', { params: { path: { contact_id: props.contactId } } }))
  .then(list => (calls.value = list)).catch(notifyError)
watch(() => props.contactId, load, { immediate: true })
const dial = () => call({ contact_id: props.contactId }, load)
defineExpose({ load, dial, calling })
</script>

<template>
  <div class="flex flex-col gap-2">
    <UButton v-if="button && auth.me.value?.has_phone_line && phone" label="Ligar" icon="i-lucide-phone-outgoing" size="sm" variant="soft"
             class="self-start" :loading="calling" @click="dial" />
    <ul class="flex flex-col divide-y divide-muted text-sm">
      <li v-for="c in calls" :key="c.id" class="flex items-start gap-3 py-2">
        <UIcon name="i-lucide-phone" class="mt-0.5 size-4 shrink-0 text-dimmed" />
        <div class="min-w-0 flex-1">
          <p class="text-toned">{{ callLabel(c) }}<span v-if="c.activity_title" class="text-dimmed"> · {{ c.activity_title }}</span></p>
          <p class="text-xs text-dimmed">{{ formatDateTime(c.created_at) }} · {{ c.user_name ?? '—' }}</p>
        </div>
        <a v-if="c.record_url" :href="c.record_url" target="_blank" rel="noopener" class="text-xs text-muted hover:text-primary">Gravação</a>
      </li>
      <li v-if="!calls.length" class="py-2 text-dimmed">Nenhuma ligação.</li>
    </ul>
  </div>
</template>
