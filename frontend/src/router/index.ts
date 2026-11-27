/** Route table. One route per product screen; `/players/:id` is the detail view. */

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'overview',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: '首页' },
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
    path: '/compare',
    name: 'compare',
    component: () => import('../views/CompareView.vue'),
    meta: { title: '球员对比' },
  },
  {
    path: '/watchlist',
    name: 'watchlist',
    component: () => import('../views/WatchlistView.vue'),
    meta: { title: '关注名单' },
  },
  {
    path: '/squad',
    name: 'squad',
    component: () => import('../views/SquadView.vue'),
    meta: { title: '阵容分析' },
  },
  {
    path: '/scouting',
    name: 'scouting',
    component: () => import('../views/ScoutingView.vue'),
    meta: { title: '角色球探' },
  },
  {
    path: '/recruitment',
    name: 'recruitment',
    component: () => import('../views/RecruitmentView.vue'),
    meta: { title: '引援中心' },
  },
  {
    path: '/development',
    name: 'development',
    component: () => import('../views/DevelopmentView.vue'),
    meta: { title: '球员发展' },
  },
  {
    path: '/performance',
    name: 'performance',
    component: () => import('../views/PerformanceView.vue'),
    meta: { title: '表现分析' },
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
    meta: { title: 'AI 球探助手' },
  },
  {
    path: '/director',
    name: 'director',
    component: () => import('../views/DirectorView.vue'),
    meta: { title: 'AI 足球总监' },
  },
  {
    path: '/identity',
    name: 'identity',
    component: () => import('../views/IdentityResolutionView.vue'),
    meta: { title: '身份复核' },
  },
  {
    path: '/identity-center',
    name: 'identity-center',
    component: () => import('../views/PlayerIdentityCenterView.vue'),
    meta: { title: '身份中心' },
  },
  {
    path: '/save-identity',
    name: 'save-identity',
    component: () => import('../views/SaveIdentityView.vue'),
    meta: { title: '存档身份' },
  },
  {
    path: '/unresolved',
    name: 'unresolved',
    component: () => import('../views/UnresolvedPlayerView.vue'),
    meta: { title: '待确认球员' },
  },
  {
    path: '/data',
    name: 'data',
    component: () => import('../views/DataView.vue'),
    meta: { title: '数据中心' },
  },
  {
    path: '/governance',
    name: 'governance',
    component: () => import('../views/GovernanceView.vue'),
    meta: { title: '数据治理中心' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../views/SettingsView.vue'),
    meta: { title: '系统设置' },
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
