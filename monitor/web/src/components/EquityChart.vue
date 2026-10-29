<script setup>
// 누적 수익률(Agent vs 코스피)과 낙폭. 축 범위는 데이터에 맞춰 자동으로 잡는다.
import { computed } from 'vue'

const props = defineProps({ series: { type: Array, required: true } })
const W = 800, X0 = 50, X1 = 790, TOP = 12, H = 228

function niceStep(span) {
  const raw = span / 5
  const p = 10 ** Math.floor(Math.log10(raw))
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw)
}

const chart = computed(() => {
  const s = props.series
  if (s.length < 2) return null
  const vals = s.flatMap((d) => [d.agent, d.kospi]).filter((v) => v !== null)
  const step = niceStep(Math.max(...vals) - Math.min(...vals) || 1)
  const max = Math.ceil(Math.max(...vals, 0) / step) * step
  const min = Math.floor(Math.min(...vals, 0) / step) * step
  const x = (i) => X0 + (i * (X1 - X0)) / (s.length - 1)
  const y = (v) => TOP + ((max - v) / (max - min)) * H
  const pts = (key) => s.map((d, i) => (d[key] === null ? null : `${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`)).filter(Boolean).join(' ')
  const grid = []
  for (let v = max; v >= min - 1e-9; v -= step) grid.push({ y: y(v), label: v > 0 ? `+${+v.toFixed(2)}` : v < 0 ? `−${+(-v).toFixed(2)}` : '0' })
  const ticks = Array.from({ length: 6 }, (_, k) => Math.round((k * (s.length - 1)) / 5)).map((i, k) => ({ x: x(i), label: s[i].date.slice(5).replace('-', '/'), anchor: k === 0 ? 'start' : k === 5 ? 'end' : 'middle' }))
  const ddMin = Math.min(...s.map((d) => d.dd), -1)
  const ddFloor = Math.floor(ddMin)
  const dy = (v) => 4 + (v / ddFloor) * 48
  const ddPts = s.map((d, i) => `${x(i).toFixed(1)},${dy(d.dd).toFixed(1)}`).join(' ')
  const last = s[s.length - 1]
  return {
    grid, ticks, agent: pts('agent'), kospi: pts('kospi'),
    area: `${X0},${y(0).toFixed(1)} ${pts('agent')} ${X1},${y(0).toFixed(1)}`,
    lastX: x(s.length - 1), lastY: y(last.agent),
    dd: ddPts, ddArea: `${X0},4 ${ddPts} ${X1},4`, ddFloor, ddMin: Math.min(...s.map((d) => d.dd)),
    aria: `Agent 누적 수익률 ${last.agent?.toFixed(2)}%, 코스피 ${last.kospi?.toFixed(2)}%`,
  }
})
</script>

<template>
  <div v-if="chart" class="wrap">
    <svg :viewBox="`0 0 ${W} 270`" role="img" :aria-label="chart.aria">
      <g v-for="g in chart.grid" :key="g.y">
        <line x1="44" :x2="W" :y1="g.y" :y2="g.y" stroke="#ECEEF2" />
        <text x="36" :y="g.y + 4" class="axis" text-anchor="end">{{ g.label }}</text>
      </g>
      <polyline :points="chart.kospi" fill="none" stroke="#6B7584" stroke-width="1.6" stroke-dasharray="5 4" />
      <polygon :points="chart.area" fill="var(--accent)" fill-opacity="0.08" />
      <polyline :points="chart.agent" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linejoin="round" />
      <circle :cx="chart.lastX" :cy="chart.lastY" r="4" fill="var(--accent)" />
      <text v-for="t in chart.ticks" :key="t.x" :x="t.x" y="266" class="axis" :text-anchor="t.anchor">{{ t.label }}</text>
    </svg>
    <div class="lbl" style="margin: 4px 0">낙폭 (고점 대비, 최저 {{ chart.ddMin.toFixed(2).replace('-', '−') }}%)</div>
    <svg :viewBox="`0 0 ${W} 56`" role="img" :aria-label="`낙폭 최저 ${chart.ddMin.toFixed(2)}%`">
      <line x1="44" :x2="W" y1="4" y2="4" stroke="#ECEEF2" />
      <polygon :points="chart.ddArea" fill="var(--down)" fill-opacity="0.18" />
      <polyline :points="chart.dd" fill="none" stroke="var(--down)" stroke-width="1.4" />
      <text x="36" y="8" class="axis" text-anchor="end">0</text>
      <text x="36" y="54" class="axis" text-anchor="end">−{{ -chart.ddFloor }}</text>
    </svg>
  </div>
  <div v-else class="empty">표시할 날짜가 부족합니다</div>
</template>

<style scoped>
svg { width: 100%; height: auto; display: block; }
.axis { fill: #6B7584; font-size: 11px; font-family: var(--mono); }
</style>
