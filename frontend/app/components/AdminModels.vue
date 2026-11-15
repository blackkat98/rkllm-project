<script setup lang="ts">
import type { EngineStatus, ModelAdmin } from '~/types/api'

const toast = useToast()
const publicModels = useModelsStore()
const items = ref<ModelAdmin[]>([])
const engine = ref<EngineStatus | null>(null)
const loading = ref(true)
const scanning = ref(false)

async function load() {
  const [m, e] = await Promise.all([
    api<ModelAdmin[]>('/api/admin/models'),
    api<EngineStatus>('/api/engine/status')
  ])
  items.value = m
  engine.value = e
  loading.value = false
}

async function rescan() {
  scanning.value = true
  try {
    const r = await api<{ added: number, updated: number, missing: number, total: number }>('/api/admin/models/rescan', { method: 'POST' })
    toast.add({ title: 'Scan complete', description: `${r.total} files · ${r.added} new · ${r.missing} missing`, color: 'success' })
    await load()
  } finally {
    scanning.value = false
  }
}

async function patch(m: ModelAdmin, body: Record<string, unknown>) {
  try {
    const updated = await api<ModelAdmin>(`/api/admin/models/${m.id}`, { method: 'PATCH', body })
    Object.assign(m, updated)
    if ('keep_loaded' in body && body.keep_loaded) items.value.forEach((o) => { if (o.id !== m.id) o.keep_loaded = false })
    void publicModels.fetch()
  } catch (e) {
    toast.add({ title: 'Update failed', description: errorMessage(e), color: 'error' })
    await load()
  }
}

async function makeDefault(m: ModelAdmin) {
  try {
    await api('/api/admin/settings', { method: 'PATCH', body: { default_model_id: m.id } })
    items.value.forEach(o => (o.is_default = o.id === m.id))
    void publicModels.fetch()
  } catch (e) {
    toast.add({ title: 'Could not set default', description: errorMessage(e), color: 'error' })
  }
}

async function resetStatus(m: ModelAdmin) {
  Object.assign(m, await api<ModelAdmin>(`/api/admin/models/${m.id}/reset-status`, { method: 'POST' }))
}

async function unload() {
  try {
    await api('/api/admin/engine/unload', { method: 'POST' })
    toast.add({ title: 'Model unloaded', color: 'success' })
    setTimeout(load, 500)
  } catch (e) {
    toast.add({ title: 'Could not unload', description: errorMessage(e), color: 'warning' })
  }
}

// ---- edit modal ----
const editing = ref<ModelAdmin | null>(null)
const form = reactive({
  display_name: '', family: 'chatml', max_context_len: 4096, max_new_tokens: 2048, sort_order: 100,
  temperature: undefined as number | undefined, top_p: undefined as number | undefined,
  top_k: undefined as number | undefined, repeat_penalty: undefined as number | undefined
})
const families = ['chatml', 'deepseek', 'gemma', 'llama3', 'llama2', 'phi3'].map(f => ({ label: f, value: f }))
function openEdit(m: ModelAdmin) {
  editing.value = m
  Object.assign(form, {
    display_name: m.display_name, family: m.family, max_context_len: m.max_context_len,
    max_new_tokens: m.max_new_tokens, sort_order: m.sort_order,
    temperature: m.sampling.temperature, top_p: m.sampling.top_p, top_k: m.sampling.top_k,
    repeat_penalty: m.sampling.repeat_penalty
  })
}
async function saveEdit() {
  const m = editing.value
  if (!m) return
  await patch(m, {
    display_name: form.display_name, family: form.family, max_context_len: form.max_context_len,
    max_new_tokens: form.max_new_tokens, sort_order: form.sort_order,
    sampling: { temperature: form.temperature, top_p: form.top_p, top_k: form.top_k, repeat_penalty: form.repeat_penalty }
  })
  editing.value = null
}

