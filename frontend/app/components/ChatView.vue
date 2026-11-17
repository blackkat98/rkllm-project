<script setup lang="ts">
const props = defineProps<{ id?: string }>()

const chat = useChatStore()
const models = useModelsStore()
const auth = useAuthStore()
const toast = useToast()
const { collapsed, toggle } = useSidebar()

const draft = ref('')
const composer = useTemplateRef<{ focus: () => void }>('composer')
const scroller = useTemplateRef<HTMLElement>('scroller')

// ---------- load ----------
watch(() => props.id, async (id) => {
  if (id) {
    try {
      await chat.load(id)
    } catch (e) {
      toast.add({ title: 'Could not load chat', description: errorMessage(e), color: 'error' })
    }
  } else if (chat.conversationId && !chat.streaming) {
    chat.reset()
  }
  await nextTick()
  scrollToBottom(true)
  composer.value?.focus()
}, { immediate: true })

// ---------- model selection ----------
// admins: inside a conversation its model (can be switched for the next message), new chat: picker
// state. Everyone else always uses the instance default chosen in Admin.
const convModel = ref<number | null>(null)
watch(() => chat.conversation?.model_id, (v) => { convModel.value = v ?? null }, { immediate: true })
const selectedModel = computed<number | null>({
  get: () => {
    if (!auth.isAdmin) return models.defaultModel?.id ?? null
    return props.id ? (convModel.value ?? models.defaultModel?.id ?? null) : models.newChatModelId
  },
  set: (v) => {
    if (!v || !auth.isAdmin) return
    if (props.id) convModel.value = v
    else models.setNewChatModel(v)
  }
})

// ---------- actions ----------
async function send(text: string) {
  try {
    const id = await chat.send(text, selectedModel.value)
    if (id && !props.id) await navigateTo(`/c/${id}`, { replace: true })
    scrollToBottom(true)
  } catch (e) {
    draft.value = text
    toast.add({ title: 'Could not send', description: errorMessage(e), color: 'error' })
  }
}
function regenerate() {
  scrollToBottom(true)
  void chat.regenerate(selectedModel.value)
}
function edit(messageId: number, content: string) {
  void chat.edit(messageId, content, selectedModel.value)
}

