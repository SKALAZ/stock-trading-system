<script setup>
// 판정(PASS/CLIP/REJECT), 매수·매도, 원칙 상태를 같은 모양의 작은 꼬리표로
import { computed } from 'vue'
import { STATUS, VERDICT } from '../format.js'

const props = defineProps({
  verdict: String,
  side: String,
  status: String,
  text: String,
})

const style = computed(() => {
  if (props.side) {
    const buy = props.side === 'BUY'
    return { background: buy ? 'var(--buy-bg)' : 'var(--sell-bg)', color: buy ? 'var(--buy-fg)' : 'var(--sell-fg)', borderRadius: '6px', fontFamily: 'var(--mono)', padding: '2px 7px', fontSize: '11px' }
  }
  const v = props.verdict ? VERDICT[props.verdict] : STATUS[props.status] || STATUS.draft
  return { background: v.bg, color: v.fg }
})
const label = computed(() => props.text ?? (props.side || (props.verdict ? VERDICT[props.verdict]?.label : STATUS[props.status]?.label)))
</script>

<template>
  <span class="pill" :style="style">{{ label }}</span>
</template>
