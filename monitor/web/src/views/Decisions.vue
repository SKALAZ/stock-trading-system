<script setup>
// ② 판단 추적 — "이 주문은 왜 나갔나": 입력 → GPT 도구 호출 → 제안 → 가드레일 → 주문·체결
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { store } from '../store.js'
import { compact, pct, shortDate, won } from '../format.js'
import Chip from '../components/Chip.vue'
import CheckRow from '../components/CheckRow.vue'

const route = useRoute(), router = useRouter()
const list = ref([]), detail = ref(null), filter = ref('all'), error = ref(null)

const filters = [['all', '전체'], ['BUY', '매수'], ['SELL', '매도'], ['REJECT', '거부 있음']]
const keep = {
  all: () => true,
  BUY: (d) => d.items.some((i) => i.side === 'BUY'),
  SELL: (d) => d.items.some((i) => i.side === 'SELL'),
  REJECT: (d) => d.items.some((i) => i.verdict === 'REJECT'),
}
const shown = computed(() => list.value.filter(keep[filter.value]))
const rowOf = (d) => {
  const sides = [...new Set(d.items.map((i) => i.side).filter(Boolean))]
  const names = [...new Set(d.items.map((i) => i.name))]
  return { side: sides.length === 1 ? sides[0] : sides.length ? 'MIX' : 'HOLD', name: names.join(' · ') || '판단 없음',
           reject: d.items.some((i) => i.verdict === 'REJECT') }
}

async function loadList() {
  try {
    list.value = await api.decisions(store.runId)
    if (!route.params.id && list.value.length) router.replace(`/decisions/${list.value[0].decision_id}`)
  } catch (e) { error.value = e.message }
}
async function loadDetail(id) {
  if (!id) { detail.value = null; return }
  try {
    const d = await api.decision(id)
    if (d.run.run_id !== store.runId) { store.select(d.run.run_id); return }  // 다른 실행의 판단이면 그 실행으로 전환
    detail.value = d
    error.value = null
  } catch (e) { error.value = e.message }
}
loadList()
watch(() => route.params.id, loadDetail, { immediate: true })

// 도구 호출과 최종 답만 시간 순으로 (직접 구현 루프·LangGraph 로그 형식을 같은 모양으로)
const steps = computed(() => (detail.value?.steps || []).flatMap((s) => {
  if (s.tool) return [{ step: s.step, call: s.tool, args: typeof s.args === 'string' ? s.args : JSON.stringify(s.args), result: compact(s.result), final: false }]
  if (s.final !== undefined) return [{ step: s.step, call: '최종 답 (JSON)', args: '도구 호출 없음 → 결론', result: s.final, final: true }]
  return []
}))
const nTools = computed(() => steps.value.filter((s) => !s.final).length)
const nCalls = computed(() => new Set((detail.value?.steps || []).map((s) => s.step)).size)
const title = computed(() => {
  const items = detail.value?.items.filter((i) => !i.invalid && i.action !== 'HOLD') || []
  if (!items.length) return '주문 없음 — 왜 아무것도 하지 않았나'
  const verb = { BUY: '매수', SELL: '매도' }
  return `${[...new Set(items.map((i) => i.name))].join(' · ')} ${[...new Set(items.map((i) => verb[i.action]))].join('·')} — 왜 주문됐나`
})
</script>

