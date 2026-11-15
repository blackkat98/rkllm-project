<script setup lang="ts">
const chat = useChatStore()
const label = computed(() => {
  switch (chat.phase) {
    case 'queued':
      return chat.queueAhead > 0
        ? `Waiting for the NPU · ${chat.queueAhead} ahead`
        : 'Waiting for the NPU…'
    case 'loading_model':
      return `Loading ${chat.loadingModelName || 'model'} onto the NPU…`
    case 'summarizing':
      return 'Condensing earlier messages to fit the context…'
    case 'started':
      return 'Reading the conversation…'
    default:
      return ''
  }
})
const icon = computed(() => ({
  queued: 'i-lucide-hourglass',
  loading_model: 'i-lucide-hard-drive-download',
  summarizing: 'i-lucide-archive-restore',
  started: 'i-lucide-sparkles'
} as Record<string, string>)[chat.phase] ?? 'i-lucide-sparkles')
</script>

<template>
  <div v-if="label" class="flex items-center gap-2 text-sm text-(--ui-text-muted) py-1">
    <UIcon :name="icon" class="size-4" />
    <span class="shimmer">{{ label }}</span>
  </div>
</template>
