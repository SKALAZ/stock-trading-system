<script setup>
// ③ 원칙·검정 — "어떤 원칙을 쓸 수 있나": 검정을 통과한 원칙만 GPT가 쓸 수 있다
import { computed, ref } from 'vue'
import { api } from '../api.js'
import { pct } from '../format.js'
import Chip from '../components/Chip.vue'

const data = ref(null), error = ref(null), copied = ref(false)
api.principles().then((d) => (data.value = d)).catch((e) => (error.value = e.message))

const counts = computed(() => {
  const c = { passed: 0, rejected: 0, draft: 0 }
  for (const p of data.value?.principles || []) c[p.status] = (c[p.status] || 0) + 1
  return c
})
const cost = computed(() => {
  const c = data.value?.costs
  return c ? 2 * c.commission + c.sell_tax + 2 * c.slippage : null
})

// 평균과 95% 신뢰구간을 0 기준선 위에 그린다
function ciView(t) {
  const lo = Math.min(t.ci_low, t.mean_excess, 0), hi = Math.max(t.ci_high, t.mean_excess, 0)
  const pad = (hi - lo) * 0.15 || 0.005
  const a = lo - pad, b = hi + pad, L = 20, R = 740
  const x = (v) => L + ((v - a) / (b - a)) * (R - L)
  const step = (b - a) / 6
  return {
    zero: x(0), mean: x(t.mean_excess), ciX: x(t.ci_low), ciW: x(t.ci_high) - x(t.ci_low),
    ticks: Array.from({ length: 7 }, (_, k) => a + k * step).map((v) => ({ x: x(v), label: pct(v, 1, true) })),
  }
}

function yearView(yearly, validateStart) {
  if (!yearly?.length) return null
  const vs = Number(validateStart.slice(0, 4))
  const max = Math.max(...yearly.map((y) => y.mean), 0.002), min = Math.min(...yearly.map((y) => y.mean), -0.002)
  const top = 8, h = 142, w = 360 / yearly.length
  const y = (v) => top + ((max - v) / (max - min)) * h
  const zero = y(0)
  const vIdx = yearly.findIndex((r) => r.year >= vs)
  return {
    zero, w,
    band: vIdx >= 0 ? { x: vIdx * w, w: (yearly.length - vIdx) * w } : null,
    bars: yearly.map((r, i) => ({ x: i * w + w * 0.15, bw: w * 0.7, cx: i * w + w / 2, y: r.mean >= 0 ? y(r.mean) : zero,
      h: Math.max(Math.abs(y(r.mean) - zero), 1), fill: r.mean >= 0 ? 'var(--up)' : 'var(--down)', label: "'" + String(r.year).slice(2),
      title: `${r.year}: ${r.n}건, ${pct(r.mean, 2, true)}` })),
    aria: yearly.map((r) => `${r.year} ${pct(r.mean, 2, true)}`).join(', '),
  }
}

async function copyCmd() {
  try { await navigator.clipboard.writeText('python -m trader test P-003'); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* 복사 불가 환경 */ }
}
</script>

