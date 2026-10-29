// 화면 전체가 함께 쓰는 상태: 실행 목록과 지금 보고 있는 실행
import { reactive } from 'vue'
import { api } from './api.js'

export const store = reactive({
  runs: [],
  runId: null,
  error: null,
  async loadRuns() {
    try {
      this.runs = await api.runs()
      this.error = null
      const saved = Number(localStorageGet('runId'))
      if (!this.runs.some((r) => r.run_id === this.runId)) {
        // 기본값: 기록된 날이 있는 가장 최근 실행 (1회 테스트 주문처럼 일별 기록이 없는 실행은 건너뜀)
        const withDays = this.runs.find((r) => r.days > 0)
        this.runId = this.runs.some((r) => r.run_id === saved) ? saved : (withDays ?? this.runs[0])?.run_id ?? null
      }
    } catch (e) {
      this.error = e.message
    }
  },
  select(id) {
    this.runId = id
    localStorageSet('runId', id)
  },
  get run() {
    return this.runs.find((r) => r.run_id === this.runId) || null
  },
})

function localStorageGet(k) {
  try { return localStorage.getItem(k) } catch { return null }
}
function localStorageSet(k, v) {
  try { localStorage.setItem(k, v) } catch { /* 저장 못 해도 동작에는 지장 없음 */ }
}
