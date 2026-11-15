<script setup lang="ts">
defineProps<{ title: string, description?: string }>()
const { collapsed, toggle } = useSidebar()
</script>

<template>
  <div class="flex flex-col h-full">
    <header class="h-14 shrink-0 flex items-center gap-1 px-2 md:px-3">
      <UButton icon="i-lucide-panel-left-open" color="neutral" variant="ghost" aria-label="Toggle sidebar"
        :class="collapsed ? '' : 'md:hidden'" @click="toggle" />
    </header>
    <div class="flex-1 overflow-y-auto">
      <div class="max-w-4xl mx-auto px-4 md:px-6 pb-16">
        <h1 class="text-2xl font-semibold tracking-tight">{{ title }}</h1>
        <p v-if="description" class="text-sm text-(--ui-text-muted) mt-1">{{ description }}</p>
        <div class="mt-6">
          <slot />
        </div>
      </div>
    </div>
  </div>
</template>