<template>
  <main class="page" style="flex-direction: row; flex-wrap: wrap; align-items: flex-start">
    <aside class="card side" aria-label="판단 목록" style="padding: 18px 16px; flex-basis: 300px">
      <h2 style="margin: 0 6px 12px">판단 기록 <span class="num muted" style="font-weight: 400">{{ list.length }}</span></h2>
      <div role="group" aria-label="필터" class="filters">
        <button v-for="[id, label] in filters" :key="id" type="button" :aria-pressed="filter === id" :class="{ on: filter === id }" @click="filter = id">{{ label }}</button>
      </div>
      <ol class="dlist">
        <li v-for="d in shown" :key="d.decision_id">
          <RouterLink :to="`/decisions/${d.decision_id}`" class="ditem" :class="{ cur: String(d.decision_id) === String(route.params.id) }"
                      :aria-current="String(d.decision_id) === String(route.params.id) ? 'page' : undefined">
            <span class="num muted" style="font-size: 12px; width: 40px">{{ shortDate(d.date) }}</span>
            <Chip v-if="rowOf(d).side === 'BUY' || rowOf(d).side === 'SELL'" :side="rowOf(d).side" />
            <span v-else class="pill" style="background: var(--chip); color: var(--text-3); font-size: 11px">{{ rowOf(d).side === 'MIX' ? '혼합' : 'HOLD' }}</span>
            <span class="dname">{{ rowOf(d).name }}</span>
            <span class="ddot" :style="{ background: rowOf(d).reject ? 'var(--reject)' : 'var(--pass)' }" :aria-label="rowOf(d).reject ? '거부 있음' : '모두 통과'" />
          </RouterLink>
        </li>
      </ol>
      <div v-if="!shown.length" class="empty">해당하는 판단이 없습니다</div>
    </aside>

    <div class="grow" style="display: flex; flex-direction: column; gap: 16px; flex-basis: 720px">
      <div v-if="error" class="card empty">{{ error }}</div>
      <template v-if="detail">
        <div class="head" style="margin: 0; align-items: flex-end">
          <div>
            <div class="num lbl">판단 #{{ detail.decision_id }} · {{ detail.date }} 장 마감</div>
            <h1 style="margin-top: 4px">{{ title }}</h1>
          </div>
          <div class="num muted" style="font-size: 12px; text-align: right">{{ detail.agent }} · prompt {{ detail.prompt_version }}<br>GPT 호출 {{ nCalls }}회 · 도구 {{ nTools }}회</div>
        </div>

        <nav aria-label="역추적" class="card trace">
          <span class="lbl" style="margin-right: 4px">역추적</span>
          <span class="num tchip">주문 {{ detail.items.filter((i) => i.order).map((i) => '#' + i.order.order_id).join(' · ') || '없음' }}</span>
          <span aria-hidden="true" class="arrow">→</span>
          <span class="num tchip">판단 #{{ detail.decision_id }}</span>
          <template v-for="t in detail.trace" :key="t.principle_id">
            <span aria-hidden="true" class="arrow">→</span>
            <RouterLink to="/principles" class="num tchip">원칙 {{ t.principle_id }}</RouterLink>
            <span aria-hidden="true" class="arrow">→</span>
            <RouterLink to="/principles" class="num tchip" :style="t.verdict === 'passed' ? 'background: var(--pass-bg); color: var(--pass-fg)' : 'background: var(--reject-bg); color: var(--reject-fg)'">
              {{ t.test_id ? `검정 test #${t.test_id} · ${t.verdict === 'passed' ? '통과' : '탈락'}` : '검정 기록 없음 (--untested 실행)' }}
            </RouterLink>
          </template>
        </nav>

        <section class="card pad" aria-labelledby="s1">
          <div class="stage"><span class="num n">1</span><h2 id="s1">GPT에게 준 입력</h2><span class="muted" style="font-size: 12px">종목명·날짜는 가리고, 가격 대신 정규화 지표만</span></div>
          <div class="grid3">
            <div class="panel">
              <div class="lbl">매수 후보 (코드가 걸러낸 것)</div>
              <div v-if="!detail.input.candidates.length" style="margin-top: 10px; color: var(--text-3)">없음</div>
              <div v-for="c in detail.input.candidates" :key="c.alias" class="pair"><span class="num" style="font-weight: 600">{{ c.alias }}</span><span class="muted" style="font-size: 12px">= {{ c.name }} · {{ c.principles.join(', ') }}</span></div>
              <div style="font-size: 11px; color: var(--faint); margin-top: 10px">실명은 사람에게만 보입니다</div>
            </div>
            <div class="panel">
              <div class="lbl">매도 후보</div>
              <div v-if="!detail.input.exit_due.length" style="margin-top: 10px; color: var(--text-3)">없음</div>
              <div v-for="c in detail.input.exit_due" :key="c.alias" class="pair"><span class="num" style="font-weight: 600">{{ c.alias }}</span><span class="muted" style="font-size: 12px">= {{ c.name }} · 보유 {{ c.held_days }}일</span></div>
              <div style="font-size: 11px; color: var(--faint); margin-top: 10px">보유 기간이 원칙의 보유일에 닿은 종목</div>
            </div>
            <div class="panel">
              <div class="lbl">포트폴리오</div>
              <div style="display: flex; gap: 20px; margin-top: 10px">
                <div><div class="num" style="font-size: 18px; font-weight: 600">{{ pct(detail.input.cash_weight, 1) }}</div><div class="muted" style="font-size: 11px">현금</div></div>
                <div><div class="num" style="font-size: 18px; font-weight: 600">{{ detail.input.n_holdings }}</div><div class="muted" style="font-size: 11px">보유 종목</div></div>
                <div><div class="num" style="font-size: 18px; font-weight: 600">{{ (detail.input.equity / 1e6).toFixed(2) }}M</div><div class="muted" style="font-size: 11px">총자산</div></div>
              </div>
            </div>
          </div>
        </section>

        <section class="card pad" aria-labelledby="s2">
          <div class="stage"><span class="num n">2</span><h2 id="s2">GPT 추론 단계</h2><span class="muted" style="font-size: 12px">읽기 전용 도구만 사용 · 주문 도구 없음</span></div>
          <ol class="steps">
            <li v-for="(s, i) in steps" :key="i">
              <div class="rail"><span class="sdot" :style="{ borderColor: s.final ? 'var(--accent)' : 'var(--faint)' }" /><span class="sline" /></div>
              <div style="flex: 1; min-width: 0; padding-bottom: 14px">
                <div style="display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px">
                  <span class="num muted" style="font-size: 11px">step {{ s.step }}</span>
                  <span class="num" style="font-weight: 600">{{ s.call }}</span>
                  <span class="num" style="font-size: 12px; color: var(--text-3)">{{ s.args === '{}' ? '' : s.args }}</span>
                </div>
                <div class="num result">{{ s.result }}</div>
              </div>
            </li>
          </ol>
        </section>

        <div class="row" style="gap: 16px">
          <section v-for="it in detail.items.filter((x) => !x.invalid)" :key="it.index" class="card pad item" :aria-label="`${it.name} 판단`">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
              <div style="display: flex; align-items: center; gap: 8px">
                <Chip v-if="it.action !== 'HOLD'" :side="it.action" />
                <span v-else class="pill" style="background: var(--chip); color: var(--text-3); font-size: 11px">HOLD</span>
                <span style="font-weight: 700; font-size: 16px">{{ it.name }}</span>
                <span class="num muted" style="font-size: 12px">{{ it.alias }}</span>
              </div>
              <Chip :verdict="it.checks.some((c) => c.verdict === 'REJECT') ? 'REJECT' : it.checks.some((c) => c.verdict === 'CLIP') ? 'CLIP' : 'PASS'" />
            </div>
            <div>
              <div class="lbl" style="margin-bottom: 6px"><span class="num">3</span> · GPT 제안</div>
              <div style="display: flex; gap: 18px; align-items: baseline">
                <div v-if="it.action === 'BUY'"><span class="num" style="font-size: 20px; font-weight: 600">{{ pct(it.target_weight, 1) }}</span><span class="muted" style="font-size: 12px; margin-left: 4px">목표 비중</span></div>
                <div v-else-if="it.action === 'SELL'"><span class="num" style="font-size: 20px; font-weight: 600">전량</span><span class="muted" style="font-size: 12px; margin-left: 4px">매도</span></div>
                <div class="num" style="color: var(--text-3)">{{ it.principle_id }}</div>
              </div>
              <p style="margin: 8px 0 0; font-size: 13px; color: var(--text-2)">“{{ it.reason }}”</p>
              <div v-if="it.conditions_claimed?.length" class="claims">
                <span v-for="c in it.conditions_claimed" :key="c.name" class="num">{{ c.name }} {{ typeof c.value === 'number' ? +c.value.toFixed(4) : c.value }}</span>
              </div>
            </div>
            <div>
              <div class="lbl" style="margin-bottom: 8px"><span class="num">4</span> · 가드레일{{ detail.run.guardrails === 'off' ? ' (기록만 — 이 실행은 가드레일 OFF)' : '' }}</div>
              <ul style="list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px">
                <CheckRow v-for="c in it.checks" :key="c.id" :check="c" />
              </ul>
            </div>
            <div style="border-top: 1px solid var(--line); padding-top: 12px">
              <div class="lbl" style="margin-bottom: 8px"><span class="num">5</span> · 주문 → 체결</div>
              <div v-if="!it.order" class="muted" style="font-size: 13px">주문 없음</div>
              <template v-else>
                <div class="grid-order">
                  <div><div class="num" style="font-weight: 600">{{ it.order.fill_qty ?? it.order.qty }}주</div><div class="muted" style="font-size: 11px">{{ it.order.status === 'FILLED' ? '체결 수량' : '주문 수량' }}</div></div>
                  <div><div class="num" style="font-weight: 600">{{ it.order.fill_price ? won(it.order.fill_price) + '원' : it.order.status }}</div><div class="muted" style="font-size: 11px">{{ it.order.fill_date ? it.order.fill_date.slice(5) + ' 시가 체결가' : '대기' }}</div></div>
                  <div v-if="it.action === 'BUY'"><div class="num" style="font-weight: 600">{{ it.order.weight_after !== null ? pct(it.order.weight_after) : '—' }}</div><div class="muted" style="font-size: 11px">체결 후 비중</div></div>
                </div>
                <div class="num" style="font-size: 11px; color: var(--faint); margin-top: 10px">client_order_id {{ it.order.client_order_id }}</div>
              </template>
            </div>
          </section>

          <section v-for="it in detail.items.filter((x) => x.invalid)" :key="'bad' + it.index" class="card pad item" aria-label="형식 오류 판단">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
              <span style="font-weight: 700; font-size: 16px">형식이 틀린 제안</span>
              <Chip verdict="REJECT" text="G01 거부" />
            </div>
            <p style="margin: 0; font-size: 13px">{{ it.error }}</p>
            <pre class="num result" style="white-space: pre-wrap">{{ JSON.stringify(it.raw, null, 1) }}</pre>
          </section>
        </div>

        <section v-if="detail.forced.length" class="card pad">
          <h2 style="margin-bottom: 8px">강제 손절 (F01) — GPT와 무관하게 실행</h2>
          <div v-for="o in detail.forced" :key="o.order_id" class="num" style="font-size: 13px">{{ o.ticker }} · {{ o.qty }}주 · {{ o.status }}</div>
        </section>
      </template>
      <div v-else-if="!error" class="card empty">{{ list.length ? '판단을 고르세요' : '이 실행에는 판단 기록이 없습니다' }}</div>
    </div>
  </main>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 6px 12px; }