const statusColor = (s: string) => ({ ok: 'success', missing: 'neutral', too_large: 'error', over_ram: 'error' } as const)[s as 'ok'] ?? 'neutral'
const statusLabel = (s: string) => ({ ok: 'OK', missing: 'Missing', too_large: 'Too large', over_ram: 'Over RAM limit' } as Record<string, string>)[s] ?? s
const gb = (b: number) => `${(b / 1024 ** 3).toFixed(2)} GB`

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3 rounded-xl border border-(--ui-border) p-3">
      <UIcon name="i-lucide-cpu" class="size-5 text-(--ui-primary)" />
      <div class="flex-1 min-w-0 text-sm">
        <p class="font-medium">
          NPU: {{ engine?.loaded_model_name ?? 'no model loaded' }}
          <UBadge v-if="engine?.busy" color="warning" variant="subtle" size="sm" class="ml-1">busy · {{ engine.current_kind }}</UBadge>
        </p>
        <p class="text-(--ui-text-muted)">
          Queue: {{ engine?.queue_length ?? 0 }} · one model in memory at a time (8 GB board)
        </p>
      </div>
      <UButton icon="i-lucide-power" color="neutral" variant="outline" label="Unload" :disabled="!engine?.loaded_model_id" @click="unload" />
      <UButton icon="i-lucide-folder-sync" color="neutral" label="Rescan folder" :loading="scanning" @click="rescan" />
    </div>

    <p class="text-xs text-(--ui-text-muted)">
      Copy <code>.rkllm</code> files (RK3588, runtime 1.2.0, ≤2B parameters) into the models folder, then rescan.
      New models start disabled. Sampling settings are applied when a model loads.
    </p>

    <div v-if="loading" class="space-y-3">
      <USkeleton v-for="i in 3" :key="i" class="h-28 w-full" />
    </div>
    <div v-else-if="!items.length" class="rounded-xl border border-dashed border-(--ui-border-accented) p-10 text-center text-sm text-(--ui-text-muted)">
      No <code>.rkllm</code> files found in the models folder.
    </div>

    <div
      v-for="m in items"
      :key="m.id"
      class="rounded-xl border border-(--ui-border) p-4"
      :class="{ 'opacity-60': m.status === 'missing' }"
    >
      <div class="flex flex-wrap items-start gap-3">
        <div class="flex-1 min-w-60">
          <div class="flex items-center gap-2 flex-wrap">
            <h3 class="font-medium">{{ m.display_name }}</h3>
            <UBadge :color="statusColor(m.status)" variant="subtle" size="sm">{{ statusLabel(m.status) }}</UBadge>
            <UBadge v-if="m.is_default" color="primary" variant="subtle" size="sm" icon="i-lucide-star">Default</UBadge>
            <UBadge v-if="m.loaded" color="success" variant="soft" size="sm" icon="i-lucide-zap">Loaded</UBadge>
          </div>
          <p class="text-xs text-(--ui-text-muted) mt-1 break-all">{{ m.filename }}</p>
          <p class="text-xs text-(--ui-text-muted) mt-1">
            {{ gb(m.file_size) }}
            <template v-if="m.param_hint_b"> · ~{{ m.param_hint_b }}B (from filename)</template>
            · {{ m.family }} · {{ m.max_context_len }} ctx
            · RAM {{ m.measured_ram_mb ? `${m.measured_ram_mb} MB measured` : `~${m.est_ram_mb} MB est.` }}
            <template v-if="m.tokenizer_path"> · exact token counts</template>
          </p>
          <p v-if="m.status_detail" class="text-xs text-(--ui-error) mt-1">{{ m.status_detail }}</p>
          <p v-for="w in m.warnings" :key="w" class="text-xs text-(--ui-warning) mt-1 flex gap-1">
            <UIcon name="i-lucide-triangle-alert" class="size-3.5 mt-px shrink-0" />{{ w }}
          </p>
        </div>

        <div class="flex items-center gap-4">
          <USwitch :model-value="m.enabled" label="Enabled" :disabled="m.status !== 'ok'" @update:model-value="(v) => patch(m, { enabled: v })" />
          <UTooltip text="Preload at startup and never unload when idle (only one model)">
            <USwitch :model-value="m.keep_loaded" label="Keep loaded" :disabled="!m.enabled" @update:model-value="(v) => patch(m, { keep_loaded: v })" />
          </UTooltip>
          <UDropdownMenu :items="[[
            { label: 'Edit settings', icon: 'i-lucide-settings-2', onSelect: () => openEdit(m) },
            { label: 'Make default', icon: 'i-lucide-star', disabled: !m.enabled || m.is_default, onSelect: () => makeDefault(m) },
            ...(m.status === 'over_ram' ? [{ label: 'Reset RAM flag', icon: 'i-lucide-rotate-ccw', onSelect: () => resetStatus(m) }] : [])
          ]]">
            <UButton icon="i-lucide-ellipsis-vertical" color="neutral" variant="ghost" aria-label="Model actions" />
          </UDropdownMenu>
        </div>
      </div>
    </div>

    <UModal :open="!!editing" :title="`Edit ${editing?.display_name ?? ''}`" @update:open="(v: boolean) => { if (!v) editing = null }">
      <template #body>
        <form id="model-form" class="grid grid-cols-2 gap-4" @submit.prevent="saveEdit">
          <UFormField label="Display name" class="col-span-2">
            <UInput v-model="form.display_name" class="w-full" />
          </UFormField>
          <UFormField label="Chat template" description="Must match how the model was trained.">
            <USelect v-model="form.family" :items="families" class="w-full" />
          </UFormField>
          <UFormField label="Sort order">
            <UInputNumber v-model="form.sort_order" :min="0" class="w-full" />
          </UFormField>
          <UFormField label="Context length" description="Must be ≤ the value used at conversion.">
            <UInputNumber v-model="form.max_context_len" :min="512" :max="16384" :step="512" class="w-full" />
          </UFormField>
          <UFormField label="Max new tokens">
            <UInputNumber v-model="form.max_new_tokens" :min="16" :max="8192" :step="64" class="w-full" />
          </UFormField>
          <UFormField label="Temperature" hint="default 0.8">
            <UInputNumber v-model="form.temperature" :min="0" :max="2" :step="0.05" :format-options="{ maximumFractionDigits: 2 }" class="w-full" />
          </UFormField>
          <UFormField label="Top-p" hint="default 0.9">
            <UInputNumber v-model="form.top_p" :min="0.05" :max="1" :step="0.05" :format-options="{ maximumFractionDigits: 2 }" class="w-full" />
          </UFormField>
          <UFormField label="Top-k" hint="default 20">
            <UInputNumber v-model="form.top_k" :min="1" :max="200" class="w-full" />
          </UFormField>
          <UFormField label="Repeat penalty" hint="default 1.1">
            <UInputNumber v-model="form.repeat_penalty" :min="0.5" :max="2" :step="0.05" :format-options="{ maximumFractionDigits: 2 }" class="w-full" />
          </UFormField>
        </form>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton color="neutral" variant="ghost" label="Cancel" @click="editing = null" />
          <UButton type="submit" form="model-form" color="neutral" label="Save" />
        </div>
      </template>
    </UModal>
  </div>
</template>
