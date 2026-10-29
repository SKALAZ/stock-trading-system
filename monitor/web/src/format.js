// 숫자 표기: 음수는 진짜 빼기 기호(−), 상승=빨강 / 하락=파랑
const MINUS = '−'

export function pct(v, digits = 2, signed = false) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = Math.abs(v * 100).toFixed(digits) + '%'
  if (v < 0) return MINUS + s
  return (signed && v > 0 ? '+' : '') + s
}

export function pp(v, digits = 2) {
  if (v === null || v === undefined) return '—'
  return (v < 0 ? MINUS : '+') + Math.abs(v * 100).toFixed(digits) + '%p'
}

export function won(v) {
  if (v === null || v === undefined) return '—'
  return Math.round(v).toLocaleString('ko-KR')
}

export function num(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = Math.abs(v).toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return (v < 0 ? MINUS : '') + s
}

export const tone = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '')

export const shortDate = (d) => (d ? d.slice(5).replace('-', '/') : '—')

export const VERDICT = {
  PASS: { label: '통과', bg: 'var(--pass-bg)', fg: 'var(--pass-fg)', bar: 'var(--pass)' },
  CLIP: { label: '조정', bg: 'var(--clip-bg)', fg: 'var(--clip)', bar: 'var(--clip)' },
  REJECT: { label: '거부', bg: 'var(--reject-bg)', fg: 'var(--reject-fg)', bar: 'var(--reject)' },
  HOLD: { label: '보류', bg: 'var(--chip)', fg: 'var(--text-3)', bar: 'var(--line-3)' },
  FORCED: { label: '강제', bg: 'var(--clip-bg)', fg: 'var(--clip)', bar: 'var(--clip)' },
}

export const MODE = { backtest: '백테스트', paper: '모의투자', live: '실거래', 'live-dry': '실거래 미리보기 (주문 안 함)' }

export const STATUS = {
  passed: { label: '통과', bg: 'var(--pass-bg)', fg: 'var(--pass-fg)' },
  rejected: { label: '탈락', bg: 'var(--reject-bg)', fg: 'var(--reject-fg)' },
  draft: { label: '검정 전', bg: 'var(--chip)', fg: 'var(--text-3)' },
}

// GPT 도구 결과를 한 줄로
export function compact(result) {
  if (Array.isArray(result)) {
    return result.map((p) => (p.id ? `${p.id} ${p.name} · entry: ${p.entry} · 보유 ${p.horizon_days}일` : JSON.stringify(p))).join(' / ')
  }
  if (result && typeof result === 'object') {
    if (result.holdings) {
      const h = result.holdings.map((x) => `${x.stock} ${pct(x.weight, 1)}`).join(', ')
      return `현금 ${pct(result.cash_weight, 1)} · 보유 ${result.holdings.length}종목${h ? ' (' + h + ')' : ''}`
    }
    return Object.entries(result).map(([k, v]) => `${k} ${typeof v === 'number' ? v.toFixed(4) : v}`).join(' · ')
  }
  return String(result)
}
