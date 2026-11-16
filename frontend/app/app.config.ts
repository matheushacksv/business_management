// SORA look applied globally to Nuxt UI components
export default defineAppConfig({
  ui: {
    colors: {
      primary: 'sky',
      neutral: 'neutral',
      success: 'emerald',
      error: 'red',
    },
    button: {
      slots: { base: 'font-medium tracking-tight cursor-pointer' },
    },
    card: {
      slots: {
        root: 'rounded-2xl bg-(--s-panel) ring ring-default shadow-(--s-shadow)',
        header: 'font-display',
      },
    },
    modal: {
      slots: {
        content: 'bg-(--s-overlay) ring ring-default rounded-2xl',
        title: 'font-display',
      },
    },
    slideover: {
      slots: {
        content: 'bg-(--s-overlay) ring ring-default',
        title: 'font-display',
      },
    },
    badge: {
      slots: { base: 'rounded-full' },
    },
    table: {
      slots: {
        th: 'text-xs font-medium text-muted uppercase tracking-wide',
        td: 'text-sm',
        tr: 'data-[selectable=true]:cursor-pointer',
      },
    },
    tabs: {
      slots: { list: 'rounded-xl ring ring-default bg-transparent' },
    },
    navigationMenu: {
      slots: { link: 'rounded-full' },
    },
  },
})
