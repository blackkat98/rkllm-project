<script setup lang="ts">
import type { ApiKey } from '~/types/api'

const auth = useAuthStore()
const models = useModelsStore()
const toast = useToast()
const colorMode = useColorMode()
useHead({ title: () => `Settings · ${auth.appName}` })

const tabs = [
  { label: 'General', icon: 'i-lucide-sliders-horizontal', slot: 'general' as const },
  { label: 'Personalization', icon: 'i-lucide-user-pen', slot: 'personal' as const },
  { label: 'Account', icon: 'i-lucide-key-round', slot: 'account' as const },
  { label: 'API keys', icon: 'i-lucide-terminal', slot: 'keys' as const }
]

// ---- general ----
const themeItems = [
  { label: 'System', value: 'system', icon: 'i-lucide-monitor' },
  { label: 'Light', value: 'light', icon: 'i-lucide-sun' },
  { label: 'Dark', value: 'dark', icon: 'i-lucide-moon' }
]
const modelItems = computed(() => [{ label: 'Instance default', value: 0 }, ...models.models.map(m => ({ label: m.display_name, value: m.id }))])
const defaultModel = computed({
  get: () => (auth.user?.settings?.default_model_id as number | undefined) ?? 0,
  set: async (v: number) => {
    await auth.updateMe({ settings: { default_model_id: v || null } })
    toast.add({ title: 'Default model saved', color: 'success' })
  }
})

// ---- personalization ----
const personal = reactive({
  display_name: auth.user?.display_name ?? '',
  custom_instructions: auth.user?.custom_instructions ?? ''
})
const savingPersonal = ref(false)
async function savePersonal() {
  savingPersonal.value = true
  try {
    await auth.updateMe({ display_name: personal.display_name || null, custom_instructions: personal.custom_instructions || null })
    toast.add({ title: 'Saved', color: 'success' })
  } catch (e) {
    toast.add({ title: 'Could not save', description: errorMessage(e), color: 'error' })
  } finally {
    savingPersonal.value = false
  }
}

// ---- account ----
const email = ref(auth.user?.email ?? '')
async function saveEmail() {
  try {
    await auth.updateMe({ email: email.value })
    toast.add({ title: 'Email updated', color: 'success' })
  } catch (e) {
    toast.add({ title: 'Could not update email', description: errorMessage(e), color: 'error' })
  }
}
const pw = reactive({ current: '', next: '', confirm: '' })
async function changePassword() {
  if (pw.next !== pw.confirm) {
    toast.add({ title: 'Passwords do not match', color: 'error' })
    return
  }
  try {
    await api('/api/auth/password', { method: 'POST', body: { current_password: pw.current, new_password: pw.next } })
    pw.current = pw.next = pw.confirm = ''
    toast.add({ title: 'Password changed', description: 'Other sessions were signed out.', color: 'success' })
  } catch (e) {
    toast.add({ title: 'Could not change password', description: errorMessage(e), color: 'error' })
  }
}

// ---- api keys ----
const keys = ref<ApiKey[]>([])
const newKeyName = ref('')
const createdKey = ref<string | null>(null)
async function loadKeys() {
  keys.value = await api<ApiKey[]>('/api/keys')
}
async function createKey() {
  if (!newKeyName.value.trim()) return
  const k = await api<ApiKey>('/api/keys', { method: 'POST', body: { name: newKeyName.value.trim() } })
  createdKey.value = k.key ?? null
  newKeyName.value = ''
  await loadKeys()
}
async function deleteKey(id: number) {
  await api(`/api/keys/${id}`, { method: 'DELETE' })
  await loadKeys()
}
const origin = import.meta.client ? window.location.origin : ''
onMounted(() => {
  void loadKeys()
  if (!models.loaded) void models.fetch()
})
</script>

