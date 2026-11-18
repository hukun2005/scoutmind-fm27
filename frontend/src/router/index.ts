/** Route table. One route per product screen; `/players/:id` is the detail view. */

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'overview',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: '概览' },
  },
  {
    path: '/players',
    name: 'players',
    component: () => import('../views/PlayersView.vue'),
    meta: { title: '球员中心' },
  },
  {
    path: '/players/:id',
    name: 'player-detail',
    component: () => import('../views/PlayerDetailView.vue'),
    meta: { title: '球员详情' },
  },
  {
    path: '/watchlist',
    name: 'watchlist',
    component: () => import('../views/WatchlistView.vue'),
    meta: { title: '成长追踪' },
  },
  {
    path: '/scouting',
    name: 'scouting',
    component: () => import('../views/ScoutingView.vue'),
    meta: { title: '智能球探' },
  },
  {
    path: '/transfers',
    name: 'transfers',
    component: () => import('../views/TransfersView.vue'),
    meta: { title: '转会情报' },
  },
  {
    path: '/agent',
    name: 'agent',
    component: () => import('../views/AgentView.vue'),
    meta: { title: 'AI 决策中心' },
  },
  {
    path: '/data',
    name: 'data',
    component: () => import('../views/DataView.vue'),
    meta: { title: '数据与诊断' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

/** Application router (HTML5 history; the dev server rewrites unknown paths). */
export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · ScoutMind` : 'ScoutMind 工作台'
})
