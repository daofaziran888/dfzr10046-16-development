<template>
  <div class="modal-backdrop" data-testid="import-modal">
    <div class="modal wide" role="dialog" aria-label="导入度量登记表">
      <header class="import-head">
        <div>
          <h3>浏览器导入度量登记表</h3>
          <p class="page-desc">
            上传带「度量编号」的 CSV，逐行选择新增、略过或保留待修；预览行序与文件行序一致。
          </p>
        </div>
        <button class="btn ghost" type="button" data-testid="import-close" @click="$emit('close')">
          关闭
        </button>
      </header>

      <p v-if="errorMessage" class="error-text" data-testid="import-error">{{ errorMessage }}</p>
      <p v-if="notice" class="notice-text" data-testid="import-notice">{{ notice }}</p>

      <div class="import-extra" v-if="!session">
        <label class="create-field">
          <span>或直接粘贴 CSV 文本（无本地文件时使用）</span>
          <textarea v-model="pasted" rows="5" data-testid="import-paste"
            placeholder="度量编号,度量名称,计算表达式,聚合方式,单位声明,精度位数,适用粒度,目录版本" />
        </label>
        <button class="btn" type="button" data-testid="import-parse-paste" :disabled="!pasted.trim()"
          @click="parsePasted">
          解析粘贴内容
        </button>
      </div>

      <div v-if="!session" class="import-upload">
        <label class="file-pick">
          <span>选择登记表（.csv）</span>
          <input type="file" accept=".csv,text/csv" data-testid="import-file"
            @change="onFileChange" />
        </label>
        <p class="hint">
          表头至少包含「度量编号」，推荐列：
          <span class="mono">{{ requiredColumns.join('、') }}</span>
        </p>
        <p v-if="pickedName" class="hint" data-testid="import-picked">已选择：{{ pickedName }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="$emit('close')">取消</button>
          <button class="btn primary" type="button" data-testid="import-preview"
            :disabled="!parsed || previewing" @click="doPreview">
            {{ previewing ? '解析中…' : '预览导入' }}
          </button>
        </div>
      </div>

      <template v-else>
        <div class="import-summary" data-testid="import-summary">
          <span>本次导入：<strong>{{ session.import_id }}</strong></span>
          <span>文件：{{ session.filename }}</span>
          <span data-testid="import-counts">
            共 {{ session.counts.total }} 行，已保存 {{ session.counts.saved }}，
            冲突 {{ session.counts.conflict }}，待修 {{ session.counts.pending }}，
            略过 {{ session.counts.skipped }}
          </span>
        </div>

        <div v-if="session.verified_saved_row_nos.length" class="saved-strip"
          data-testid="import-saved-strip">
          <strong>本次导入已实际保存的行：</strong>
          <span v-for="rowNo in session.verified_saved_row_nos" :key="rowNo" class="badge ok">
            第 {{ rowNo }} 行
          </span>
          <small>断线重连后按这些行对账，不依赖本地选择。</small>
        </div>
        <div v-if="session.conflict_rows.length" class="conflict-strip" data-testid="import-conflict-strip">
          <strong>与其他已保存记录分开的冲突行：</strong>
          <span v-for="row in session.conflict_rows" :key="row.row_no" class="badge danger">
            第 {{ row.row_no }} 行 · {{ row.values['度量编号'] }}
          </span>
          <small>这些行在预览后被同事抢先登记同编号，未写入度量目录，可改编号后再次提交。</small>
        </div>

        <table class="data-table import-table">
          <thead>
            <tr>
              <th>行号</th><th>度量编号</th><th>度量名称</th><th>计算表达式</th>
              <th>聚合方式</th><th>预览提示</th><th>处理选择</th><th>登记结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in session.rows" :key="row.row_no"
              :data-testid="`import-row-${row.row_no}`"
              :data-status="row.result_status"
              :data-conflict="row.result_status === '冲突' ? 'true' : 'false'"
              :class="{
                'row-conflict': row.result_status === '冲突',
                'row-saved': row.result_status === '已保存',
                'row-repair': row.result_status === '待修',
              }">
              <td>
                第 {{ row.row_no }} 行
                <small v-if="row.duplicate_in_file" class="cell-note">
                  与第 {{ row.duplicate_positions.join('、') }} 行同编号
                </small>
              </td>
              <td>
                <input v-if="row.editable" v-model="row.values['度量编号']"
                  :data-testid="`import-code-${row.row_no}`" :disabled="!row.editable" />
                <template v-else>{{ row.values['度量编号'] }}</template>
              </td>
              <td>
                <input v-if="row.editable" v-model="row.values['度量名称']"
                  :data-testid="`import-name-${row.row_no}`" />
                <template v-else>{{ row.values['度量名称'] }}</template>
              </td>
              <td>
                <input v-if="row.editable" v-model="row.values['计算表达式']" class="mono"
                  :data-testid="`import-expr-${row.row_no}`" />
                <span v-else class="mono">{{ row.values['计算表达式'] }}</span>
                <small v-if="row.conflict_in_file" class="cell-note">
                  与同文件其他行表达式不同，选中哪条需再次确认
                </small>
              </td>
              <td>
                <input v-if="row.editable" v-model="row.values['聚合方式']"
                  :data-testid="`import-agg-${row.row_no}`" />
                <template v-else>{{ row.values['聚合方式'] }}</template>
              </td>
              <td class="issue-cell">
                <span v-for="issue in row.issues" :key="issue.code + issue.field"
                  :class="['badge', issue.code.startsWith('duplicate') ? 'warn' : 'danger']">
                  {{ issue.message }}
                </span>
                <span v-if="!row.issues.length" class="cell-note">校验通过</span>
              </td>
              <td>
                <select v-model="row.decision" :data-testid="`import-decision-${row.row_no}`"
                  :disabled="row.result_status === '已保存'">
                  <option v-for="option in DECISION_OPTIONS" :key="option" :value="option">
                    {{ option }}
                  </option>
                </select>
              </td>
              <td>
                <span class="badge" :class="tone(row.result_status)"
                  :data-testid="`import-status-${row.row_no}`">{{ row.result_status }}</span>
                <small v-if="row.message" class="cell-note">{{ row.message }}</small>
                <small v-if="row.candidate_id" class="cell-note">
                  候选 {{ row.candidate_id }}：{{ row.candidate_status }}
                  <template v-if="row.candidate_status_text">· {{ row.candidate_status_text }}</template>
                </small>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="page-actions import-actions">
          <span class="hint" data-testid="import-editable">
            仍可修改的行：{{ session.editable_row_nos.length
              ? session.editable_row_nos.map((no) => `第 ${no} 行`).join('、')
              : '无' }}
          </span>
          <button class="btn" type="button" data-testid="import-reload" @click="recover">
            按本次导入核对已保存行
          </button>
          <button class="btn primary" type="button" data-testid="import-commit"
            :disabled="committing" @click="doCommit()">
            {{ committing ? '提交中…' : '提交导入结果' }}
          </button>
        </div>

        <CandidateBoard ref="boardRef" :import-id="session.import_id"
          @confirmed="(message) => { notice = message; void boardRef?.reload() }" />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import CandidateBoard from '@/components/CandidateBoard.vue'
