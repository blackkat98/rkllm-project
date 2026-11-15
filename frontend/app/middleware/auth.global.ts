export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await Promise.all([auth.fetchMe(), auth.fetchConfig()])
  }
  const isPublic = to.path === '/login'
  if (!auth.user && !isPublic) return navigateTo('/login')
  if (auth.user && isPublic) return navigateTo('/')
  if (to.path.startsWith('/admin') && !auth.isAdmin) return navigateTo('/')
})
