<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button v-if="meta.key === 'measure_catalog'" class="btn" data-testid="open-import"
          type="button" @click="showImport = true">
          导入度量登记表
        </button>
        <button v-if="meta.key === 'metric_bind'" class="btn" data-testid="open-candidates"
          type="button" @click="showCandidates = !showCandidates">
          {{ showCandidates ? '收起指标绑定候选' : '查看指标绑定候选' }}
        </button>
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <p class="page-desc" v-if="meta.key === 'metric_bind'" data-testid="bind-hint">
      引用度量只能选择真正登记成功的那一条；同编号多条表达式不同的导入登记需先在度量目录再次确认。
    </p>

    <CandidateBoard v-if="showCandidates" ref="candidateBoard" :import-id="rememberedImport()"
      @confirmed="(message) => { errorMessage = message; void reload() }" />

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <select v-if="meta.key === 'metric_bind' && field === '引用度量'"
            v-model="createValues[field]" :data-testid="`create-${field}`" required>
            <option value="">请选择当前可采用的度量</option>
            <option v-for="option in bindableOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <input v-else v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <p v-if="meta.key === 'metric_bind'" class="hint" data-testid="bind-options-note">
          可选引用 {{ bindableOptions.length }} 条，每个度量编号只露出当前可采用的一条。
        </p>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <MeasureImportDialog v-if="showImport" @close="showImport = false" @saved="reload" />

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import CandidateBoard from '@/components/CandidateBoard.vue'
import MeasureImportDialog from '@/components/MeasureImportDialog.vue'
import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import { loadBindableOptions } from '@/api/measure-import'
import { rememberedImport } from '@/domain/measureImport'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const showImport = ref(false)
const showCandidates = ref(false)
const candidateBoard = ref<InstanceType<typeof CandidateBoard> | null>(null)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const bindableOptions = ref<Awaited<ReturnType<typeof loadBindableOptions>>>([])
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
  if (meta.key === 'metric_bind') void loadOptions()
}

async function loadOptions() {
  try {
    bindableOptions.value = await loadBindableOptions()
  } catch (error) {
    bindableOptions.value = []
    errorMessage.value = error instanceof Error ? error.message : '可选度量读取失败'
  }
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

watch(showCandidates, (visible) => {
  if (visible) void candidateBoard.value?.reload()
})
watch(showCreate, (visible) => {
  if (visible && meta.key === 'metric_bind') void loadOptions()
})

onMounted(reload)
</script>
