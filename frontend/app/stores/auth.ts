import { defineStore } from 'pinia'
import type { User } from '~/types/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    loaded: false,
    openSignup: false,
    appName: 'RKLLM Chat'
  }),
  getters: {
    isAdmin: s => s.user?.role === 'admin',
    displayName: s => s.user?.display_name || s.user?.username || ''
  },
  actions: {
    async fetchMe() {
      try {
        this.user = await api<User>('/api/auth/me', { _retry: false })
      } catch {
        // access cookie may be expired: try the refresh cookie once
        if (await refreshSession()) {
          try {
            this.user = await api<User>('/api/auth/me')
          } catch {
            this.user = null
          }
        } else {
          this.user = null
        }
      }
      this.loaded = true
      return this.user
    },
    async fetchConfig() {
      try {
        const c = await $fetch<{ open_signup: boolean, app_name: string }>('/api/auth/config')
        this.openSignup = c.open_signup
        this.appName = c.app_name
      } catch { /* backend down */ }
    },
    async login(username: string, password: string) {
      this.user = await api<User>('/api/auth/login', { method: 'POST', body: { username, password } })
      this.loaded = true
    },
    async register(body: { username: string, email: string, password: string, display_name?: string }) {
      this.user = await api<User>('/api/auth/register', { method: 'POST', body })
      this.loaded = true
    },
    async logout(everywhere = false) {
      try {
        await api(everywhere ? '/api/auth/logout-all' : '/api/auth/logout', { method: 'POST' })
      } catch { /* ignore */ }
      this.clear()
      useConversationsStore().$reset()
      useModelsStore().$reset()
      useChatStore().reset()
      await navigateTo('/login')
    },
    async updateMe(patch: Partial<Pick<User, 'display_name' | 'email' | 'custom_instructions' | 'settings'>>) {
      this.user = await api<User>('/api/auth/me', { method: 'PATCH', body: patch })
    },
    clear() {
      this.user = null
    }
  }
})
