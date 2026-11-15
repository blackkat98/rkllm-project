<script setup lang="ts">
const props = defineProps<{ modelId: number | null, streaming: boolean, autofocus?: boolean, placeholder?: string }>()
const emit = defineEmits<{ send: [text: string], stop: [], 'update:modelId': [id: number] }>()

const text = defineModel<string>('text', { default: '' })
const textarea = useTemplateRef<{ textareaRef?: HTMLTextAreaElement }>('textarea')

function submit() {
  if (props.streaming || !text.value.trim() || !props.modelId) return
  emit('send', text.value)
  text.value = ''
}

function onKeydown(e: KeyboardEvent) {
  // isComposing: don't send while an IME (e.g. Vietnamese Telex, CJK) is composing
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

function focus() {
  textarea.value?.textareaRef?.focus()
}
defineExpose({ focus })
</script>

<template>
  <div
    class="rounded-3xl border border-(--ui-border) bg-(--ui-bg) shadow-sm focus-within:border-(--ui-border-accented) transition-colors"
  >
    <UTextarea
      ref="textarea"
      v-model="text"
      :placeholder="placeholder ?? 'Message the model…'"
      :autofocus="autofocus"
      autoresize
      :rows="1"
      :maxrows="10"
      variant="none"
      class="w-full"
      :ui="{ base: 'px-5 pt-4 pb-1 text-base resize-none' }"
      @keydown="onKeydown"
    />
    <div class="flex items-center gap-2 px-3 pb-3 pt-1">
      <ModelPicker :model-value="modelId" :disabled="streaming" @update:model-value="(id: number) => emit('update:modelId', id)" />
      <div class="flex-1" />
      <UTooltip v-if="streaming" text="Stop generating">
        <UButton icon="i-lucide-square" color="neutral" class="rounded-full" aria-label="Stop" @click="emit('stop')" />
      </UTooltip>
      <UButton
        v-else
        icon="i-lucide-arrow-up"
        color="neutral"
        class="rounded-full"
        aria-label="Send"
        :disabled="!text.trim() || !modelId"
        @click="submit"
      />
    </div>
  </div>
</template>
