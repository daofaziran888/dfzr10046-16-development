/** 度量目录浏览器导入确认的纯前端数据层：CSV 解析、类型、会话断线恢复。 */

export type ImportIssue = {
  field: string
  code: string
  message: string
}

export type ImportRow = {
  row_no: number
  source_line: number
  values: Record<string, string>
  issues: ImportIssue[]
  duplicate_in_file: boolean
  duplicate_positions: number[]
  conflict_in_file: boolean
  duplicate_existing: boolean
  existing_count: number
  decision: string
  result_status: string
  editable: boolean
  message: string
  measure_id: number | null
  candidate_id: string | null
  candidate_status: string
  candidate_adoptable: boolean
  candidate_status_text: string
  saved_at: string
}

export type ImportSession = {
  import_id: string
  filename: string
  created_at: string
  updated_at: string
  rows: ImportRow[]
  saved_rows: ImportRow[]
  conflict_rows: ImportRow[]
  skipped_rows: ImportRow[]
  pending_rows: ImportRow[]
  editable_row_nos: number[]
  verified_saved_row_nos: number[]
  counts: {
    total: number
    saved: number
    conflict: number
    skipped: number
    pending: number
    editable: number
  }
}

export type Candidate = {
  候选编号: string
  度量编号: string
  度量名称: string
  计算表达式: string
  来源导入: string
  来源文件: string
  来源行号: number
  度量条目ID: number
  状态: string
  状态说明: string
  可绑定: boolean
  确认采用: boolean
  绑定次数: number
  绑定编号: string[]
}

export type CandidateGroup = {
  度量编号: string
  needs_reconfirm: boolean
  message: string
  adoptable: Candidate | null
  candidates: Candidate[]
}

export type CandidateBoard = {
  total: number
  groups: CandidateGroup[]
  selectable: {
    value: string
    候选编号: string
    度量编号: string
    label: string
    计算表达式: string
    来源导入: string
  }[]
  candidate_count: number
}

export type ParsedCsv = {
  headers: string[]
  rows: Record<string, string>[]
}

/** 解析带引号、逗号和换行的 CSV；表头去掉 BOM 与首尾空白。 */
export function parseCsv(text: string): ParsedCsv {
  const source = text.replace(/^﻿/, '')
  const records: string[][] = []
  let field = ''
  let record: string[] = []
  let quoted = false
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index]
    if (quoted) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          quoted = false
        }
      } else {
        field += char
      }
      continue
    }
    if (char === '"') {
      quoted = true
    } else if (char === ',') {
      record.push(field)
      field = ''
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[index + 1] === '\n') index += 1
      record.push(field)
      field = ''
      if (record.some((value) => value.trim() !== '')) records.push(record)
      record = []
    } else {
      field += char
    }
  }
  if (field !== '' || record.length) {
    record.push(field)
    if (record.some((value) => value.trim() !== '')) records.push(record)
  }
  if (!records.length) return { headers: [], rows: [] }
  const headers = records[0].map((name) => name.trim())
  const rows = records.slice(1).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, (values[index] ?? '').trim()])),
  )
  return { headers, rows }
}

const STORAGE_PREFIX = 'measure-import:'

export function rememberImport(importId: string): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}latest`, importId)
  } catch {
    // 隐私模式下 localStorage 不可用时，断线恢复只保留在后端会话里。
  }
}

export function rememberedImport(): string {
  try {
    return localStorage.getItem(`${STORAGE_PREFIX}latest`) ?? ''
  } catch {
    return ''
  }
}

export function forgetImport(): void {
  try {
    localStorage.removeItem(`${STORAGE_PREFIX}latest`)
  } catch {
    // 同上。
  }
}

export const DECISION_OPTIONS = ['新增', '略过', '待修']

export function decisionTone(status: string): string {
  if (status === '已保存') return 'ok'
  if (status === '冲突') return 'danger'
  if (status === '待修' || status === '待确认') return 'warn'
  return 'muted'
}
