<template>
  <section class="candidate-board" data-testid="candidate-board">
    <header class="board-head">
      <div>
        <h3>指标绑定候选清单</h3>
        <p class="board-desc">
          每个度量编号只露出当前可采用的一条登记；同编号多条表达式不同的登记需要导入人再次确认。
        </p>
      </div>
      <button class="btn ghost" type="button" data-testid="candidate-refresh" @click="reload">
        刷新候选
      </button>
    </header>
    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    <p v-else-if="!board.groups.length" class="empty-state">还没有导入登记产生的指标绑定候选。</p>
    <div v-for="group in board.groups" :key="group.度量编号" class="candidate-group"
      :data-testid="`candidate-group-${group.度量编号}`"
      :data-needs-reconfirm="group.needs_reconfirm ? 'true' : 'false'">
      <div class="candidate-group-head">
        <strong>{{ group.度量编号 }}</strong>
        <span v-if="group.adoptable" class="badge ok" data-testid="candidate-adoptable">
          当前可采用：{{ group.adoptable.候选编号 }} · 第 {{ group.adoptable.来源行号 }} 行
        </span>
        <span v-else class="badge warn" data-testid="candidate-reconfirm-needed">等待导入人再次确认</span>
      </div>
      <p v-if="group.message" class="candidate-message">{{ group.message }}</p>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>候选编号</th><th>来源导入</th><th>来源行</th><th>度量名称</th>
            <th>计算表达式</th><th>状态</th><th>确认</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in group.candidates" :key="item.候选编号"
            :data-testid="`candidate-${item.候选编号}`" :data-adoptable="item.可绑定 ? 'true' : 'false'">
            <td>{{ item.候选编号 }}</td>
            <td>{{ item.来源导入 }} · {{ item.来源文件 }}</td>
            <td>第 {{ item.来源行号 }} 行</td>
            <td>{{ item.度量名称 }}</td>
            <td class="mono">{{ item.计算表达式 }}</td>
            <td>
              <span class="badge" :class="item.可绑定 ? 'ok' : 'warn'">{{ item.状态 }}</span>
              <small class="cell-note">{{ item.状态说明 }}</small>
            </td>
            <td>
              <button v-if="importId && item.状态 !== '已确认'"
                class="link" type="button" :data-testid="`candidate-confirm-${item.候选编号}`"
                @click="confirm(item)">
                确认采用
              </button>
              <span v-else-if="!importId && !item.确认采用" class="cell-note">
                请回度量目录发起导入后确认
              </span>
              <span v-else-if="item.确认采用" class="cell-note">已确认</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { confirmMeasureImportRow, loadCandidateBoard } from '@/api/measure-import'
import type { Candidate, CandidateBoard } from '@/domain/measureImport'

const props = defineProps<{ importId?: string }>()
const emit = defineEmits<{ (event: 'confirmed', message: string): void }>()
const board = ref<CandidateBoard>({ total: 0, groups: [], selectable: [], candidate_count: 0 })
const errorMessage = ref('')

async function reload() {
  errorMessage.value = ''
  try {
    board.value = await loadCandidateBoard()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选清单读取失败'
  }
}

async function confirm(item: Candidate) {
  if (!props.importId) return
  errorMessage.value = ''
  try {
    const result = await confirmMeasureImportRow(props.importId, item.来源行号)
    if (!result.ok) throw new Error(result.message)
    await reload()
    emit('confirmed', result.message)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认失败'
  }
}

defineExpose({ reload })
onMounted(reload)
</script>
