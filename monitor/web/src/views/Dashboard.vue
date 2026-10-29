<script setup>
// ① 대시보드 — "지금 무슨 일이 일어나고 있나"
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'
import { store } from '../store.js'
import { MODE, pct, pp, shortDate, tone, won, VERDICT } from '../format.js'
import Chip from '../components/Chip.vue'
import EquityChart from '../components/EquityChart.vue'

const s = ref(null), series = ref([]), hold = ref(null), feed = ref([]), rules = ref([]), error = ref(null)

async function load() {
  const id = store.runId
  try {
    const [a, b, c, d, e] = await Promise.all([api.summary(id), api.equity(id), api.holdings(id), api.decisions(id), api.rules(id)])
    s.value = a; series.value = b; hold.value = c; rules.value = e
    feed.value = d.slice(0, 8).flatMap((x) => x.items.map((it) => ({ ...it, date: x.date, id: x.decision_id }))).slice(0, 7)
    error.value = null
  } catch (err) {
    error.value = err.message
  }
}

let timer
onMounted(() => { load(); timer = setInterval(load, 30000) })  // 모의투자 중이면 30초마다 갱신
onUnmounted(() => clearInterval(timer))

const excess = computed(() => (s.value && s.value.bench_return !== null ? s.value.return - s.value.bench_return : null))
const ruleRows = computed(() => rules.value.map((r) => {
  const t = r.PASS + r.CLIP + r.REJECT
  const w = (n) => (t ? (n / t) * 100 : 0) + '%'
  return { ...r, total: t, pw: w(r.PASS), cw: w(r.CLIP), rw: w(r.REJECT) }
}))
const scale = computed(() => (hold.value ? hold.value.max_position_weight * 1.2 : 0.12))  // 비중 막대: 상한의 1.2배까지
const at = (w) => (w / scale.value) * 100 + '%'
</script>

