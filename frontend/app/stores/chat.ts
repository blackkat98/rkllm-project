import { defineStore } from 'pinia'
import type { Conversation, ConversationDetail, Message, Phase } from '~/types/api'

let tempId = -1

function placeholder(role: 'user' | 'assistant', content = '', seq = 0): Message {
  return {
    id: tempId--, seq, role, content, model_id: null, status: role === 'assistant' ? 'streaming' : 'complete',
    error: null, prompt_tokens: null, completion_tokens: null, tok_per_s: null, used_kv_cache: false,
    created_at: new Date().toISOString()
  }
}

/** State of the conversation currently on screen, including the live stream. Lives in Pinia so a
 *  route change from "/" to "/c/:id" during the first reply does not lose the stream. */
export const useChatStore = defineStore('chat', {
  state: () => ({
    conversationId: null as string | null,
    conversation: null as ConversationDetail | null,
    messages: [] as Message[],
    loading: false,
    notFound: false,
    streaming: false,
    phase: 'idle' as Phase,
    queueAhead: 0,
    loadingModelName: '',
    summarizing: false,
    abort: null as AbortController | null
  }),
  getters: {
    lastAssistant: s => [...s.messages].reverse().find(m => m.role === 'assistant') ?? null,
    modelId(s): number | null {
      return s.conversation?.model_id ?? null
    }
  },
  actions: {
    reset() {
      this.abort?.abort()
      this.$reset()
    },

    newChat() {
      if (this.streaming) this.abort?.abort() // detach only; the server keeps generating & saves
      this.reset()
    },

    async load(id: string) {
      if (this.conversationId === id && (this.streaming || this.conversation)) return
      this.abort?.abort()
      this.$reset()
      this.conversationId = id
      this.loading = true
      try {
        const detail = await api<ConversationDetail>(`/api/conversations/${id}`)
        if (this.conversationId !== id) return
        this.conversation = detail
        this.messages = detail.messages
        if (detail.generating) void this.attach()
      } catch (e: unknown) {
        if ((e as { statusCode?: number })?.statusCode === 404) this.notFound = true
        else throw e
      } finally {
        this.loading = false
      }
    },

    /** Re-attach to a generation that is still running on the server (e.g. after reload). */
    async attach() {
      const id = this.conversationId
      if (!id) return
      this.beginStream()
      try {
        const attached = await streamSSE(`/api/conversations/${id}/stream`, {
          method: 'GET', signal: this.abort!.signal, onEvent: (ev, data) => this.onEvent(ev, data)
        })
        if (!attached) await this.refreshMessages()
      } catch (e) {
        if ((e as Error).name !== 'AbortError') console.error(e)
      } finally {
        this.endStream()
      }
    },

    async refreshMessages() {
      if (!this.conversationId) return
      const detail = await api<ConversationDetail>(`/api/conversations/${this.conversationId}`)
      this.conversation = detail
      this.messages = detail.messages
    },

    beginStream() {
      this.abort = new AbortController()
      this.streaming = true
      this.phase = 'queued'
      this.queueAhead = 0
      this.summarizing = false
    },

    endStream() {
      this.streaming = false
      this.phase = 'idle'
      this.abort = null
      const last = this.messages[this.messages.length - 1]
      if (last && last.role === 'assistant' && last.status === 'streaming') last.status = 'aborted'
      void useModelsStore().fetchEngine()
    },

    currentAssistant(): Message | undefined {
      const last = this.messages[this.messages.length - 1]
      return last?.role === 'assistant' ? last : undefined
    },

    onEvent(ev: string, data: any) {
      const a = this.currentAssistant()
      switch (ev) {
        case 'meta': {
          const conv = data.conversation as Conversation
          useConversationsStore().upsert(conv)
          if (this.conversation) Object.assign(this.conversation, conv)
          // swap optimistic placeholders for the stored rows
          const ui = this.messages.findIndex(m => m.id < 0 && m.role === 'user')
          if (ui >= 0) this.messages[ui] = data.user_message
          const ai = this.messages.findIndex(m => m.id < 0 && m.role === 'assistant')
          if (ai >= 0) this.messages[ai] = data.assistant_message
          else this.messages.push(data.assistant_message)
          break
        }
        case 'snapshot':
          if (a && a.status === 'streaming') a.content = data.content
          else this.messages.push({ ...placeholder('assistant', data.content), id: data.assistant_message_id })
          this.phase = data.phase === 'streaming' ? 'streaming' : (data.phase || 'queued')
          break
        case 'queued':
          this.phase = 'queued'
          this.queueAhead = data.ahead
          break
        case 'loading_model':
          this.phase = 'loading_model'
          this.loadingModelName = data.model
          break
        case 'summarizing':
          this.phase = 'summarizing'
          break
        case 'started':
          this.phase = 'started'
          break
        case 'token':
          this.phase = 'streaming'
          if (a) a.content += data.t
          break
        case 'done':
          if (a) Object.assign(a, data.message)
          break
        case 'error':
          if (a) {
            if (data.message_obj) Object.assign(a, data.message_obj)
            a.status = 'error'
            a.error = data.message
          }
          break
      }
    },

    async runStream(url: string, body: unknown) {
      this.beginStream()
      const convs = useConversationsStore()
      const id = this.conversationId!
      try {
        await streamSSE(url, { body, signal: this.abort!.signal, onEvent: (ev, data) => this.onEvent(ev, data) })
      } catch (e) {
        if ((e as Error).name === 'AbortError') return
        const a = this.currentAssistant()
        if (a && a.id < 0) {
          // request rejected before it started (e.g. 409/503): show the reason inline
          a.status = 'error'
          a.error = (e as Error).message
        } else {
          useToast().add({ title: 'Generation failed', description: (e as Error).message, color: 'error' })
        }
      } finally {
        this.endStream()
        convs.touch(id)
      }
    },

    /** Send a message. Creates the conversation first when on the "new chat" screen. */
    async send(content: string, modelId: number | null): Promise<string | null> {
      const text = content.trim()
      if (!text || this.streaming) return null
      const convs = useConversationsStore()
      if (!this.conversationId) {
        const conv = await api<Conversation>('/api/conversations', { method: 'POST', body: { model_id: modelId } })
        convs.upsert(conv)
        this.conversationId = conv.id
        this.conversation = { ...conv, messages: [], summary: null, summary_upto_seq: 0, generating: false }
      }
      const id = this.conversationId
      const isFirst = this.messages.length === 0
      this.messages.push(placeholder('user', text), placeholder('assistant'))
      const run = this.runStream(`/api/conversations/${id}/messages`, { content: text, model_id: modelId })
      if (isFirst) {
        void run.then(() => convs.waitForTitle(id))
      }
      return id
    },

    async stop() {
      if (!this.conversationId) return
      try {
        await api(`/api/conversations/${this.conversationId}/stop`, { method: 'POST' })
      } catch { /* ignore */ }
    },

    async regenerate(modelId: number | null) {
      if (!this.conversationId || this.streaming) return
      const last = this.messages[this.messages.length - 1]
      if (last?.role === 'assistant') this.messages.pop()
      this.messages.push(placeholder('assistant'))
      await this.runStream(`/api/conversations/${this.conversationId}/regenerate`, { model_id: modelId })
    },

    async edit(messageId: number, content: string, modelId: number | null) {
      if (!this.conversationId || this.streaming) return
      const idx = this.messages.findIndex(m => m.id === messageId)
      if (idx < 0) return
      this.messages[idx] = { ...this.messages[idx]!, content }
      this.messages.splice(idx + 1)
      this.messages.push(placeholder('assistant'))
      await this.runStream(`/api/conversations/${this.conversationId}/messages/${messageId}/edit`, { content, model_id: modelId })
    }
  }
})
