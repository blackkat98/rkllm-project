import { defineStore } from 'pinia'
import type { EngineStatus, ModelPublic } from '~/types/api'

const STORAGE_KEY = 'rk:new-chat-model'

export const useModelsStore = defineStore('models', {
  state: () => ({
    models: [] as ModelPublic[],
    engine: null as EngineStatus | null,
    loaded: false,
    /** model chosen in the picker for a *new* chat */
    newChatModelId: null as number | null
  }),
  getters: {
    byId: s => (id: number | null | undefined) => s.models.find(m => m.id === id) ?? null,
    /** admins: their own default first. Everyone else always gets the instance default. */
    defaultModel(s): ModelPublic | null {
      const auth = useAuthStore()
      const userDefault = auth.isAdmin ? auth.user?.settings?.default_model_id : undefined
      return s.models.find(m => m.id === userDefault)
        ?? s.models.find(m => m.is_default)
        ?? s.models[0]
        ?? null
    }
  },
  actions: {
    async fetch() {
      this.models = await api<ModelPublic[]>('/api/models')
      this.loaded = true
      // only admins choose models; the server ignores anyone else's choice anyway
      if (!useAuthStore().isAdmin) {
        this.newChatModelId = this.defaultModel?.id ?? null
        return
      }
      if (this.newChatModelId === null && import.meta.client) {
        const saved = Number(localStorage.getItem(STORAGE_KEY))
        if (saved && this.models.some(m => m.id === saved)) this.newChatModelId = saved
      }
      if (!this.models.some(m => m.id === this.newChatModelId)) this.newChatModelId = this.defaultModel?.id ?? null
    },
    async fetchEngine() {
      try {
        this.engine = await api<EngineStatus>('/api/engine/status')
        for (const m of this.models) m.loaded = m.id === this.engine.loaded_model_id
      } catch { /* ignore */ }
    },
    setNewChatModel(id: number) {
      this.newChatModelId = id
      try { localStorage.setItem(STORAGE_KEY, String(id)) } catch { /* private mode */ }
    }
  }
})