// ---------- autoscroll ----------
const atBottom = ref(true)
function onScroll() {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
function scrollToBottom(force = false) {
  const el = scroller.value
  if (!el || (!force && !atBottom.value)) return
  el.scrollTo({ top: el.scrollHeight, behavior: force ? 'auto' : 'instant' as ScrollBehavior })
}
watch(() => chat.messages.at(-1)?.content.length, () => nextTick(() => scrollToBottom()))

// ---------- empty state ----------
const greeting = computed(() => {
  const h = new Date().getHours()
  const part = h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
  return `${part}, ${auth.displayName}`
})
const suggestions = [
  { icon: 'i-lucide-lightbulb', text: 'Explain how an NPU differs from a GPU' },
  { icon: 'i-lucide-code', text: 'Write a Python script that renames photos by date' },
  { icon: 'i-lucide-languages', text: 'Translate "Have a nice weekend" into Vietnamese and Japanese' },
  { icon: 'i-lucide-list-checks', text: 'Plan a 3-day trip to Da Lat on a budget' }
]
const isEmpty = computed(() => !props.id && chat.messages.length === 0)
const title = computed(() => (props.id ? chat.conversation?.title : null) ?? 'New chat')
useHead({ title: () => `${title.value} · ${auth.appName}` })
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- top bar -->
    <header class="h-14 shrink-0 flex items-center gap-1 px-2 md:px-3">
      <UTooltip :text="collapsed ? 'Open sidebar' : 'Sidebar'">
        <UButton
          icon="i-lucide-panel-left-open"
          color="neutral"
          variant="ghost"
          aria-label="Toggle sidebar"
          :class="collapsed ? '' : 'md:hidden'"
          @click="toggle"
        />
      </UTooltip>
      <UTooltip v-if="collapsed" text="New chat">
        <UButton icon="i-lucide-square-pen" color="neutral" variant="ghost" class="hidden md:inline-flex" aria-label="New chat" to="/" @click="chat.newChat()" />
      </UTooltip>
      <h1 v-if="!isEmpty" class="ml-1 truncate text-sm font-medium text-(--ui-text-toned)">
        {{ title }}
      </h1>
      <UTooltip v-if="chat.conversation?.has_summary" text="Older messages are condensed into a summary to fit the model's context window">
        <UBadge color="neutral" variant="soft" size="sm" icon="i-lucide-archive" class="ml-1">memory</UBadge>
      </UTooltip>
    </header>

    <!-- empty / new chat -->
    <div v-if="isEmpty" class="flex-1 overflow-y-auto">
      <div class="min-h-full flex flex-col items-center justify-center px-4 pb-16">
        <div class="w-full max-w-3xl">
          <h2 class="text-3xl md:text-4xl font-semibold tracking-tight mb-2 bg-gradient-to-r from-(--ui-primary) to-pink-500 bg-clip-text text-transparent w-fit">
            {{ greeting }}
          </h2>
          <p class="text-xl md:text-2xl text-(--ui-text-muted) mb-8">How can I help today?</p>
          <ChatComposer
            ref="composer"
            v-model:text="draft"
            :model-id="selectedModel"
            :streaming="chat.streaming"
            autofocus
            @update:model-id="(id) => (selectedModel = id)"
            @send="send"
            @stop="chat.stop()"
          />
          <div class="grid sm:grid-cols-2 gap-2 mt-4">
            <button
              v-for="s in suggestions"
              :key="s.text"
              type="button"
              class="flex items-start gap-2.5 text-left rounded-2xl border border-(--ui-border) px-4 py-3 text-sm text-(--ui-text-toned) hover:bg-(--ui-bg-elevated) transition-colors cursor-pointer"
              @click="draft = s.text; composer?.focus()"
            >
              <UIcon :name="s.icon" class="size-4 mt-0.5 shrink-0 text-(--ui-text-muted)" />
              <span>{{ s.text }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- conversation -->
    <template v-else>
      <div ref="scroller" class="flex-1 overflow-y-auto" @scroll="onScroll">
        <div v-if="chat.notFound" class="max-w-3xl mx-auto px-4 py-20 text-center">
          <UIcon name="i-lucide-message-circle-off" class="size-10 text-(--ui-text-muted) mx-auto mb-3" />
          <p class="font-medium">This chat doesn't exist or was deleted.</p>
          <UButton class="mt-4" label="Start a new chat" color="neutral" to="/" />
        </div>
        <div v-else-if="chat.loading" class="max-w-3xl mx-auto px-4 py-8 space-y-6">
          <USkeleton class="h-10 w-1/2 ml-auto rounded-3xl" />
          <USkeleton class="h-24 w-full" />
          <USkeleton class="h-10 w-2/5 ml-auto rounded-3xl" />
        </div>
        <div v-else class="max-w-3xl mx-auto px-4 pt-4 pb-10 space-y-8">
          <ChatMessageItem
            v-for="(m, i) in chat.messages"
            :key="m.id"
            :message="m"
            :is-last="i === chat.messages.length - 1"
            :busy="chat.streaming"
            @regenerate="regenerate"
            @edit="(c) => edit(m.id, c)"
          />
        </div>
      </div>

      <div class="relative shrink-0 px-4 pb-3 pt-1">
        <UButton
          v-if="!atBottom"
          icon="i-lucide-arrow-down"
          color="neutral"
          variant="outline"
          class="absolute -top-12 left-1/2 -translate-x-1/2 rounded-full shadow-md bg-(--ui-bg)"
          aria-label="Scroll to bottom"
          @click="scrollToBottom(true)"
        />
        <div class="max-w-3xl mx-auto">
          <ChatComposer
            ref="composer"
            v-model:text="draft"
            :model-id="selectedModel"
            :streaming="chat.streaming"
            @update:model-id="(id) => (selectedModel = id)"
            @send="send"
            @stop="chat.stop()"
          />
          <p class="text-center text-xs text-(--ui-text-dimmed) mt-2">
            Runs locally on your device's NPU. Small models make mistakes, so double-check important answers.
          </p>
        </div>
      </div>
    </template>
  </div>
</template>
