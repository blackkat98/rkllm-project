<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'
import type { Conversation } from '~/types/api'

const auth = useAuthStore()
const conversations = useConversationsStore()
const chat = useChatStore()
const route = useRoute()
const colorMode = useColorMode()
const toast = useToast()
const { toggle } = useSidebar()

const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(search, (q) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => conversations.runSearch(q), 250)
})

const activeId = computed(() => (route.params.id as string | undefined) ?? null)

function newChat() {
  chat.newChat()
  navigateTo('/')
}

// ---- rename ----
const renaming = ref<string | null>(null)
const renameValue = ref('')
function startRename(c: Conversation) {
  renaming.value = c.id
  renameValue.value = c.title
  nextTick(() => (document.getElementById(`rename-${c.id}`) as HTMLInputElement | null)?.select())
}
async function commitRename(c: Conversation) {
  const title = renameValue.value.trim()
  renaming.value = null
  if (!title || title === c.title) return
  await conversations.update(c.id, { title })
  if (chat.conversation?.id === c.id) chat.conversation.title = title
}

// ---- delete ----
const deleting = ref<Conversation | null>(null)
async function confirmDelete() {
  const c = deleting.value
  if (!c) return
  deleting.value = null
  try {
    await conversations.remove(c.id)
    if (activeId.value === c.id) newChat()
  } catch (e) {
    toast.add({ title: 'Could not delete', description: errorMessage(e), color: 'error' })
  }
}

function itemMenu(c: Conversation): DropdownMenuItem[][] {
  return [[
    { label: c.pinned ? 'Unpin' : 'Pin', icon: c.pinned ? 'i-lucide-pin-off' : 'i-lucide-pin', onSelect: () => conversations.update(c.id, { pinned: !c.pinned }) },
    { label: 'Rename', icon: 'i-lucide-pencil', onSelect: () => startRename(c) },
    { label: 'Archive', icon: 'i-lucide-archive', onSelect: async () => { await conversations.update(c.id, { archived: true }); if (activeId.value === c.id) newChat() } }
  ], [
    { label: 'Delete', icon: 'i-lucide-trash-2', color: 'error', onSelect: () => { deleting.value = c } }
  ]]
}

const userMenu = computed<DropdownMenuItem[][]>(() => [
  [{ label: auth.user?.email ?? '', type: 'label' }],
  [
    { label: 'Settings', icon: 'i-lucide-settings', to: '/settings' },
    ...(auth.isAdmin ? [{ label: 'Admin', icon: 'i-lucide-shield', to: '/admin' }] : []),
    {
      label: 'Theme',
      icon: colorMode.value === 'dark' ? 'i-lucide-moon' : 'i-lucide-sun',
      children: [
        { label: 'System', icon: 'i-lucide-monitor', type: 'checkbox', checked: colorMode.preference === 'system', onSelect: (e: Event) => { e.preventDefault(); colorMode.preference = 'system' } },
        { label: 'Light', icon: 'i-lucide-sun', type: 'checkbox', checked: colorMode.preference === 'light', onSelect: (e: Event) => { e.preventDefault(); colorMode.preference = 'light' } },
        { label: 'Dark', icon: 'i-lucide-moon', type: 'checkbox', checked: colorMode.preference === 'dark', onSelect: (e: Event) => { e.preventDefault(); colorMode.preference = 'dark' } }
      ]
    }
  ],
  [{ label: 'Log out', icon: 'i-lucide-log-out', onSelect: () => auth.logout() }]
])

const initials = computed(() => (auth.displayName || '?').slice(0, 2).toUpperCase())
</script>

