import { defineStore } from 'pinia'
import type { Conversation } from '~/types/api'

export interface ConversationGroup {
  label: string
  items: Conversation[]
}

export const useConversationsStore = defineStore('conversations', {
  state: () => ({
    items: [] as Conversation[],
    loaded: false,
    search: '',
    searchResults: null as Conversation[] | null
  }),
  getters: {
    groups(s): ConversationGroup[] {
      const list = s.searchResults ?? s.items
      const now = new Date()
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
      const day = 86400000
      const buckets: Record<string, Conversation[]> = {
        Pinned: [], Today: [], Yesterday: [], 'Previous 7 days': [], 'Previous 30 days': [], Older: []
      }
      for (const c of list) {
        const t = new Date(c.updated_at).getTime()
        if (c.pinned && !s.searchResults) buckets.Pinned!.push(c)
        else if (t >= startOfToday) buckets.Today!.push(c)
        else if (t >= startOfToday - day) buckets.Yesterday!.push(c)
        else if (t >= startOfToday - 7 * day) buckets['Previous 7 days']!.push(c)
        else if (t >= startOfToday - 30 * day) buckets['Previous 30 days']!.push(c)
        else buckets.Older!.push(c)
      }
      return Object.entries(buckets).filter(([, v]) => v.length).map(([label, items]) => ({ label, items }))
    }
  },
  actions: {
    async fetch() {
      this.items = await api<Conversation[]>('/api/conversations', { query: { limit: 300 } })
      this.loaded = true
    },
    async runSearch(q: string) {
      this.search = q
      if (!q.trim()) {
        this.searchResults = null
        return
      }
      const res = await api<Conversation[]>('/api/conversations', { query: { q, limit: 100 } })
      if (this.search === q) this.searchResults = res
    },
    upsert(c: Conversation) {
      const i = this.items.findIndex(x => x.id === c.id)
      if (i >= 0) this.items[i] = { ...this.items[i], ...c }
      else this.items.unshift(c)
      this.sort()
    },
    touch(id: string) {
      const c = this.items.find(x => x.id === id)
      if (c) {
        c.updated_at = new Date().toISOString()
        this.sort()
      }
    },
    sort() {
      this.items.sort((a, b) => (Number(b.pinned) - Number(a.pinned)) || b.updated_at.localeCompare(a.updated_at))
    },
    async update(id: string, patch: Partial<Pick<Conversation, 'title' | 'pinned' | 'archived' | 'model_id' | 'system_prompt'>>) {
      const c = await api<Conversation>(`/api/conversations/${id}`, { method: 'PATCH', body: patch })
      if (c.archived) this.items = this.items.filter(x => x.id !== id)
      else this.upsert(c)
      return c
    },
    async remove(id: string) {
      await api(`/api/conversations/${id}`, { method: 'DELETE' })
      this.items = this.items.filter(x => x.id !== id)
      if (this.searchResults) this.searchResults = this.searchResults.filter(x => x.id !== id)
    },
    async waitForTitle(id: string) {
      try {
        const r = await api<{ title: string, generated: boolean }>(`/api/conversations/${id}/title`, { query: { wait: 30 } })
        const c = this.items.find(x => x.id === id)
        if (c) c.title = r.title
        const chat = useChatStore()
        if (chat.conversation?.id === id) chat.conversation.title = r.title
      } catch { /* ignore */ }
    }
  }
})
