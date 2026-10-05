<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessages } from '../api'
const data = ref<any>(null)
const candidates = ref<any[]>([])
const violKeys = ref<Set<string>>(new Set())
const errors = ref<string[]>([])
async function loadLatest() {
  try {
    errors.value = []
    data.value = await api('/seating/latest?hall_id=1')
  } catch (e) { errors.value = errorMessages(e) }
}
async function refreshViolations() {
  try {
    const v = await api('/seating/violations?hall_id=1')
    const keys = new Set<string>()
    for (const x of v.violations || []) {
      if (x.a_id != null) keys.add(String(x.a_id))
      if (x.b_id != null) keys.add(String(x.b_id))
    }
    violKeys.value = keys
  } catch { violKeys.value = new Set() }
}
async function run() {
  try {
    errors.value = []
    data.value = await api('/seating/run?hall_id=1', { method: 'POST' })
    await refreshViolations()
  } catch (e) {
    // 整场失败：不增方案，保留当前最新方案，仅逐条展示失败消息
    errors.value = errorMessages(e)
  }
}
onMounted(async () => {
  candidates.value = await api('/candidates')
  await loadLatest()
  await refreshViolations()
})
const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      out.push(map.get(r + ',' + c) || { empty: true, row: r, col: c })
    }
  }
  return out
})
// 左账人数、右账人数与排座图同一套：都取自最新方案里的两本账
const leftCount = computed(() => (data.value?.ledgers?.left || []).length)
const rightCount = computed(() => (data.value?.ledgers?.right || []).length)
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
function sideLabel(s: string | null) {
  return s === 'L' ? '左' : s === 'R' ? '右' : '未标记'
}
function sideTagClass(s: string | null) {
  return s === 'L' ? 'l' : s === 'R' ? 'r' : 'u'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左右两本账分界列切开 · 违规课桌高亮</p>
  <button class="btn" @click="run">重新排座</button>
  <div v-if="errors.length" class="hs-errors">
    <div v-for="(m, i) in errors" :key="i">{{ m }}</div>
  </div>
  <div class="hs-ledger-bar" v-if="data">
    <span class="hs-ledger-chip l">左账 {{ leftCount }} 人</span>
    <span class="hs-ledger-chip r">右账 {{ rightCount }} 人</span>
    <span class="muted">分界列 {{ data.boundary_col }} · 已座 {{ data.stats?.seated }} / {{ data.stats?.capacity }}</span>
  </div>
  <div class="hs-classroom" style="margin-top:0.85rem">
    <aside class="hs-clipboard">
      <h2>考生名册</h2>
      <div v-for="c in candidates" :key="c.id" class="hs-roster-row">
        <div>
          <div>{{ c.name }}</div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }} <span class="hs-side-tag" :class="sideTagClass(c.side)">{{ sideLabel(c.side) }}</span></div>
      </div>
    </aside>
    <div class="hs-desk-stage" v-if="data">
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{
            empty: cell.empty,
            'hs-viol': isViol(cell),
            'hs-boundary': cell.col === data.boundary_col,
            'side-l': !cell.empty && cell.side === 'L',
            'side-r': !cell.empty && cell.side === 'R',
          }"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
</template>