.filters button { min-height: 32px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--line-3); background: var(--surface); color: var(--text-3); font-size: 12px; cursor: pointer; }
.filters button.on { background: var(--text); color: #fff; border-color: var(--text); }
.dlist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; max-height: 70vh; overflow-y: auto; }
.ditem { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 10px; color: var(--text); min-height: 44px; }
.ditem:hover { background: var(--panel); }
.ditem.cur { background: var(--active); }
.dname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ddot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.trace { padding: 12px 16px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 13px; }
.tchip { padding: 4px 10px; border-radius: 8px; background: var(--chip); color: var(--text); }
.arrow { color: #A0A8B4; }
.stage { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px; }
.stage .n { width: 26px; height: 26px; border-radius: 8px; background: var(--active); display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }
.grid3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.pair { display: flex; justify-content: space-between; gap: 8px; margin-top: 8px; }
.steps { list-style: none; margin: 0; padding: 0; }
.steps li { display: flex; gap: 14px; }
.rail { display: flex; flex-direction: column; align-items: center; width: 14px; }
.sdot { width: 10px; height: 10px; border-radius: 50%; margin-top: 6px; border: 2px solid; }
.sline { flex: 1; width: 2px; background: var(--line); }
.result { margin-top: 6px; padding: 10px 12px; border-radius: 8px; background: var(--panel); border: 1px solid var(--line-2); font-size: 12px; color: var(--text-2); overflow-x: auto; white-space: nowrap; }
.item { flex: 1 1 380px; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.claims { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.claims span { font-size: 11px; padding: 2px 8px; border-radius: 6px; background: var(--chip); color: var(--text-3); }
.grid-order { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; }
</style>
