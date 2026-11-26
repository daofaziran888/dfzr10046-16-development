import { request } from './client'
import type {
  CandidateBoard,
  ImportSession,
  ParsedCsv,
} from '@/domain/measureImport'

async function jsonOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (response.ok) return (await response.json()) as T
  let detail = fallback
  try {
    const body = (await response.json()) as { detail?: string }
    if (body?.detail) detail = body.detail
  } catch {
    // 非 JSON 错误体保留兜底文案。
  }
  throw new Error(detail)
}

export async function previewMeasureImport(
  filename: string,
  parsed: ParsedCsv,
): Promise<ImportSession> {
  const response = await request('/api/measure_catalog/imports/preview', {
    method: 'POST',
    body: JSON.stringify({ filename, rows: parsed.rows }),
  })
  return jsonOrThrow<ImportSession>(response, '登记表预览失败')
}

export async function loadMeasureImport(importId: string): Promise<ImportSession> {
  const response = await request(`/api/measure_catalog/imports/${importId}`)
  return jsonOrThrow<ImportSession>(response, '导入会话读取失败')
}

export async function commitMeasureImport(
  importId: string,
  decisions: { row_no: number; decision: string; values?: Record<string, string> }[],
): Promise<ImportSession> {
  const response = await request(`/api/measure_catalog/imports/${importId}/commit`, {
    method: 'POST',
    body: JSON.stringify({ decisions }),
  })
  return jsonOrThrow<ImportSession>(response, '导入提交失败')
}

export async function confirmMeasureImportRow(
  importId: string,
  rowNo: number,
): Promise<{ ok: boolean; message: string }> {
  const response = await request(`/api/measure_catalog/imports/${importId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ row_no: rowNo }),
  })
  return jsonOrThrow(response, '候选确认失败')
}

export async function loadCandidateBoard(): Promise<CandidateBoard> {
  const response = await request('/api/measure_catalog/binding-candidates')
  return jsonOrThrow<CandidateBoard>(response, '指标绑定候选清单读取失败')
}

export async function loadBindableOptions(): Promise<CandidateBoard['selectable']> {
  const response = await request('/api/metric_bind/bindable-options')
  const payload = await jsonOrThrow<{ items: CandidateBoard['selectable'] }>(
    response, '可绑定度量读取失败')
  return payload.items
}