<template>
  <main class="page" v-if="data">
    <div class="head" style="margin: 0; align-items: flex-end">
      <div>
        <h1>원칙·검정</h1>
        <p class="muted" style="margin: 4px 0 0">검정을 통과한 원칙만 GPT가 판단 근거로 쓸 수 있습니다</p>
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center">
        <Chip status="passed" :text="`통과 ${counts.passed}`" />
        <Chip status="rejected" :text="`탈락 ${counts.rejected}`" />
        <Chip status="draft" :text="`검정 전 ${counts.draft}`" />
        <button type="button" class="btn primary" @click="copyCmd">{{ copied ? '복사됨' : '새 원칙 검정 명령 복사' }}</button>
      </div>
    </div>

    <div class="row">
      <div class="grow" style="display: flex; flex-direction: column; gap: 16px; flex-basis: 720px">
        <article v-for="p in data.principles" :key="p.id" class="card" style="padding: 22px 24px; display: flex; flex-direction: column; gap: 16px" :aria-labelledby="p.id">
          <div class="head" style="margin: 0; align-items: center">
            <div style="display: flex; align-items: center; gap: 10px">
              <span class="num muted">{{ p.id }}</span>
              <h2 :id="p.id" style="font-size: 18px; font-weight: 700">{{ p.name }}</h2>
            </div>
            <div style="display: flex; align-items: center; gap: 10px">
              <span v-if="p.latest" class="num muted" style="font-size: 12px">{{ p.trials }}번째 검정 · test #{{ p.latest.test_id }} · {{ p.latest.created_at.slice(5, 10) }}</span>
              <Chip :status="p.status" />
            </div>
          </div>
          <p style="margin: 0; color: var(--text-2)">{{ p.hypothesis }}</p>
          <code class="num code">{{ p.entry }} · 보유 {{ p.horizon_days }}일 · 1회 {{ pct(p.position_size, 0) }}</code>

          <div v-if="!p.latest" class="panel empty">아직 검정하지 않았습니다. <span class="num">python -m trader test {{ p.id }}</span></div>

          <div v-else-if="p.latest.n_events === 0" class="panel" style="display: flex; flex-wrap: wrap; gap: 16px; align-items: center; border-style: dashed">
            <div class="num" style="font-size: 32px; font-weight: 600; color: var(--text-3)">0</div>
            <div style="flex: 1 1 320px">
              <div style="font-weight: 600">검정 구간 동안 조건이 한 번도 충족되지 않았습니다</div>
              <div class="muted" style="font-size: 13px; margin-top: 2px">검정할 표본이 없어 탈락. 조건이 동시에 성립할 수 있는지 다시 확인하세요.</div>
            </div>
          </div>

          <template v-else>
            <div class="stats">
              <div class="stat"><div class="lbl">이벤트 (검정 / 검증)</div><div class="num v">{{ p.latest.n_events }} <span class="muted" style="font-size: 13px">/ {{ p.latest.validate_n }}</span></div></div>
              <div class="stat"><div class="lbl">평균 초과수익</div><div class="num v" :class="p.latest.mean_excess > 0 ? 'up' : 'down'">{{ pct(p.latest.mean_excess, 2, true) }}</div></div>
              <div class="stat"><div class="lbl">p값 (단측)</div><div class="num v">{{ p.latest.p_value.toFixed(3) }}</div></div>
              <div class="stat"><div class="lbl">무작위 진입 대비</div><div class="num v">{{ (p.latest.random_percentile * 100).toFixed(1) }}<span class="muted" style="font-size: 13px">분위</span></div></div>
            </div>

            <div v-if="p.latest.ci_low !== null">
              <div class="lbl" style="margin-bottom: 6px">평균 초과수익과 95% 신뢰구간 — 하한이 0보다 커야 통과</div>
              <svg viewBox="0 0 760 64" role="img" :aria-label="`평균 ${pct(p.latest.mean_excess)}, 신뢰구간 ${pct(p.latest.ci_low)} ~ ${pct(p.latest.ci_high)}`" style="width: 100%; height: auto; display: block">
                <line x1="20" x2="740" y1="30" y2="30" stroke="#E3E6EB" stroke-width="2" />
                <g v-for="t in ciView(p.latest).ticks" :key="t.x">
                  <line :x1="t.x" :x2="t.x" y1="24" y2="36" stroke="#CBD1D9" />
                  <text :x="t.x" y="58" class="axis" text-anchor="middle">{{ t.label }}</text>
                </g>
                <line :x1="ciView(p.latest).zero" :x2="ciView(p.latest).zero" y1="6" y2="46" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="3 3" />
                <text :x="ciView(p.latest).zero + 22" y="14" class="axis" text-anchor="middle" style="fill: var(--accent)">0 기준</text>
                <rect :x="ciView(p.latest).ciX" y="24" :width="ciView(p.latest).ciW" height="12" rx="6" :fill="p.latest.ci_low > 0 ? 'var(--up)' : 'var(--down)'" fill-opacity="0.3" />
                <circle :cx="ciView(p.latest).mean" cy="30" r="6" :fill="p.latest.mean_excess > 0 ? 'var(--up)' : 'var(--down)'" />
              </svg>
            </div>

            <div class="row" style="gap: 24px">
              <div style="flex: 1 1 300px; min-width: 0">
                <div class="lbl" style="margin-bottom: 8px">통과 기준</div>
                <ul class="crit">
                  <li v-for="(c, i) in p.latest.reasons" :key="i">
                    <svg v-if="c.ok" width="16" height="16" viewBox="0 0 16 16" aria-label="충족"><circle cx="8" cy="8" r="7" fill="var(--pass-bg)" /><path d="M4.8 8.2 L7 10.3 L11.2 5.9" stroke="var(--pass-fg)" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round" /></svg>
                    <svg v-else width="16" height="16" viewBox="0 0 16 16" aria-label="미충족"><circle cx="8" cy="8" r="7" fill="var(--reject-bg)" /><path d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5" stroke="var(--reject-fg)" stroke-width="1.8" stroke-linecap="round" /></svg>
                    <span>{{ c.text }}</span>
                  </li>
                </ul>
              </div>
              <div v-if="yearView(p.latest.yearly, data.criteria.validate_start)" style="flex: 1 1 320px; min-width: 0">
                <div class="lbl" style="margin-bottom: 8px">연도별 평균 초과수익 <span style="color: var(--faint)">(밝은 띠 = 검증 구간 {{ data.criteria.validate_start.slice(0, 4) }}~)</span></div>
                <svg viewBox="0 0 360 170" role="img" :aria-label="'연도별 평균 초과수익: ' + yearView(p.latest.yearly, data.criteria.validate_start).aria" style="width: 100%; height: auto; display: block">
                  <rect v-if="yearView(p.latest.yearly, data.criteria.validate_start).band" :x="yearView(p.latest.yearly, data.criteria.validate_start).band.x" y="0" :width="yearView(p.latest.yearly, data.criteria.validate_start).band.w" height="150" fill="var(--accent)" fill-opacity="0.06" />
                  <line x1="0" x2="360" :y1="yearView(p.latest.yearly, data.criteria.validate_start).zero" :y2="yearView(p.latest.yearly, data.criteria.validate_start).zero" stroke="#CBD1D9" />
                  <g v-for="b in yearView(p.latest.yearly, data.criteria.validate_start).bars" :key="b.label">
                    <rect :x="b.x" :y="b.y" :width="b.bw" :height="b.h" rx="3" :fill="b.fill"><title>{{ b.title }}</title></rect>
                    <text :x="b.cx" y="166" class="axis" text-anchor="middle" style="font-size: 10px">{{ b.label }}</text>
                  </g>
                </svg>
              </div>
            </div>
            <div class="foot">
              <span>보고서: <span class="num">{{ p.latest.report_path }}</span></span>
              <span>현재 대형주 유니버스라 생존편향 있음</span>
            </div>
          </template>
        </article>
      </div>

      <aside class="side" style="display: flex; flex-direction: column; gap: 16px; flex-basis: 340px">
        <section class="card pad" aria-labelledby="how">
          <h2 id="how" style="margin-bottom: 14px">검정 방법</h2>
          <ol class="how">
            <li><span class="num">1</span><span>신호일 <b>종가</b>로 조건 판정 → 다음 날 <b>시가</b> 매수 → 보유일 뒤 종가 매도</span></li>
            <li><span class="num">2</span><span>초과수익 = 종목 − 코스피 − 왕복 비용 <span class="num">{{ pct(cost) }}</span></span></li>
            <li><span class="num">3</span><span>날짜 단위 블록 부트스트랩 <span class="num">{{ data.criteria.bootstrap_trials.toLocaleString() }}</span>회 → p값·신뢰구간</span></li>
            <li><span class="num">4</span><span>같은 종목·같은 기간 무작위 진입 <span class="num">{{ data.criteria.random_trials.toLocaleString() }}</span>회와 비교</span></li>
            <li><span class="num">5</span><span>검정 구간(~{{ +data.criteria.validate_start.slice(0, 4) - 1 }})에서 판정, 검증 구간({{ data.criteria.validate_start.slice(0, 4) }}~)에서 같은 방향인지 확인</span></li>
          </ol>
        </section>
        <section class="card pad" aria-labelledby="new">
          <h2 id="new" style="margin-bottom: 6px">새 가설 시험</h2>
          <p class="muted" style="margin: 0 0 12px; font-size: 13px">원칙을 YAML로 쓰고 한 줄로 검정합니다. 같은 원칙을 고쳐 다시 시험할수록 우연히 통과할 확률이 커지므로 검정 횟수가 함께 기록됩니다.</p>
          <pre class="num code" style="white-space: pre">id: P-003
