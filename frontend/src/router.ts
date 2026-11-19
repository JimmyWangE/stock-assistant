import { createRouter, createWebHistory } from 'vue-router'

import { ensureUserLoaded } from './auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    {
      // 登录后的页面共用顶栏和指数详情抽屉
      path: '/',
      component: () => import('./views/ShellLayout.vue'),
      children: [
        // 登录后首先看到当天的市场概览
        { path: '', name: 'home', component: () => import('./views/DashboardView.vue') },
        // 新对话和已有会话共用同一个页面，会话 id 在网址里，可直接收藏或刷新。
        // 新对话可带 ?q=问题，进入后自动提问（概览页、指数详情里的"AI 解读"用）
        { path: 'chat', name: 'new-chat', component: () => import('./views/ChatView.vue') },
        { path: 'c/:id', name: 'chat', component: () => import('./views/ChatView.vue') },
      ],
    },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

// 未登录访问任何页面都跳到登录页（验收 A1）；已登录则不再停留在登录页
router.beforeEach(async (to) => {
  const user = await ensureUserLoaded()
  if (to.name === 'login') return user ? { path: '/' } : true
  if (!user) return { name: 'login', query: to.path === '/' ? {} : { redirect: to.fullPath } }
  return true
})
