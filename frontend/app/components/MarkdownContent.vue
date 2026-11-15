<script setup lang="ts">
const props = defineProps<{ content: string, streaming?: boolean }>()
const { render } = useMarkdown()
const html = computed(() => render(props.content))

async function onClick(e: MouseEvent) {
  const btn = (e.target as HTMLElement).closest('button[data-copy]') as HTMLButtonElement | null
  if (!btn) return
  const code = btn.closest('.code-block')?.querySelector('pre')?.textContent ?? ''
  try {
    await navigator.clipboard.writeText(code)
    btn.textContent = 'Copied'
    setTimeout(() => { btn.textContent = 'Copy' }, 1500)
  } catch { /* clipboard blocked (http) */ }
}
</script>

<template>
  <!-- markdown-it runs with html:false, so model output cannot inject markup -->
  <div class="md" :class="{ 'streaming-caret': streaming }" @click="onClick" v-html="html" />
</template>