<template>
  <div class="flex flex-col h-full min-w-68 w-full">
    <!-- header -->
    <div class="flex items-center justify-between px-3 h-14 shrink-0">
      <NuxtLink to="/" class="flex items-center gap-2 font-semibold tracking-tight" @click="chat.newChat()">
        <span class="size-7 rounded-lg bg-(--ui-primary) text-white grid place-items-center">
          <UIcon name="i-lucide-cpu" class="size-4" />
        </span>
        <span>{{ auth.appName }}</span>
      </NuxtLink>
      <UTooltip text="Close sidebar">
        <UButton icon="i-lucide-panel-left-close" color="neutral" variant="ghost" aria-label="Close sidebar" @click="toggle" />
      </UTooltip>
    </div>

    <div class="px-3 space-y-2 shrink-0">
      <UButton block icon="i-lucide-square-pen" color="neutral" variant="outline" class="justify-start" label="New chat" @click="newChat" />
      <UInput v-model="search" icon="i-lucide-search" placeholder="Search chats" variant="soft" class="w-full" :ui="{ base: 'bg-(--ui-bg-elevated)' }">
        <template v-if="search" #trailing>
          <UButton icon="i-lucide-x" size="xs" color="neutral" variant="link" aria-label="Clear search" @click="search = ''" />
        </template>
      </UInput>
    </div>

    <!-- list -->
    <nav class="flex-1 overflow-y-auto px-2 py-3 space-y-4">
      <div v-if="!conversations.loaded" class="space-y-2 px-1">
        <USkeleton v-for="i in 6" :key="i" class="h-7 w-full" />
      </div>
      <p v-else-if="!conversations.groups.length" class="px-3 text-sm text-(--ui-text-muted)">
        {{ conversations.searchResults ? 'No chats match your search.' : 'No chats yet.' }}
      </p>
      <div v-for="group in conversations.groups" :key="group.label">
        <p class="px-3 pb-1 text-xs font-medium text-(--ui-text-muted)">{{ group.label }}</p>
        <ul>
          <li v-for="c in group.items" :key="c.id" class="group relative">
            <input
              v-if="renaming === c.id"
              :id="`rename-${c.id}`"
              v-model="renameValue"
              class="w-full rounded-lg px-3 py-1.5 text-sm bg-(--ui-bg) border border-(--ui-border-accented) outline-none"
              @keydown.enter="commitRename(c)"
              @keydown.esc="renaming = null"
              @blur="commitRename(c)"
            >
            <NuxtLink
              v-else
              :to="`/c/${c.id}`"
              class="flex items-center gap-1.5 rounded-lg pl-3 pr-8 py-1.5 text-sm transition-colors"
              :class="activeId === c.id ? 'bg-(--ui-bg-accented) text-(--ui-text-highlighted)' : 'hover:bg-(--ui-bg-elevated) text-(--ui-text)'"
              @dblclick.prevent="startRename(c)"
            >
              <UIcon v-if="c.pinned" name="i-lucide-pin" class="size-3 shrink-0 text-(--ui-text-muted)" />
              <span class="truncate">{{ c.title }}</span>
            </NuxtLink>
            <UDropdownMenu v-if="renaming !== c.id" :items="itemMenu(c)" :content="{ align: 'start' }">
              <UButton
                icon="i-lucide-ellipsis"
                size="xs"
                color="neutral"
                variant="ghost"
                aria-label="Chat options"
                class="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100"
                :class="{ 'opacity-100': activeId === c.id }"
              />
            </UDropdownMenu>
          </li>
        </ul>
      </div>
    </nav>

    <!-- user -->
    <div class="p-2 border-t border-(--ui-border) shrink-0">
      <UDropdownMenu :items="userMenu" :content="{ side: 'top', align: 'start' }" :ui="{ content: 'w-60' }">
        <button class="w-full flex items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-(--ui-bg-elevated) text-left cursor-pointer">
          <UAvatar :text="initials" size="sm" class="bg-(--ui-primary)/15 text-(--ui-primary)" />
          <span class="flex-1 min-w-0">
            <span class="block text-sm font-medium truncate">{{ auth.displayName }}</span>
            <span class="block text-xs text-(--ui-text-muted) truncate">{{ auth.isAdmin ? 'Administrator' : 'Member' }}</span>
          </span>
          <UIcon name="i-lucide-chevrons-up-down" class="size-4 text-(--ui-text-muted)" />
        </button>
      </UDropdownMenu>
    </div>

    <UModal :open="!!deleting" title="Delete chat?" @update:open="(v: boolean) => { if (!v) deleting = null }">
      <template #body>
        <p class="text-sm">
          This will permanently delete <strong>{{ deleting?.title }}</strong> and all of its messages.
        </p>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="Cancel" @click="deleting = null" />
          <UButton color="error" label="Delete" @click="confirmDelete" />
        </div>
      </template>
    </UModal>
  </div>
</template>
