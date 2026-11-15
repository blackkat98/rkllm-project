import MarkdownIt from 'markdown-it'
import type { HighlighterCore } from 'shiki/core'

const LANGS = [
  'python', 'javascript', 'typescript', 'tsx', 'jsx', 'json', 'bash', 'shellscript', 'yaml', 'toml', 'ini',
  'html', 'css', 'vue', 'sql', 'c', 'cpp', 'java', 'kotlin', 'go', 'rust', 'php', 'csharp', 'markdown',
  'dockerfile', 'diff', 'xml', 'lua', 'ruby', 'swift'
] as const
const ALIASES: Record<string, string> = {
  py: 'python', js: 'javascript', ts: 'typescript', sh: 'bash', shell: 'bash', zsh: 'bash', console: 'bash',
  yml: 'yaml', md: 'markdown', 'c++': 'cpp', cs: 'csharp', rs: 'rust', golang: 'go', docker: 'dockerfile', kt: 'kotlin'
}

const ready = ref(false)
let highlighter: HighlighterCore | null = null
let loading: Promise<void> | null = null

function loadHighlighter() {
  if (loading) return loading
  loading = (async () => {
    const [{ createHighlighterCore }, { createJavaScriptRegexEngine }, { bundledLanguages }, { bundledThemes }] = await Promise.all([
      import('shiki/core'),
      import('shiki/engine/javascript'),
      import('shiki/langs'),
      import('shiki/themes')
    ])
    highlighter = await createHighlighterCore({
      themes: [bundledThemes['github-light'](), bundledThemes['github-dark']()],
      langs: LANGS.map(l => bundledLanguages[l]()),
      engine: createJavaScriptRegexEngine()
    })
    ready.value = true
  })().catch((e) => {
    console.warn('syntax highlighter unavailable', e)
  })
  return loading
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const md = new MarkdownIt({ html: false, linkify: true, breaks: true, typographer: false })

md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]!
  const raw = (token.info || '').trim().split(/\s+/)[0]?.toLowerCase() || ''
  const lang = ALIASES[raw] || raw
  let body: string
  if (highlighter && lang && highlighter.getLoadedLanguages().includes(lang)) {
    body = highlighter.codeToHtml(token.content.replace(/\n$/, ''), {
      lang,
      themes: { light: 'github-light', dark: 'github-dark' },
      defaultColor: false
    })
  } else {
    body = `<pre><code>${escapeHtml(token.content.replace(/\n$/, ''))}</code></pre>`
  }
  return `<div class="code-block"><div class="code-header"><span>${escapeHtml(raw || 'text')}</span>`
    + `<button type="button" data-copy>Copy</button></div>${body}</div>`
}

const defaultLinkOpen = md.renderer.rules.link_open
  ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx]!.attrSet('target', '_blank')
  tokens[idx]!.attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

export function useMarkdown() {
  if (import.meta.client) loadHighlighter()
  return {
    ready,
    render(text: string): string {
      void ready.value // re-render once the highlighter arrives
      return md.render(text)
    }
  }
}

/** Split a reasoning model's "<think>…</think>" preamble from the answer. */
export function splitThinking(content: string): { thinking: string | null, answer: string, thinkingOpen: boolean } {
  const m = content.match(/^\s*<think>([\s\S]*?)(<\/think>|$)/)
  if (!m) return { thinking: null, answer: content, thinkingOpen: false }
  return {
    thinking: m[1]!.trim(),
    answer: content.slice(m[0].length).replace(/^\s+/, ''),
    thinkingOpen: m[2] !== '</think>'
  }
}
