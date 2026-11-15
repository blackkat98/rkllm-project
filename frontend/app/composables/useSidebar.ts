const KEY = 'rk:sidebar-collapsed'

/** Desktop: collapsible sidebar (remembered). Mobile: slide-over drawer. */
export function useSidebar() {
  const collapsed = useState('sidebar-collapsed', () => {
    if (!import.meta.client) return false
    try { return localStorage.getItem(KEY) === '1' } catch { return false }
  })
  const mobileOpen = useState('sidebar-mobile-open', () => false)

  function toggle() {
    if (import.meta.client && window.matchMedia('(max-width: 767px)').matches) {
      mobileOpen.value = !mobileOpen.value
      return
    }
    collapsed.value = !collapsed.value
    try { localStorage.setItem(KEY, collapsed.value ? '1' : '0') } catch { /* ignore */ }
  }
  return { collapsed, mobileOpen, toggle }
}
