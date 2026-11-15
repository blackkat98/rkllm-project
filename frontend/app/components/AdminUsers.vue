<script setup lang="ts">
import type { User } from '~/types/api'

const auth = useAuthStore()
const toast = useToast()
const users = ref<User[]>([])
const loading = ref(true)

async function load() {
  users.value = await api<User[]>('/api/admin/users')
  loading.value = false
}

async function patch(u: User, body: Record<string, unknown>) {
  try {
    Object.assign(u, await api<User>(`/api/admin/users/${u.id}`, { method: 'PATCH', body }))
  } catch (e) {
    toast.add({ title: 'Update failed', description: errorMessage(e), color: 'error' })
    await load()
  }
}

// ---- create ----
const creating = ref(false)
const form = reactive({ username: '', email: '', display_name: '', password: '', role: 'user' as 'user' | 'admin' })
async function create() {
  try {
    await api('/api/admin/users', { method: 'POST', body: { ...form, display_name: form.display_name || null } })
    creating.value = false
    Object.assign(form, { username: '', email: '', display_name: '', password: '', role: 'user' })
    toast.add({ title: 'User created', color: 'success' })
    await load()
  } catch (e) {
    toast.add({ title: 'Could not create user', description: errorMessage(e), color: 'error' })
  }
}

// ---- reset password ----
const resetting = ref<User | null>(null)
const newPassword = ref('')
async function resetPassword() {
  if (!resetting.value) return
  await patch(resetting.value, { password: newPassword.value })
  toast.add({ title: 'Password reset', description: 'The user was signed out everywhere.', color: 'success' })
  resetting.value = null
  newPassword.value = ''
}

// ---- delete ----
const deleting = ref<User | null>(null)
async function remove() {
  const u = deleting.value
  if (!u) return
  deleting.value = null
  try {
    await api(`/api/admin/users/${u.id}`, { method: 'DELETE' })
    users.value = users.value.filter(x => x.id !== u.id)
  } catch (e) {
    toast.add({ title: 'Could not delete', description: errorMessage(e), color: 'error' })
  }
}

const roleItems = [{ label: 'User', value: 'user' }, { label: 'Admin', value: 'admin' }]
onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex justify-between items-center">
      <p class="text-sm text-(--ui-text-muted)">{{ users.length }} accounts</p>
      <UButton icon="i-lucide-user-plus" color="neutral" label="Add user" @click="creating = true" />
    </div>

    <div v-if="loading" class="space-y-2"><USkeleton v-for="i in 3" :key="i" class="h-14 w-full" /></div>
    <div v-else class="divide-y divide-(--ui-border) border border-(--ui-border) rounded-xl">
      <div v-for="u in users" :key="u.id" class="flex flex-wrap items-center gap-3 p-3">
        <UAvatar :text="(u.display_name || u.username).slice(0, 2).toUpperCase()" size="sm" />
        <div class="flex-1 min-w-48">
          <p class="text-sm font-medium flex items-center gap-2">
            {{ u.display_name || u.username }}
            <UBadge v-if="u.role === 'admin'" size="sm" color="primary" variant="subtle">Admin</UBadge>
            <UBadge v-if="!u.is_active" size="sm" color="neutral" variant="subtle">Disabled</UBadge>
            <span v-if="u.id === auth.user?.id" class="text-xs text-(--ui-text-muted)">(you)</span>
          </p>
          <p class="text-xs text-(--ui-text-muted)">
            @{{ u.username }} · {{ u.email }}
            · {{ u.last_login_at ? `last login ${new Date(u.last_login_at).toLocaleString()}` : 'never logged in' }}
          </p>
        </div>
        <USwitch :model-value="u.is_active" label="Active" :disabled="u.id === auth.user?.id" @update:model-value="(v) => patch(u, { is_active: v })" />
        <UDropdownMenu :items="[[
          { label: u.role === 'admin' ? 'Make regular user' : 'Make admin', icon: 'i-lucide-shield', disabled: u.id === auth.user?.id, onSelect: () => patch(u, { role: u.role === 'admin' ? 'user' : 'admin' }) },
          { label: 'Reset password', icon: 'i-lucide-key-round', onSelect: () => { resetting = u } }
        ], [
          { label: 'Delete user', icon: 'i-lucide-trash-2', color: 'error', disabled: u.id === auth.user?.id, onSelect: () => { deleting = u } }
        ]]">
          <UButton icon="i-lucide-ellipsis-vertical" color="neutral" variant="ghost" aria-label="User actions" />
        </UDropdownMenu>
      </div>
    </div>

    <UModal v-model:open="creating" title="Add user">
      <template #body>
        <form id="user-form" class="space-y-3" @submit.prevent="create">
          <UFormField label="Username" required><UInput v-model="form.username" class="w-full" autocomplete="off" /></UFormField>
          <UFormField label="Email" required><UInput v-model="form.email" type="email" class="w-full" autocomplete="off" /></UFormField>
          <UFormField label="Display name"><UInput v-model="form.display_name" class="w-full" /></UFormField>
          <UFormField label="Initial password" required hint="min. 8 characters">
            <UInput v-model="form.password" type="password" class="w-full" autocomplete="new-password" />
          </UFormField>
          <UFormField label="Role"><USelect v-model="form.role" :items="roleItems" class="w-full" /></UFormField>
        </form>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="Cancel" @click="creating = false" />
          <UButton type="submit" form="user-form" color="neutral" label="Create" />
        </div>
      </template>
    </UModal>

    <UModal :open="!!resetting" :title="`Reset password for ${resetting?.username}`" @update:open="(v: boolean) => { if (!v) resetting = null }">
      <template #body>
        <UInput v-model="newPassword" type="password" placeholder="New password (min. 8 characters)" class="w-full" autocomplete="new-password" />
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="Cancel" @click="resetting = null" />
          <UButton color="neutral" label="Reset" :disabled="newPassword.length < 8" @click="resetPassword" />
        </div>
      </template>
    </UModal>

    <UModal :open="!!deleting" title="Delete user?" @update:open="(v: boolean) => { if (!v) deleting = null }">
      <template #body>
        <p class="text-sm">This permanently deletes <strong>{{ deleting?.username }}</strong> and all of their chats.</p>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="Cancel" @click="deleting = null" />
          <UButton color="error" label="Delete" @click="remove" />
        </div>
      </template>
    </UModal>
  </div>
</template>
