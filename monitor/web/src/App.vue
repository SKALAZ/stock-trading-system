<script setup>
import { onMounted, onUnmounted } from 'vue'
import { store } from './store.js'

const nav = [
  { to: '/', label: '대시보드', exact: true },
  { to: '/decisions', label: '판단 추적' },
  { to: '/principles', label: '원칙·검정' },
  { to: '/experiments', label: '가드레일 실험' },
]

// 새 실행(백테스트·모의투자)이 생기면 목록에 나타나도록 30초마다 다시 읽는다
let timer
onMounted(() => {
  store.loadRuns()
  timer = setInterval(() => store.loadRuns(), 30000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <header class="top">
    <div class="bar">
      <RouterLink to="/" class="brand">
        <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
          <rect width="28" height="28" rx="8" fill="#EEF0F3" />
          <path d="M6 18 L11 13 L15 16 L22 8" stroke="var(--accent)" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round" />
          <circle cx="22" cy="8" r="2.2" fill="var(--accent)" />
        </svg>
        <span>Agent Monitor</span>
      </RouterLink>
      <nav aria-label="주요 화면" class="nav">
        <RouterLink v-for="n in nav" :key="n.to" :to="n.to" v-slot="{ href, navigate, isActive, isExactActive }" custom>
          <a :href="href" @click="navigate" :class="{ on: n.exact ? isExactActive : isActive }"
             :aria-current="(n.exact ? isExactActive : isActive) ? 'page' : undefined">{{ n.label }}</a>
        </RouterLink>
      </nav>
      <div class="right">
        <template v-if="store.run">
          <span class="pill mode" :style="store.run.mode === 'live' ? 'background: var(--buy-bg); color: var(--buy-fg); border-color: transparent' : ''">
            <span class="dot" :style="store.run.mode === 'live' ? 'background: var(--up)' : ''" />{{ store.run.mode.toUpperCase() }} · run {{ store.run.run_id }}</span>
          <span v-if="store.run.guardrails === 'off'" class="pill" style="background: var(--clip-bg); color: var(--clip)">가드레일 기록만 (OFF)</span>
        </template>
        <label class="pick">실행
          <select :value="store.runId" @change="store.select(Number($event.target.value))">
            <option v-for="r in store.runs" :key="r.run_id" :value="r.run_id">run {{ r.run_id }} · {{ r.label }}</option>
          </select>
        </label>
      </div>
    </div>
  </header>
  <div v-if="store.error" class="page"><div class="card empty">API에 연결하지 못했습니다: {{ store.error }}</div></div>
  <RouterView v-else-if="store.runId" :key="store.runId" />
  <div v-else class="page"><div class="card empty">기록된 실행이 없습니다. <span class="num">python -m trader backtest</span>로 먼저 실행하세요.</div></div>
</template>

<style scoped>
.top { border-bottom: 1px solid var(--line); background: var(--surface); position: sticky; top: 0; z-index: 10; }
.bar { max-width: 1440px; margin: 0 auto; padding: 14px 32px; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 28px; }
.brand { display: flex; align-items: center; gap: 10px; color: var(--text); font-weight: 700; font-size: 15px; letter-spacing: -.01em; }
.nav { display: flex; flex-wrap: wrap; gap: 4px; }
.nav a { padding: 8px 14px; border-radius: 999px; color: var(--text-3); }
.nav a.on { background: var(--active); color: var(--text); font-weight: 600; }
.right { margin-left: auto; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.mode { border: 1px solid var(--line-3); color: var(--text-2); font-weight: 500; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--pass); }
.pick { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
.pick select { background: var(--surface); color: var(--text); border: 1px solid var(--line-3); border-radius: 8px; padding: 6px 8px; font: inherit; max-width: 260px; }
@media (max-width: 640px) { .bar { padding: 12px 16px; } .right { margin-left: 0; } }
</style>
