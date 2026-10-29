<script setup>
// ④ 가드레일 실험 — "가드레일이 정말 막는가": 같은 조건에서 가드레일만 끄고 켠 실행을 나란히
import { ref } from 'vue'
import { api } from '../api.js'
import { pct, tone } from '../format.js'

const data = ref(null), error = ref(null)
api.experiments().then((d) => (data.value = d)).catch((e) => (error.value = e.message))

const isMock = (e) => (e.agent || '').includes('mock')
const color = (v) => (tone(v) ? `var(--${tone(v)})` : '')

function finding(e) {
  const b = e.buy_requests
  if (e.off.extreme === 0 && e.offline_filter === 0) {
    return `GPT의 매수 제안 ${b.n}건이 모두 1회 한도 이내(최대 ${pct(b.max, 1)})였습니다. 가드레일이 조정할 일이 없었고, 손절(F01)만 ${e.on.forced}회 작동했습니다.`
  }
  return `가드레일을 끈 실행의 극단적 주문 ${e.off.extreme}건이 켠 실행에서는 ${e.on.extreme}건이 됐습니다. 한 종목 최대 비중은 ${pct(e.off.max_weight, 1)}에서 ${pct(e.on.max_weight, 1)}로, 최대낙폭은 ${pct(e.off.mdd)}에서 ${pct(e.on.mdd)}로 바뀌었습니다.`
}

function rows(e) {
  const cost = (u) => (u ? '$' + u.cost_usd.toFixed(3) : isMock(e) ? '— (mock)' : '기록 없음')
  return [
    { k: '극단적 주문', off: `${e.off.extreme}건`, on: `${e.on.extreme}건`, offC: e.off.extreme ? 'var(--clip)' : '', onC: e.on.extreme ? 'var(--clip)' : 'var(--pass)' },
    { k: '최대 종목 비중', off: pct(e.off.max_weight, 1), on: pct(e.on.max_weight, 1), offC: e.off.max_weight > data.value.max_position_weight ? 'var(--clip)' : '' },
    { k: '최대낙폭', off: pct(e.off.mdd), on: pct(e.on.mdd) },
    { k: `수익률 (코스피 ${pct(e.on.bench, 2, true)})`, off: pct(e.off.return, 2, true), on: pct(e.on.return, 2, true), offC: color(e.off.return), onC: color(e.on.return) },
    { k: '판단 / 체결', off: `${e.off.decisions} / ${e.off.orders}`, on: `${e.on.decisions} / ${e.on.orders}` },
    { k: '강제 손절 F01', off: '꺼짐', on: `${e.on.forced}건`, offC: 'var(--muted)' },
    { k: 'GPT 비용', off: cost(e.off.usage), on: cost(e.on.usage) },
  ]
}

function bars(e) {
  const list = e.on.rule_bars
  const max = Math.max(...list.map((r) => r.n), 1)
  return list.map((r) => ({ label: `${r.rule} ${r.verdict === 'CLIP' ? '조정' : '거부'}`, n: r.n, w: (r.n / max) * 100 + '%',
    c: r.verdict === 'CLIP' ? 'var(--clip)' : 'var(--reject)' }))
}
</script>

