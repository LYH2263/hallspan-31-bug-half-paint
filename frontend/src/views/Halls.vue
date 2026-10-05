<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errorMessages } from '../api'
const rows = ref<any[]>([])
const edits = ref<Record<number, number>>({})
const errors = ref<string[]>([])
const notices = ref<string[]>([])
onMounted(async () => {
  rows.value = await api('/halls')
  for (const r of rows.value) edits.value[r.id] = r.boundary_col
})
async function save(r: any) {
  errors.value = []; notices.value = []
  try {
    const res = await api(`/halls/${r.id}`, {
      method: 'PUT',
      body: JSON.stringify({ boundary_col: Number(edits.value[r.id]) }),
    })
    r.boundary_col = res.boundary_col
    if (res.seating?.ok) {
      notices.value = [`分界列已保存为 ${res.boundary_col}，两本账与最新方案已更新`]
    } else {
      // 重提交失败：分界列已保存，但两本账与最新方案同失败、不增方案
      errors.value = res.seating?.errors?.length ? res.seating.errors : ['排座失败']
    }
  } catch (e) {
    errors.value = errorMessages(e)  // 分界列越界：拒绝保存，三处不动
  }
}
</script>
<template>
  <h1>考室</h1>
  <p class="sub">考室网格、最小曼哈顿间距与左右账分界列</p>
  <div v-if="errors.length" class="hs-errors">
    <div v-for="(m, i) in errors" :key="i">{{ m }}</div>
  </div>
  <div v-if="notices.length" class="card" style="color:var(--hs-ok)">
    <div v-for="(m, i) in notices" :key="i">{{ m }}</div>
  </div>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>行</th><th>列</th><th>最小间距</th><th>分界列</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.rows }}</td><td>{{ r.cols }}</td><td>{{ r.min_manhattan }}</td>
          <td>
            <input
              type="number" min="1" :max="r.cols - 1" v-model="edits[r.id]"
              style="width:4.5rem;font:inherit"
            />
            <span class="muted" style="font-size:0.72rem">（左账 0–{{ edits[r.id] - 1 }} 列 · 右账 {{ edits[r.id] }}–{{ r.cols - 1 }} 列）</span>
          </td>
          <td><button class="btn" @click="save(r)">保存</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
