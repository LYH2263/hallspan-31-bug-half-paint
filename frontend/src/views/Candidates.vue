<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errorMessages } from '../api'
const rows = ref<any[]>([])
const errors = ref<string[]>([])
onMounted(async () => { rows.value = await api('/candidates') })
async function setSide(r: any, side: string) {
  errors.value = []
  try {
    const res = await api(`/candidates/${r.id}`, {
      method: 'PUT',
      body: JSON.stringify({ side: side || null }),
    })
    r.side = res.side
    if (!res.seating?.ok) {
      // 改标记后重提交失败：两本账与最新方案同失败、不增方案
      errors.value = res.seating?.errors?.length ? res.seating.errors : ['排座失败']
    }
  } catch (e) {
    errors.value = errorMessages(e)
  }
}
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">夹板名册样式 · 左右标记决定归入哪本账，未标记提交时归入且只归入一本账</p>
  <div v-if="errors.length" class="hs-errors">
    <div v-for="(m, i) in errors" :key="i">{{ m }}</div>
  </div>
  <div class="hs-clipboard" style="max-width:460px">
    <h2>考生名册 · Clipboard</h2>
    <div v-for="r in rows" :key="r.id ?? JSON.stringify(r)" class="hs-roster-row">
      <div>
        <div>{{ r.name }}</div>
        <div class="hs-ticket">{{ r.ticket_no }}</div>
      </div>
      <div>
        卷{{ r.paper_id }} · 室{{ r.hall_id }}
        <select
          :value="r.side ?? ''"
          @change="setSide(r, ($event.target as HTMLSelectElement).value)"
          style="margin-left:0.4rem;font:inherit"
        >
          <option value="">未标记</option>
          <option value="L">左账</option>
          <option value="R">右账</option>
        </select>
      </div>
    </div>
  </div>
</template>
