import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// ── Tasks ──────────────────────────────────────────────────────────────────
export const createTask = (folderPath: string, name?: string) =>
  api.post('/tasks', { folder_path: folderPath, name })

export const listTasks = () =>
  api.get('/tasks')

export const getTask = (taskId: number) =>
  api.get(`/tasks/${taskId}`)

export const deleteTask = (taskId: number) =>
  api.delete(`/tasks/${taskId}`)

// ── Scan ───────────────────────────────────────────────────────────────────
export const startScan = (taskId: number) =>
  api.post(`/tasks/${taskId}/scan`)

export const getScanStatus = (taskId: number) =>
  api.get(`/tasks/${taskId}/scan/status`)

export const getScanSummary = (taskId: number) =>
  api.get(`/tasks/${taskId}/scan/summary`)

export const listFiles = (taskId: number, params?: Record<string, any>) =>
  api.get(`/tasks/${taskId}/files`, { params })

// ── Duplicates ─────────────────────────────────────────────────────────────
export const startDuplicateDetection = (taskId: number, similarityLevel = 'standard') =>
  api.post(`/tasks/${taskId}/duplicates/detect`, null, { params: { similarity_level: similarityLevel } })

export const listDuplicateGroups = (taskId: number, params?: Record<string, any>) =>
  api.get(`/tasks/${taskId}/duplicates/groups`, { params })

export const setMemberAction = (taskId: number, groupId: number, memberId: number, action: string) =>
  api.put(`/tasks/${taskId}/duplicates/groups/${groupId}/members/${memberId}`, { action })

export const executeDeletions = (taskId: number) =>
  api.post(`/tasks/${taskId}/duplicates/execute`)

// ── Files ──────────────────────────────────────────────────────────────────
export const getThumbnailUrl = (fileId: number) =>
  `/api/files/${fileId}/thumbnail`

export const getOriginalUrl = (fileId: number) =>
  `/api/files/${fileId}/original`

// ── Logs ───────────────────────────────────────────────────────────────────
export const listLogs = (params?: Record<string, any>) =>
  api.get('/logs', { params })

// ── WebSocket ──────────────────────────────────────────────────────────────
export function connectTaskWs(taskId: number, onMessage: (event: string, data: any) => void) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/tasks/${taskId}/progress`)
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      onMessage(msg.event, msg.data)
    } catch { /* ignore */ }
  }
  return ws
}

export default api
