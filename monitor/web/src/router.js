import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Decisions from './views/Decisions.vue'
import Principles from './views/Principles.vue'
import Experiments from './views/Experiments.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard, meta: { title: '대시보드' } },
    { path: '/decisions/:id?', name: 'decisions', component: Decisions, meta: { title: '판단 추적' } },
    { path: '/principles', name: 'principles', component: Principles, meta: { title: '원칙·검정' } },
    { path: '/experiments', name: 'experiments', component: Experiments, meta: { title: '가드레일 실험' } },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => { document.title = `${to.meta.title} — Agent Monitor` })