<template>
  <main class="page" v-if="s">
    <div class="head" style="margin: 0; align-items: flex-end">
      <div>
        <h1>오늘의 운용 현황</h1>
        <p class="muted" style="margin: 4px 0 0">{{ s.as_of }} 장 마감 기준 · 마지막 판단 {{ s.last_decision || '없음' }} · 주문은 다음 날 시가 체결</p>
      </div>
      <p class="num muted" style="margin: 0; font-size: 12px">{{ s.run.agent }}</p>
    </div>

    <section aria-label="핵심 지표" class="kpis">
      <div class="card kpi">
        <div class="lbl">총자산</div>
        <div class="num big">{{ won(s.equity) }}<small>원</small></div>
        <div class="sub">시작 {{ won(s.start_equity) }}원</div>
      </div>
      <div class="card kpi">
        <div class="lbl">누적 수익률</div>
        <div class="num big" :class="tone(s.return)">{{ pct(s.return, 2, true) }}</div>
        <div class="sub">코스피 <span class="num" :class="tone(s.bench_return)">{{ pct(s.bench_return, 2, true) }}</span>
          · 초과 <span class="num" :class="tone(excess)">{{ pp(excess) }}</span></div>
      </div>
      <div class="card kpi">
        <div class="lbl">최대낙폭</div>
        <div class="num big">{{ pct(s.mdd) }}</div>
        <div class="sub">고점 대비</div>
      </div>
      <div class="card kpi">
        <div class="lbl">현금 비중</div>
        <div class="num big">{{ pct(s.cash_weight, 1) }}</div>
        <div class="track" style="height: 6px; margin-top: 10px">
          <div class="fill" :style="{ width: s.cash_weight * 100 + '%', background: 'var(--text-3)' }" />
          <div class="tick" :style="{ left: s.min_cash_weight * 100 + '%', background: 'var(--clip)', height: '12px' }" />
        </div>
        <div class="sub" style="margin-top: 6px">최소 {{ pct(s.min_cash_weight, 0) }} 유지 (G08)</div>
      </div>
      <div class="card kpi">
        <div class="lbl">극단적 주문</div>
        <div class="num big" :style="{ color: s.extreme ? 'var(--clip)' : 'var(--pass)' }">{{ s.extreme }}<small>건</small></div>
        <div class="sub">목표 0건 · 비중 10% 초과 또는 조건 불일치</div>
      </div>
      <div class="card kpi">
        <div class="lbl">가드레일 판정 (판단 항목 {{ s.items }}건)</div>
        <div style="display: flex; gap: 14px; margin-top: 8px; align-items: baseline">
          <div v-for="k in ['PASS', 'CLIP', 'REJECT']" :key="k">
            <span class="num" style="font-size: 22px; font-weight: 600" :style="{ color: VERDICT[k].bar }">{{ s.verdicts[k] }}</span>
            <span class="muted" style="font-size: 12px; margin-left: 4px">{{ VERDICT[k].label }}</span>
          </div>
        </div>
        <div class="sub">{{ s.run.guardrails === 'off' ? '가드레일 OFF: 판정만 기록, 실행은 GPT 원안' : '가드레일 ON: 판정대로 실행' }}</div>
      </div>
    </section>

    <div class="row stretch">
      <section class="card pad grow" aria-label="자산 추이">
        <div class="head">
          <h2>자산 추이 <span class="muted" style="font-weight: 400; font-size: 13px">누적 수익률, %</span></h2>
          <div class="legend">
            <span><i style="background: var(--accent); height: 3px" />Agent</span>
            <span><i style="border-top: 2px dashed #6B7584; height: 0" />코스피</span>
          </div>
        </div>
        <EquityChart :series="series" />
      </section>

      <aside class="card pad side" aria-label="실행 상태" style="display: flex; flex-direction: column; gap: 14px">
        <h2>실행 상태</h2>
        <dl class="dl">
          <dt>모드</dt><dd>{{ MODE[s.run.mode] || s.run.mode }} · {{ s.run.start }} → {{ s.run.end }}</dd>
          <dt>에이전트</dt><dd>{{ s.run.agent?.startsWith('graph') ? 'LangGraph' : '직접 구현 루프' }} <span class="num muted">{{ s.run.agent }}</span></dd>
          <dt>가드레일</dt><dd :style="{ color: s.run.guardrails === 'off' ? 'var(--clip)' : 'var(--pass-fg)' }">{{ s.run.guardrails === 'off' ? '판정은 기록, 실행은 GPT 원안' : '주문 직전 적용' }}</dd>
          <dt>손절 F01</dt><dd :style="{ color: s.run.guardrails === 'off' ? 'var(--clip)' : '' }">{{ s.run.guardrails === 'off' ? '꺼짐 (가드레일 OFF)' : `켜짐 · ${s.forced}회 실행` }}</dd>
          <dt>GPT 사용</dt><dd><template v-if="s.usage"><span class="num">{{ s.usage.calls }}</span>회 · <span class="num">${{ s.usage.cost_usd.toFixed(4) }}</span></template><span v-else class="muted">기록 없음</span></dd>
        </dl>
        <div style="border-top: 1px solid var(--line); padding-top: 14px">
          <div class="lbl" style="margin-bottom: 8px">사용 중인 원칙</div>
          <RouterLink v-for="p in s.principles" :key="p.id" to="/principles" class="principle">
            <span><span class="num muted" style="margin-right: 8px">{{ p.id }}</span>{{ p.name }}</span>
            <Chip :status="p.status" :text="p.status === 'passed' ? '검정 통과' : s.run.untested ? '검정 탈락 · 실험' : undefined" />
          </RouterLink>
          <p v-if="s.run.untested" class="muted" style="margin: 8px 0 0; font-size: 12px">검정을 통과하지 않은 원칙을 <span class="num">--untested</span>로 실행했습니다. 운영 모드에서는 쓸 수 없습니다.</p>
        </div>
      </aside>
    </div>

    <div class="row">
      <section class="card pad grow" aria-label="보유 종목">
        <div class="head">
          <h2>보유 종목 <span class="num muted" style="font-weight: 400">{{ hold?.items.length ?? 0 }}</span>
            <span class="muted" style="font-weight: 400; font-size: 12px; margin-left: 6px">{{ hold?.as_of }} 기준</span></h2>
          <div class="legend">
            <span><i style="width: 2px; height: 12px; background: var(--text-3)" />1회 주문 {{ pct(hold?.max_order_weight, 0) }}</span>
            <span><i style="width: 2px; height: 12px; background: var(--clip)" />종목 상한 {{ pct(hold?.max_position_weight, 0) }}</span>
          </div>
        </div>
        <div v-if="!hold?.items.length" class="empty">보유 종목이 없습니다</div>
        <div v-else class="scroll-x">
          <table style="min-width: 760px">
            <thead><tr>
              <th scope="col" style="padding: 8px 10px 10px 0">종목</th>
              <th scope="col" style="padding: 8px 10px 10px">원칙</th>
              <th scope="col" style="padding: 8px 10px 10px; width: 190px">비중</th>
              <th scope="col" style="padding: 8px 10px 10px; text-align: right">평가손익</th>
              <th scope="col" style="padding: 8px 10px 10px; width: 150px">보유 기간</th>
              <th scope="col" style="padding: 8px 0 10px 10px">상태</th>
            </tr></thead>
            <tbody>
              <tr v-for="h in hold.items" :key="h.ticker" style="border-top: 1px solid var(--line-2)">
                <td style="padding: 14px 10px 14px 0">
                  <div style="font-weight: 600">{{ h.name }}</div>
                  <div class="num muted" style="font-size: 11px">{{ h.code }}<template v-if="h.alias"> · GPT에는 {{ h.alias }}</template></div>
                </td>
                <td class="num" style="padding: 14px 10px; color: var(--text-3)">{{ h.principle_id || '—' }}</td>
                <td style="padding: 14px 10px">
                  <div style="display: flex; align-items: center; gap: 10px">
                    <div class="track" style="flex: 1">
                      <div class="fill" :style="{ width: at(Math.min(h.weight, scale)) }" />
                      <div class="tick" :style="{ left: at(hold.max_order_weight), background: 'var(--text-3)' }" />
                      <div class="tick" :style="{ left: at(hold.max_position_weight), background: 'var(--clip)' }" />
                    </div>
                    <span class="num" style="width: 48px; text-align: right">{{ pct(h.weight) }}</span>
                  </div>
                </td>
                <td class="num" style="padding: 14px 10px; text-align: right; font-weight: 600" :class="tone(h.pnl)">{{ pct(h.pnl, 2, true) }}</td>
                <td style="padding: 14px 10px">
                  <div style="display: flex; align-items: center; gap: 8px">
                    <div class="track" style="flex: 1; height: 6px"><div class="fill" :style="{ width: h.horizon_days ? Math.min(h.held_days / h.horizon_days, 1) * 100 + '%' : '0', background: 'var(--faint)' }" /></div>
                    <span class="num" style="font-size: 12px; color: var(--text-3)">{{ h.held_days }}/{{ h.horizon_days ?? '—' }}일</span>
                  </div>
                </td>
                <td style="padding: 14px 0 14px 10px">
                  <div style="display: flex; flex-wrap: wrap; gap: 6px">
                    <span v-if="h.exit_due" class="pill" style="background: var(--sell-bg); color: var(--sell-fg); font-size: 11px">매도 후보</span>
                    <span v-if="h.below_stop" class="pill" style="background: var(--clip-bg); color: var(--clip); font-size: 11px">손절선 {{ pct(hold.stop_loss, 0) }} 초과{{ s.run.guardrails === 'off' ? ' · F01 꺼짐' : '' }}</span>
                    <span v-if="!h.exit_due && !h.below_stop" class="muted" style="font-size: 12px">정상</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card pad side" aria-label="최근 판단" style="flex-basis: 340px">
        <div class="head" style="margin-bottom: 8px">
          <h2>최근 판단</h2>
          <RouterLink to="/decisions" style="font-size: 12px">전체 기록</RouterLink>
        </div>
        <div v-if="!feed.length" class="empty">판단 기록이 없습니다</div>
        <ol class="feed">
          <li v-for="(f, i) in feed" :key="f.id + '-' + i">
            <RouterLink :to="`/decisions/${f.id}`" class="feed-item">
              <span class="num muted" style="font-size: 12px; width: 40px; padding-top: 2px">{{ shortDate(f.date) }}</span>
              <span style="flex: 1; min-width: 0">
                <span style="display: flex; flex-wrap: wrap; align-items: center; gap: 6px">
                  <Chip v-if="f.side" :side="f.side" />
                  <span style="font-weight: 600">{{ f.name }}</span>
                  <span class="num muted" style="font-size: 12px">{{ f.side === 'BUY' && f.weight !== null ? pct(f.weight, 1) : f.side === 'SELL' ? '전량' : '' }}</span>
                </span>
                <span class="note">{{ f.note }}</span>
              </span>
              <Chip :verdict="f.verdict" :text="f.rule ? `${f.rule} 거부` : undefined" />
            </RouterLink>
          </li>
        </ol>
      </section>
    </div>

    <section class="card pad" aria-label="규칙별 판정">
      <div class="head" style="margin-bottom: 14px">
        <h2>규칙별 판정</h2>
        <div class="legend">
          <span v-for="k in ['PASS', 'CLIP', 'REJECT']" :key="k"><i :style="{ width: '10px', height: '10px', borderRadius: '3px', background: VERDICT[k].bar }" />{{ VERDICT[k].label }}</span>
        </div>
      </div>
      <div class="rules">
        <div v-for="r in ruleRows" :key="r.rule" class="panel" style="padding: 12px 14px">
          <div style="display: flex; justify-content: space-between; align-items: baseline; gap: 8px">
            <span><span class="num" style="font-weight: 600; margin-right: 6px">{{ r.rule }}</span><span style="font-size: 12px; color: var(--text-3)">{{ r.name }}</span></span>
            <span class="num muted" style="font-size: 12px">{{ r.total ? r.total + '건' : '발동 없음' }}</span>
          </div>
          <div class="stack">
            <div :style="{ width: r.pw, background: 'var(--pass)' }" />
            <div :style="{ width: r.cw, background: 'var(--clip)' }" />
            <div :style="{ width: r.rw, background: 'var(--reject)' }" />
          </div>
        </div>
      </div>
    </section>
  </main>
  <div v-else class="page"><div class="card empty">{{ error ? '불러오지 못했습니다: ' + error : '불러오는 중…' }}</div></div>
</template>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.kpi { padding: 18px 18px 16px; }
.big { font-size: 24px; font-weight: 600; margin-top: 6px; }
.big small { font-size: 14px; color: var(--muted); margin-left: 4px; font-weight: 400; }
.sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--text-3); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { display: inline-block; width: 16px; border-radius: 2px; }
.dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 12px 16px; font-size: 13px; }
.dl dt { color: var(--muted); }
.dl dd { margin: 0; }
.principle { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px; border-radius: 10px; background: var(--chip); border: 1px solid var(--line-3); color: var(--text); margin-bottom: 6px; }
.feed { list-style: none; margin: 0; padding: 0; }
.feed li { border-top: 1px solid var(--line-2); }
.feed-item { display: flex; gap: 12px; padding: 12px 0; color: var(--text); align-items: flex-start; }
.feed-item:hover { background: var(--panel); }
.note { display: block; font-size: 12px; color: var(--muted); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.rules { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.stack { display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: var(--line-2); margin-top: 10px; }
</style>
