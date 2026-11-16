// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },

  modules: ['@nuxt/ui'],
  css: ['~/assets/css/main.css'],

  // Panel behind a login: no SEO, simpler deploy (static files + API)
  ssr: false,

  app: {
    head: {
      title: 'Grupo Enriquecedor · Financeiro',
      htmlAttrs: { lang: 'pt-BR' },
      link: [
        { rel: 'icon', href: '/favicon.ico', sizes: '32x32' },
        { rel: 'icon', href: '/favicon.svg', type: 'image/svg+xml' },
        { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' },
        { rel: 'manifest', href: '/site.webmanifest' },
      ],
      meta: [{ name: 'theme-color', content: '#000000' }],
    },
  },

  // Sora is dark-first: dark by default, light available (choice saved in localStorage)
  colorMode: { preference: 'dark', fallback: 'dark' },

  runtimeConfig: {
    public: {
      // Same-origin in dev through the proxy below; set NUXT_PUBLIC_API_BASE in production if needed
      apiBase: '',
    },
  },

  // Dev: /api -> Django, so the browser sees one origin (no CORS)
  nitro: {
    devProxy: {
      '/api': { target: 'http://localhost:8000/api', changeOrigin: true },
    },
  },
})
