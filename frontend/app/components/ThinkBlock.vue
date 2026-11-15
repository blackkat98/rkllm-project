<script setup lang="ts">
const props = defineProps<{ text: string, active: boolean }>()
const open = ref(props.active)
watch(() => props.active, (v) => { if (!v) open.value = false })
</script>

<template>
  <div class="mb-3">
    <button
      type="button"
      class="inline-flex items-center gap-1.5 text-sm text-(--ui-text-muted) hover:text-(--ui-text) cursor-pointer"
      @click="open = !open"
    >
      <UIcon name="i-lucide-brain" class="size-4" />
      <span :class="{ shimmer: active }">{{ active ? 'Thinking…' : 'Thought process' }}</span>
      <UIcon name="i-lucide-chevron-down" class="size-4 transition-transform" :class="{ 'rotate-180': open }" />
    </button>
    <div
      v-if="open"
      class="mt-2 border-l-2 border-(--ui-border-accented) pl-4 text-sm text-(--ui-text-muted) whitespace-pre-wrap leading-relaxed"
    >
      {{ text || '…' }}
    </div>
  </div>
</template>
