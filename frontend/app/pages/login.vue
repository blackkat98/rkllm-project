<script setup lang="ts">
definePageMeta({ layout: 'auth' })

const auth = useAuthStore()
const mode = ref<'login' | 'register'>('login')
const loading = ref(false)
const error = ref('')

const form = reactive({ username: '', email: '', password: '', display_name: '' })

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'login') await auth.login(form.username, form.password)
    else await auth.register({ username: form.username, email: form.email, password: form.password, display_name: form.display_name || undefined })
    await navigateTo('/')
  } catch (e) {
    error.value = errorMessage(e, 'Login failed')
  } finally {
    loading.value = false
  }
}
useHead({ title: () => `${mode.value === 'login' ? 'Log in' : 'Create account'} · ${auth.appName}` })
</script>

<template>
  <div class="w-full max-w-sm">
    <div class="flex flex-col items-center mb-8">
      <span class="size-12 rounded-2xl bg-(--ui-primary) text-white grid place-items-center mb-4 shadow-lg shadow-(--ui-primary)/30">
        <UIcon name="i-lucide-cpu" class="size-6" />
      </span>
      <h1 class="text-2xl font-semibold tracking-tight">
        {{ mode === 'login' ? 'Welcome back' : 'Create your account' }}
      </h1>
      <p class="text-sm text-(--ui-text-muted) mt-1">{{ auth.appName }} · private AI on your own hardware</p>
    </div>

    <form class="space-y-4" @submit.prevent="submit">
      <UFormField :label="mode === 'login' ? 'Username or email' : 'Username'">
        <UInput v-model="form.username" autocomplete="username" size="lg" class="w-full" autofocus required />
      </UFormField>
      <template v-if="mode === 'register'">
        <UFormField label="Email">
          <UInput v-model="form.email" type="email" autocomplete="email" size="lg" class="w-full" required />
        </UFormField>
        <UFormField label="Display name" hint="Optional">
          <UInput v-model="form.display_name" size="lg" class="w-full" />
        </UFormField>
      </template>
      <UFormField label="Password" :hint="mode === 'register' ? 'At least 8 characters' : undefined">
        <UInput v-model="form.password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" size="lg" class="w-full" required />
      </UFormField>

      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />

      <UButton type="submit" block size="lg" color="neutral" :loading="loading" :label="mode === 'login' ? 'Log in' : 'Create account'" />
    </form>

    <p v-if="auth.openSignup" class="text-sm text-center text-(--ui-text-muted) mt-6">
      <template v-if="mode === 'login'">
        No account?
        <button class="text-(--ui-primary) font-medium cursor-pointer" @click="mode = 'register'; error = ''">Sign up</button>
      </template>
      <template v-else>
        Already have an account?
        <button class="text-(--ui-primary) font-medium cursor-pointer" @click="mode = 'login'; error = ''">Log in</button>
      </template>
    </p>
    <p v-else class="text-xs text-center text-(--ui-text-dimmed) mt-6">
      Accounts are created by the administrator.
    </p>
  </div>
</template>
