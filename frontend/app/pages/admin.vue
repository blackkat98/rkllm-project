<script setup lang="ts">
const auth = useAuthStore()
useHead({ title: () => `Admin · ${auth.appName}` })
const tabs = [
  { label: 'Models', icon: 'i-lucide-boxes', slot: 'models' as const },
  { label: 'Users', icon: 'i-lucide-users', slot: 'users' as const },
  { label: 'Instance', icon: 'i-lucide-server-cog', slot: 'instance' as const }
]
</script>

<template>
  <PageShell title="Admin" description="Manage models on the NPU, user accounts and instance-wide settings.">
    <UTabs :items="tabs" variant="link" class="w-full" :ui="{ list: 'mb-6' }">
      <template #models><AdminModels /></template>
      <template #users><AdminUsers /></template>
      <template #instance><AdminInstance /></template>
    </UTabs>
  </PageShell>
</template>