<template>
  <PageShell title="Settings">
    <UTabs :items="tabs" variant="link" class="w-full" :ui="{ list: 'mb-6' }">
      <template #general>
        <div class="space-y-6 max-w-xl">
          <UFormField label="Theme">
            <URadioGroup
              :model-value="colorMode.preference"
              :items="themeItems"
              orientation="horizontal"
              variant="card"
              @update:model-value="(v) => (colorMode.preference = String(v))"
            />
          </UFormField>
          <UFormField label="Default model for new chats" description="You can still switch models in any chat.">
            <USelect v-model="defaultModel" :items="modelItems" class="w-72" />
          </UFormField>
        </div>
      </template>

      <template #personal>
        <form class="space-y-5 max-w-xl" @submit.prevent="savePersonal">
          <UFormField label="What should the assistant call you?">
            <UInput v-model="personal.display_name" class="w-full" />
          </UFormField>
          <UFormField
            label="Custom instructions"
            description="Added to the system prompt of every chat, e.g. your role, your preferred language, or the tone you want."
          >
            <UTextarea v-model="personal.custom_instructions" :rows="6" autoresize :maxrows="14" class="w-full"
              placeholder="I'm a backend developer in Ho Chi Minh City. Answer concisely, in Vietnamese unless I write in English." />
          </UFormField>
          <UButton type="submit" color="neutral" label="Save" :loading="savingPersonal" />
        </form>
      </template>

      <template #account>
        <div class="space-y-8 max-w-xl">
          <form class="space-y-3" @submit.prevent="saveEmail">
            <UFormField label="Username">
              <UInput :model-value="auth.user?.username" disabled class="w-full" />
            </UFormField>
            <UFormField label="Email">
              <div class="flex gap-2">
                <UInput v-model="email" type="email" class="flex-1" />
                <UButton type="submit" color="neutral" variant="outline" label="Update" />
              </div>
            </UFormField>
          </form>

          <form class="space-y-3" @submit.prevent="changePassword">
            <h3 class="font-medium">Change password</h3>
            <UInput v-model="pw.current" type="password" placeholder="Current password" autocomplete="current-password" class="w-full" />
            <UInput v-model="pw.next" type="password" placeholder="New password (min. 8 characters)" autocomplete="new-password" class="w-full" />
            <UInput v-model="pw.confirm" type="password" placeholder="Confirm new password" autocomplete="new-password" class="w-full" />
            <UButton type="submit" color="neutral" label="Change password" />
          </form>

          <div class="pt-2 border-t border-(--ui-border)">
            <h3 class="font-medium mb-1">Sessions</h3>
            <p class="text-sm text-(--ui-text-muted) mb-3">Sign out of every browser and device, including this one.</p>
            <UButton color="error" variant="soft" icon="i-lucide-log-out" label="Log out everywhere" @click="auth.logout(true)" />
          </div>
        </div>
      </template>

      <template #keys>
        <div class="space-y-5 max-w-2xl">
          <p class="text-sm text-(--ui-text-muted)">
            Use the OpenAI-compatible API at <code class="text-(--ui-text)">{{ origin }}/v1</code> with
            <code class="text-(--ui-text)">Authorization: Bearer &lt;key&gt;</code>.
            Requests share the NPU queue with chats and are not saved.
          </p>
          <form class="flex gap-2" @submit.prevent="createKey">
            <UInput v-model="newKeyName" placeholder="Key name, e.g. home-assistant" class="flex-1" />
            <UButton type="submit" color="neutral" icon="i-lucide-plus" label="Create key" :disabled="!newKeyName.trim()" />
          </form>
          <UAlert v-if="createdKey" color="success" variant="subtle" icon="i-lucide-key-round" title="Copy your new key now. It won't be shown again."
            :close="true" @update:open="createdKey = null">
            <template #description>
              <code class="block mt-1 break-all select-all">{{ createdKey }}</code>
            </template>
          </UAlert>
          <div class="divide-y divide-(--ui-border) border border-(--ui-border) rounded-xl">
            <div v-if="!keys.length" class="p-4 text-sm text-(--ui-text-muted)">No keys yet.</div>
            <div v-for="k in keys" :key="k.id" class="flex items-center gap-3 p-3">
              <UIcon name="i-lucide-key-round" class="size-4 text-(--ui-text-muted)" />
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium">{{ k.name }}</p>
                <p class="text-xs text-(--ui-text-muted)">
                  {{ k.prefix }}… · created {{ new Date(k.created_at).toLocaleDateString() }}
                  <template v-if="k.last_used_at"> · last used {{ new Date(k.last_used_at).toLocaleString() }}</template>
                </p>
              </div>
              <UButton icon="i-lucide-trash-2" color="error" variant="ghost" size="sm" aria-label="Delete key" @click="deleteKey(k.id)" />
            </div>
          </div>
        </div>
      </template>
    </UTabs>
  </PageShell>
</template>
