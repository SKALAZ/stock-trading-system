<script setup>
// 가드레일 검사 한 줄: 아이콘 · 규칙 · 사유 · (조정이면 전→후)
import { pct } from '../format.js'

defineProps({ check: { type: Object, required: true } })
</script>

<template>
  <li class="row-check">
    <svg v-if="check.verdict === 'PASS'" width="16" height="16" viewBox="0 0 16 16" aria-label="통과">
      <circle cx="8" cy="8" r="7" fill="var(--pass-bg)" /><path d="M4.8 8.2 L7 10.3 L11.2 5.9" stroke="var(--pass-fg)" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <svg v-else-if="check.verdict === 'CLIP'" width="16" height="16" viewBox="0 0 16 16" aria-label="조정">
      <circle cx="8" cy="8" r="7" fill="var(--clip-bg)" /><path d="M4.5 8 H11.5" stroke="var(--clip)" stroke-width="1.8" stroke-linecap="round" />
    </svg>
    <svg v-else width="16" height="16" viewBox="0 0 16 16" aria-label="거부">
      <circle cx="8" cy="8" r="7" fill="var(--reject-bg)" /><path d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5" stroke="var(--reject-fg)" stroke-width="1.8" stroke-linecap="round" />
    </svg>
    <span class="num rule">{{ check.rule }}</span>
    <span class="reason">{{ check.reason }}</span>
    <span v-if="check.verdict === 'CLIP' && check.before !== null" class="num muted" style="font-size: 12px">{{ pct(check.before, 1) }} → {{ pct(check.after, 1) }}</span>
  </li>
</template>

<style scoped>
.row-check { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.rule { width: 52px; color: var(--text-3); }
.reason { flex: 1; min-width: 0; }
</style>
