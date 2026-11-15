<script setup lang="ts">
const { collapsed, mobileOpen } = useSidebar()
const route = useRoute()
watch(() => route.fullPath, () => { mobileOpen.value = false })

const conversations = useConversationsStore()
const models = useModelsStore()
onMounted(() => {
  if (!conversations.loaded) void conversations.fetch()
  if (!models.loaded) void models.fetch().then(() => models.fetchEngine())
})
</script>

<template>
  <div class="flex h-dvh overflow-hidden">
    <!-- desktop sidebar -->
    <aside
      class="hidden md:flex flex-col shrink-0 border-r border-(--ui-border) bg-(--ui-bg-muted) transition-[width] duration-200 overflow-hidden"
      :class="collapsed ? 'w-0 border-r-0' : 'w-68'"
    >
      <AppSidebar />
    </aside>

    <!-- mobile drawer -->
    <USlideover v-model:open="mobileOpen" side="left" :ui="{ content: 'max-w-[85vw] w-72' }" class="md:hidden">
      <template #content>
        <div class="flex flex-col h-full bg-(--ui-bg-muted)">
          <AppSidebar />
        </div>
      </template>
    </USlideover>

    <main class="flex-1 min-w-0 flex flex-col">
      <slot />
    </main>
  </div>
</template>
