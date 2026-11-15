<script setup lang="ts">
import type { AppSettings } from '~/types/api'

const toast = useToast()
const models = useModelsStore()
const settings = ref<AppSettings | null>(null)
const prompt = ref('')

async function load() {
  settings.value = await api<AppSettings>('/api/admin/settings')
  prompt.value = settings.value.global_system_prompt ?? ''
  if (!models.loaded) await models.fetch()
}

async function patch(body: Partial<AppSettings>) {
  try {
    settings.value = await api<AppSettings>('/api/admin/settings', { method: 'PATCH', body })
    toast.add({ title: 'Saved', color: 'success' })
    if ('default_model_id' in body) void models.fetch()
  } catch (e) {
    toast.add({ title: 'Could not save', description: errorMessage(e), color: 'error' })
  }
}

const modelItems = computed(() => models.models.map(m => ({ label: m.display_name, value: m.id })))
onMounted(load)
</script>

<template>
  <div v-if="settings" class="space-y-6 max-w-xl">
    <USwitch
      :model-value="settings.open_signup"
      label="Open sign-up"
      description="Let anyone who can reach this server create an account. Off by default: admins create accounts."
      @update:model-value="(v) => patch({ open_signup: v })"
    />
    <USwitch
      :model-value="settings.auto_title"
      label="Auto-generate chat titles"
      description="Runs a short background job on the NPU after the first reply."
      @update:model-value="(v) => patch({ auto_title: v })"
    />
    <UFormField label="Default model" description="Used for new chats unless a user picks their own default.">
      <USelect
        :model-value="settings.default_model_id ?? undefined"
        :items="modelItems"
        placeholder="First enabled model"
        class="w-72"
        @update:model-value="(v) => patch({ default_model_id: Number(v) })"
      />
    </UFormField>
    <UFormField label="Global system prompt" description="Prepended to every chat for every user. Keep it short: small models have small context windows.">
      <UTextarea v-model="prompt" :rows="4" autoresize :maxrows="12" class="w-full" placeholder="You are a helpful assistant running locally on an Orange Pi." />
    </UFormField>
    <UButton color="neutral" label="Save system prompt" @click="patch({ global_system_prompt: prompt || null })" />
  </div>
</template>