import {
  commitMeasureImport,
  loadMeasureImport,
  previewMeasureImport,
} from '@/api/measure-import'
import {
  DECISION_OPTIONS,
  decisionTone as tone,
  forgetImport,
  parseCsv,
  rememberImport,
  rememberedImport,
} from '@/domain/measureImport'
import type { ImportSession, ParsedCsv } from '@/domain/measureImport'

const emit = defineEmits<{ (event: 'saved'): void; (event: 'close'): void }>()
const requiredColumns = ['度量编号', '度量名称', '计算表达式', '聚合方式', '单位声明', '精度位数', '适用粒度', '目录版本']

const session = ref<ImportSession | null>(null)
const parsed = ref<ParsedCsv | null>(null)
const pickedName = ref('')
const pasted = ref('')
const previewing = ref(false)
const committing = ref(false)
const errorMessage = ref('')
const notice = ref('')
const boardRef = ref<InstanceType<typeof CandidateBoard> | null>(null)

onMounted(async () => {
  const importId = rememberedImport()
  if (!importId) return
  try {
    const restored = await loadMeasureImport(importId)
    session.value = restored
    notice.value = `已按导入会话 ${restored.import_id} 恢复，实际保存过 ${restored.verified_saved_row_nos.length} 行`
  } catch {
    forgetImport()
  }
})

function parsePasted() {
  errorMessage.value = ''
  try {
    const result = parseCsv(pasted.value)
    if (!result.headers.includes('度量编号')) {
      throw new Error('粘贴内容缺少「度量编号」列，无法识别带编号的度量行')
    }
    if (!result.rows.length) throw new Error('粘贴内容没有数据行')
    parsed.value = result
    pickedName.value = `粘贴内容（${result.rows.length} 行）`
    notice.value = `已解析粘贴内容，共 ${result.rows.length} 行，可继续预览`
  } catch (error) {
    parsed.value = null
    errorMessage.value = error instanceof Error ? error.message : '粘贴内容解析失败'
  }
}

async function onFileChange(event: Event) {
  errorMessage.value = ''
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  pickedName.value = file.name
  try {
    parsed.value = parseCsv(await file.text())
    if (!parsed.value.headers.includes('度量编号')) {
      throw new Error('登记表缺少「度量编号」列，无法识别带编号的度量行')
    }
    if (!parsed.value.rows.length) throw new Error('登记表没有数据行')
  } catch (error) {
    parsed.value = null
    errorMessage.value = error instanceof Error ? error.message : '登记表解析失败'
  }
}

async function doPreview() {
  if (!parsed.value) return
  previewing.value = true
  errorMessage.value = ''
  notice.value = ''
  try {
    session.value = await previewMeasureImport(pickedName.value, parsed.value)
    rememberImport(session.value.import_id)
    notice.value = `预览完成，重复编号保留在原行位置；请逐行确认处理方式后提交`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记表预览失败'
  } finally {
    previewing.value = false
  }
}

function decisions() {
  return (session.value?.rows ?? [])
    .filter((row) => row.result_status !== '已保存')
    .map((row) => ({ row_no: row.row_no, decision: row.decision, values: row.values }))
}

async function doCommit(silent = false) {
  if (!session.value) return
  committing.value = true
  errorMessage.value = ''
  if (!silent) notice.value = ''
  try {
    session.value = await commitMeasureImport(session.value.import_id, decisions())
    if (session.value.counts.saved) {
      notice.value = `本次导入已实际保存 ${session.value.counts.saved} 行：${session.value.verified_saved_row_nos.map((no) => `第 ${no} 行`).join('、')}`
    }
    if (session.value.conflict_rows.length) {
      notice.value += `；${session.value.conflict_rows.length} 行因预览后被抢先登记而列为冲突`
    }
    await boardRef.value?.reload()
    emit('saved')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导入提交失败'
  } finally {
    committing.value = false
  }
}

async function recover() {
  if (!session.value) return
  errorMessage.value = ''
  try {
    session.value = await loadMeasureImport(session.value.import_id)
    notice.value = `已按导入会话 ${session.value.import_id} 核对，实际保存 ${session.value.counts.saved} 行`
    await boardRef.value?.reload()
    emit('saved')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导入会话恢复失败'
  }
}
</script>
