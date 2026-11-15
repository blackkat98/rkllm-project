// SPA build: the app is behind a login, so SSR adds nothing. `nuxt generate` outputs static
// files that Caddy serves (and Caddy proxies /api + /v1 to the FastAPI backend).
export default defineNuxtConfig({
  compatibilityDate: '2026-11-01',
  ssr: false,
  devtools: { enabled: false },
  modules: ['@nuxt/ui', '@pinia/nuxt'],
  css: ['~/assets/css/main.css'],

  app: {
    head: {
      title: 'RKLLM Chat',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'description', content: 'Private chat with local LLMs on the Rockchip NPU' }
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }]
    }
  },

  // static build: bundle every icon into the client, no icon server endpoint needed
  icon: {
    provider: 'iconify',
    clientBundle: {
      scan: true,
      sizeLimitKb: 512,
      icons: [
        'lucide:check', 'lucide:chevron-down', 'lucide:chevron-right', 'lucide:chevron-left',
        'lucide:chevron-up', 'lucide:x', 'lucide:loader-circle', 'lucide:ellipsis',
        'lucide:circle-alert', 'lucide:circle-check', 'lucide:info', 'lucide:triangle-alert',
        'lucide:circle-x', 'lucide:search', 'lucide:minus', 'lucide:plus', 'lucide:eye', 'lucide:eye-off',
        'lucide:panel-left-close', 'lucide:panel-left-open', 'lucide:arrow-left', 'lucide:arrow-right',
        'lucide:arrow-up', 'lucide:arrow-down', 'lucide:grip-vertical', 'lucide:square', 'lucide:copy',
        'lucide:copy-check', 'lucide:sun', 'lucide:moon', 'lucide:monitor', 'lucide:menu', 'lucide:external-link',
        'lucide:upload', 'lucide:file', 'lucide:rotate-ccw', 'lucide:ellipsis-vertical'
      ]
    }
  },

  runtimeConfig: {
    public: {
      appName: 'RKLLM Chat'
    }
  },

  // `npm run dev`: forward API calls to the backend (docker compose dev stack, BACKEND_PORT)
  nitro: {
    devProxy: {
      '/api': { target: `http://localhost:${process.env.BACKEND_PORT || 8000}/api`, changeOrigin: true },
      '/v1': { target: `http://localhost:${process.env.BACKEND_PORT || 8000}/v1`, changeOrigin: true }
    }
  },

  typescript: {
    strict: true
  }
})