name: [원칙 이름]
entry: "[조건식]"
horizon_days: [보유일]
position_size: 0.05</pre>
          <div class="num cmd">$ python -m trader test P-003</div>
        </section>
      </aside>
    </div>
  </main>
  <div v-else class="page"><div class="card empty">{{ error ? '불러오지 못했습니다: ' + error : '불러오는 중…' }}</div></div>
</template>

<style scoped>
.code { display: block; margin: 0; padding: 10px 12px; border-radius: 8px; background: var(--panel); border: 1px solid var(--line-2); font-size: 12px; color: var(--text-2); overflow-x: auto; white-space: nowrap; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.stat { padding: 12px 14px; border-radius: 10px; background: var(--panel); }
.stat .v { font-size: 20px; font-weight: 600; margin-top: 4px; }
.axis { fill: #6B7584; font-size: 11px; font-family: var(--mono); }
.crit { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.crit li { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; border-top: 1px solid var(--line); padding-top: 14px; font-size: 12px; color: var(--muted); }
.how { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 12px; font-size: 13px; }
.how li { display: flex; gap: 10px; }
.how li > .num:first-child { color: var(--accent); width: 16px; flex: none; }
.cmd { margin-top: 10px; padding: 10px 14px; border-radius: 8px; background: var(--chip); font-size: 12px; color: var(--accent); }
</style>
