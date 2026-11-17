<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'

const props = defineProps<{ modelValue: number | null, disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [id: number] }>()
const models = useModelsStore()
const auth = useAuthStore()

const current = computed(() => models.byId(props.modelValue))

const items = computed<DropdownMenuItem[][]>(() => [
  [{ label: 'Models on this device', type: 'label' }],
  models.models.map(m => ({
    label: m.display_name,
    description: [
      m.param_hint_b ? `~${m.param_hint_b}B` : null,
      `${Math.round(m.max_context_len / 1024)}k context`,
      m.loaded ? 'ready on NPU' : 'loads on first use'
    ].filter(Boolean).join(' · '),
    icon: m.loaded ? 'i-lucide-zap' : 'i-lucide-box',
    type: 'checkbox' as const,
    checked: m.id === props.modelValue,
    onSelect: () => emit('update:modelValue', m.id)
  }))
])
</script>

<template>
  <!-- non-admins see the model but can't change it: the admin picks the instance default -->
  <UTooltip v-if="models.models.length && !auth.isAdmin" text="The model is chosen by your administrator">
    <span class="inline-flex items-center gap-2 px-2.5 py-1 text-sm text-(--ui-text-muted) max-w-56">
      <span class="size-2 rounded-full shrink-0" :class="current?.loaded ? 'bg-(--ui-success)' : 'bg-(--ui-border-accented)'" />
      <span class="truncate">{{ current?.display_name ?? 'No model available' }}</span>
    </span>
  </UTooltip>
  <UDropdownMenu v-else-if="models.models.length" :items="items" :content="{ align: 'start', side: 'top' }" :ui="{ content: 'w-72', itemDescription: 'text-xs' }" :disabled="disabled">
    <UButton
      color="neutral"
      variant="ghost"
      size="sm"
      trailing-icon="i-lucide-chevron-down"
      :disabled="disabled"
      class="rounded-full max-w-56"
    >
      <span class="size-2 rounded-full shrink-0" :class="current?.loaded ? 'bg-(--ui-success)' : 'bg-(--ui-border-accented)'" />
      <span class="truncate">{{ current?.display_name ?? 'Choose model' }}</span>
    </UButton>
  </UDropdownMenu>
  <UBadge v-else-if="models.loaded" color="warning" variant="subtle" size="md">
    {{ auth.isAdmin ? 'No models enabled. Open Admin → Models' : 'No models available yet' }}
  </UBadge>
</template>
