<script setup lang="ts">
import type { Message } from '~/types/api'

const props = defineProps<{
  message: Message
  isLast: boolean
  busy: boolean // a generation is running in this chat
}>()
const emit = defineEmits<{ regenerate: [], edit: [content: string] }>()

const models = useModelsStore()
const chat = useChatStore()

const isUser = computed(() => props.message.role === 'user')
const streaming = computed(() => props.message.status === 'streaming')
const parts = computed(() => splitThinking(props.message.content))
const showPhase = computed(() => streaming.value && !props.message.content && chat.phase !== 'streaming')
const modelName = computed(() => models.byId(props.message.model_id)?.display_name)

const copied = ref(false)
async function copy() {
  try {
    await navigator.clipboard.writeText(isUser.value ? props.message.content : parts.value.answer)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch { /* clipboard unavailable over plain http */ }
}

// inline edit for user messages
const editing = ref(false)
const draft = ref('')
function startEdit() {
  draft.value = props.message.content
  editing.value = true
}
function submitEdit() {
  const v = draft.value.trim()
  if (!v) return
  editing.value = false
  if (v !== props.message.content) emit('edit', v)
}

const stats = computed(() => {
  const m = props.message
  const out: string[] = []
  if (m.tok_per_s) out.push(`${m.tok_per_s} tok/s`)
  if (m.completion_tokens) out.push(`${m.completion_tokens} tokens`)
  return out.join(' · ')
})
</script>

<template>
  <!-- user -->
  <div v-if="isUser" class="group flex flex-col items-end">
    <div v-if="editing" class="w-full max-w-[85%] rounded-3xl bg-(--ui-bg-elevated) p-3">
      <UTextarea v-model="draft" autoresize :rows="2" :maxrows="12" variant="none" class="w-full" autofocus
        @keydown.enter.exact.prevent="submitEdit" @keydown.esc="editing = false" />
      <div class="flex justify-end gap-2 mt-2">
        <UButton size="sm" color="neutral" variant="ghost" label="Cancel" @click="editing = false" />
        <UButton size="sm" color="neutral" label="Send" @click="submitEdit" />
      </div>
    </div>
    <div v-else class="max-w-[85%] rounded-3xl bg-(--ui-bg-elevated) px-5 py-2.5 whitespace-pre-wrap break-words">
      {{ message.content }}
    </div>
    <div v-if="!editing" class="flex gap-0.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <UTooltip :text="copied ? 'Copied' : 'Copy'">
        <UButton :icon="copied ? 'i-lucide-check' : 'i-lucide-copy'" size="xs" color="neutral" variant="ghost" aria-label="Copy" @click="copy" />
      </UTooltip>
      <UTooltip text="Edit">
        <UButton icon="i-lucide-pencil" size="xs" color="neutral" variant="ghost" aria-label="Edit" :disabled="busy" @click="startEdit" />
      </UTooltip>
    </div>
  </div>

  <!-- assistant -->
  <div v-else class="group">
    <PhaseIndicator v-if="showPhase" />
    <ThinkBlock v-if="parts.thinking !== null" :text="parts.thinking" :active="streaming && parts.thinkingOpen" />
    <MarkdownContent
      v-if="parts.answer || (streaming && !showPhase && !parts.thinkingOpen)"
      :content="parts.answer"
      :streaming="streaming && !parts.thinkingOpen"
    />

    <UAlert
      v-if="message.status === 'error'"
      class="mt-3"
      color="error"
      variant="subtle"
      icon="i-lucide-circle-alert"
      :title="message.error || 'Generation failed'"
    />
    <p v-else-if="message.status === 'aborted'" class="mt-2 text-xs text-(--ui-text-muted) italic">
      Stopped
    </p>

    <div
      v-if="!streaming"
      class="flex flex-wrap items-center gap-0.5 mt-2 transition-opacity"
      :class="isLast ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
    >
      <UTooltip :text="copied ? 'Copied' : 'Copy'">
        <UButton :icon="copied ? 'i-lucide-check' : 'i-lucide-copy'" size="xs" color="neutral" variant="ghost" aria-label="Copy" @click="copy" />
      </UTooltip>
      <UTooltip v-if="isLast" text="Regenerate">
        <UButton icon="i-lucide-refresh-cw" size="xs" color="neutral" variant="ghost" aria-label="Regenerate" :disabled="busy" @click="emit('regenerate')" />
      </UTooltip>
      <span class="ml-2 text-xs text-(--ui-text-dimmed) flex items-center gap-2">
        <span v-if="modelName">{{ modelName }}</span>
        <span v-if="stats">{{ stats }}</span>
        <UTooltip v-if="message.used_kv_cache" text="Continued from the NPU's KV cache: the chat history wasn't processed again">
          <span class="inline-flex items-center gap-0.5"><UIcon name="i-lucide-zap" class="size-3" />cached</span>
        </UTooltip>
      </span>
    </div>
  </div>
</template>