<template>
  <main class="page" v-if="data">
    <div>
      <h1>가드레일 실험</h1>
      <p class="muted" style="margin: 4px 0 0">같은 기간을 가드레일을 끄고·켜고 돌려 비교합니다. 극단적 주문 = 목표 비중 {{ pct(data.max_position_weight, 0) }} 초과, 또는 인용한 원칙 조건이 실제로는 미충족인 매수.</p>
    </div>

    <div v-if="!data.experiments.length" class="card empty">
      짝이 되는 실행이 없습니다. 같은 조건으로 <span class="num">--guardrails off</span>와 <span class="num">--guardrails on</span>을 각각 실행하세요.
    </div>

    <div class="row stretch">
      <section v-for="(e, i) in data.experiments" :key="e.on.run_id" class="card exp" :aria-label="isMock(e) ? '스트레스 테스트' : '실제 GPT'">
        <div>
          <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px">
            <span class="num tag" :style="isMock(e) ? 'background: var(--clip-bg); color: var(--clip)' : 'background: #ECF7D4; color: var(--accent)'">실험 {{ String.fromCharCode(65 + i) }}</span>
            <h2 style="font-size: 18px; font-weight: 700">{{ isMock(e) ? '스트레스 테스트 (mock 모델)' : '실제 GPT' }}</h2>
          </div>
          <p class="num muted" style="margin: 6px 0 0; font-size: 12px">{{ e.agent }} · {{ e.on.start }} → {{ e.on.end }} · {{ e.principles.join(', ') }}{{ e.untested ? ' (실험)' : '' }} · run {{ e.off.run_id }} vs {{ e.on.run_id }}</p>
        </div>
        <div class="panel" style="font-size: 14px">{{ finding(e) }}</div>
        <div class="scroll-x">
          <table style="min-width: 420px">
            <thead><tr style="text-align: right">
              <th scope="col" style="padding: 6px 0 8px">지표</th>
              <th scope="col" style="padding: 6px 10px 8px; text-align: right">가드레일 끔</th>
              <th scope="col" style="padding: 6px 0 8px 10px; text-align: right">가드레일 켬</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in rows(e)" :key="r.k" style="border-top: 1px solid var(--line-2)">
                <th scope="row" style="padding: 10px 0; font-weight: 400; color: var(--text-2); font-size: 13px">{{ r.k }}</th>
                <td class="num" style="padding: 10px; text-align: right" :style="{ color: r.offC || 'var(--text-2)' }">{{ r.off }}</td>
                <td class="num" style="padding: 10px 0 10px 10px; text-align: right; font-weight: 600" :style="{ color: r.onC || 'var(--text-2)' }">{{ r.on }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div>
          <div class="lbl" style="margin-bottom: 8px">가드레일 켬 — 규칙별 조정·거부</div>
          <div v-if="bars(e).length" style="display: flex; flex-direction: column; gap: 8px">
            <div v-for="b in bars(e)" :key="b.label" class="bar">
              <span class="num" style="width: 92px; color: var(--text-3)">{{ b.label }}</span>
              <div class="track" style="flex: 1; height: 10px"><div class="fill" :style="{ width: b.w, background: b.c }" /></div>
              <span class="num" style="width: 40px; text-align: right">{{ b.n }}</span>
            </div>
          </div>
          <p v-else class="muted" style="margin: 0; font-size: 13px">조정·거부 0건. 강제 손절(F01)만 {{ e.on.forced }}회 실행.</p>
        </div>
      </section>
    </div>

    <section v-if="data.experiments.length" class="card pad" aria-labelledby="ex">
      <h2 id="ex" style="margin-bottom: 14px">두 가지로 확인합니다</h2>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px">
        <div class="panel" style="padding: 16px">
          <div style="font-weight: 600">오프라인 필터</div>
          <p class="muted" style="margin: 6px 0 12px; font-size: 13px">가드레일을 끈 실행의 GPT 판단을 그대로 가드레일에 통과시킵니다. GPT 응답이 같으니 차이는 가드레일뿐입니다.</p>
          <div style="display: flex; flex-wrap: wrap; gap: 24px">
            <div v-for="(e, i) in data.experiments" :key="e.off.run_id">
              <div class="num" style="font-size: 20px; font-weight: 600" :style="{ color: e.offline_filter ? 'var(--clip)' : '' }">{{ e.offline_filter }}</div>
              <div class="muted" style="font-size: 11px">실험 {{ String.fromCharCode(65 + i) }} · 조정·거부</div>
            </div>
          </div>
        </div>
        <div class="panel" style="padding: 16px">
          <div style="font-weight: 600">폐루프 재백테스트</div>
          <p class="muted" style="margin: 6px 0 12px; font-size: 13px">같은 기간을 가드레일을 켜고 다시 돌립니다. 막힌 뒤 포트폴리오가 달라져 이후 판단도 달라집니다.</p>
          <div style="display: flex; flex-wrap: wrap; gap: 24px">
            <div v-for="(e, i) in data.experiments" :key="e.on.run_id">
              <div class="num" style="font-size: 20px; font-weight: 600" :style="{ color: e.on.extreme ? 'var(--clip)' : 'var(--pass)' }">{{ e.on.extreme }}</div>
              <div class="muted" style="font-size: 11px">실험 {{ String.fromCharCode(65 + i) }} · 극단적 주문</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </main>
  <div v-else class="page"><div class="card empty">{{ error ? '불러오지 못했습니다: ' + error : '불러오는 중…' }}</div></div>
</template>

<style scoped>
.exp { flex: 1 1 560px; min-width: 0; padding: 22px 24px; display: flex; flex-direction: column; gap: 16px; }
.tag { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 6px; }
.bar { display: flex; align-items: center; gap: 10px; font-size: 12px; }
</style>
