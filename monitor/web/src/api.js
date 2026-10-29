// 모니터링 API 호출. 화면은 읽기만 한다 (쓰기·주문 API 없음).
async function get(path) {
  const res = await fetch(`/api${path}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  runs: () => get('/runs'),
  summary: (id) => get(`/runs/${id}/summary`),
  equity: (id) => get(`/runs/${id}/equity`),
  holdings: (id) => get(`/runs/${id}/holdings`),
  decisions: (id) => get(`/runs/${id}/decisions`),
  rules: (id) => get(`/runs/${id}/rules`),
  decision: (id) => get(`/decisions/${id}`),
  principles: () => get('/principles'),
  experiments: () => get('/experiments'),
}
