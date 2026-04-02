<template>
  <div>
    <!-- 顶部标题 + 操作按钮 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">时间 / EXIF 修正</n-h2>
      <n-button type="primary" :loading="analyzing" :disabled="analyzing" @click="handleAnalyze">
        {{ analyzing ? '分析中...' : '分析 EXIF' }}
      </n-button>
    </div>

    <!-- 进度卡片 -->
    <n-card v-if="analyzing" title="分析进度" style="margin-bottom: 16px">
      <n-space vertical :size="8">
        <n-text>已处理 {{ progressCurrent }} / {{ progressTotal }} 个文件</n-text>
        <n-progress
          type="line"
          :percentage="progressTotal > 0 ? Math.round((progressCurrent / progressTotal) * 100) : 0"
          :processing="analyzing"
          indicator-placement="inside"
        />
      </n-space>
    </n-card>

    <!-- 统计卡片 -->
    <n-grid v-if="hasResult && !analyzing" :x-gap="16" :y-gap="16" :cols="4" style="margin-bottom: 24px">
      <n-gi>
        <n-card>
          <n-statistic label="图片总数" :value="stats.total_files" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="有 EXIF" :value="stats.has_exif" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="无 EXIF" :value="stats.no_exif" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="时间异常" :value="stats.has_anomaly" tabular-nums />
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 筛选 + 批量偏移工具栏 -->
    <div v-if="hasResult && !analyzing" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
        <n-tabs v-model:value="filterMode" type="segment" @update:value="handleFilterChange">
          <n-tab-pane name="all" tab="全部" />
          <n-tab-pane name="anomaly" tab="只看异常" />
        </n-tabs>

        <!-- 批量偏移工具栏（有勾选时显示） -->
        <n-card v-if="checkedRowKeys.length > 0" size="small" style="flex: 1; min-width: 400px">
          <n-space align="center">
            <n-text>已选 {{ checkedRowKeys.length }} 个文件，时间偏移：</n-text>
            <n-input-number
              v-model:value="offsetHours"
              :min="-9999"
              :max="9999"
              size="small"
              style="width: 100px"
            >
              <template #suffix>小时</template>
            </n-input-number>
            <n-input-number
              v-model:value="offsetMinutes"
              :min="-59"
              :max="59"
              size="small"
              style="width: 100px"
            >
              <template #suffix>分钟</template>
            </n-input-number>
            <n-text depth="3" style="font-size: 12px">
              共 {{ offsetTotalSeconds >= 0 ? '+' : '' }}{{ offsetTotalSeconds }} 秒
            </n-text>
            <n-button
              type="warning"
              size="small"
              :disabled="offsetTotalSeconds === 0"
              @click="handleBatchOffset"
            >
              确认偏移
            </n-button>
          </n-space>
        </n-card>
      </div>
    </div>

    <!-- 文件列表 -->
    <n-spin :show="tableLoading">
      <n-data-table
        v-if="hasResult || fileList.length > 0"
        :columns="columns"
        :data="fileList"
        :row-key="(row: ExifFile) => row.id"
        :checked-row-keys="checkedRowKeys"
        @update:checked-row-keys="(keys: number[]) => checkedRowKeys = keys"
        :pagination="pagination"
        @update:page="handlePageChange"
        :scroll-x="1200"
        size="small"
      />
      <n-empty v-else-if="!analyzing" description="请先点击「分析 EXIF」按钮" style="padding: 60px 0" />
    </n-spin>

    <!-- 单文件修正时间 Modal -->
    <n-modal v-model:show="showEditModal" preset="card" title="修正拍摄时间" style="width: 420px">
      <n-space vertical>
        <n-text v-if="editingFile" depth="3">{{ editingFile.file_name }}</n-text>
        <n-date-picker
          v-model:value="editTimeValue"
          type="datetime"
          style="width: 100%"
          clearable
        />
        <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px">
          <n-button @click="showEditModal = false">取消</n-button>
          <n-button type="primary" :loading="editLoading" @click="handleSetTime">确认</n-button>
        </div>
      </n-space>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import {
  NTag, NButton, NTooltip, NEllipsis,
  useMessage, useDialog,
  type DataTableColumns,
} from 'naive-ui'
import {
  startExifAnalyze,
  listExifFiles,
  setFileExifTime,
  batchOffsetExifTime,
  connectTaskWs,
} from '../api/index'
import { useTaskStore } from '../stores/task'

const props = defineProps<{ taskId: number }>()
const message = useMessage()
const dialog = useDialog()
const taskStore = useTaskStore()

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface ExifFile {
  id: number
  file_name: string
  relative_path: string
  extension: string
  file_type: string
  has_exif: boolean
  exif_time: string | null
  file_created: string | null
  file_modified: string | null
  best_time: string | null
  time_source: string | null
  time_anomaly: string | null
}

// ── 状态 ──────────────────────────────────────────────────────────────────────
const analyzing = ref(false)
const tableLoading = ref(false)
const progressCurrent = ref(0)
const progressTotal = ref(0)
const hasResult = ref(false)
const fileList = ref<ExifFile[]>([])
const filterMode = ref<'all' | 'anomaly'>('all')
const checkedRowKeys = ref<number[]>([])
const stats = ref({ total_files: 0, has_exif: 0, no_exif: 0, has_anomaly: 0 })
const pagination = ref({ page: 1, pageSize: 50, itemCount: 0 })

// 批量偏移
const offsetHours = ref(0)
const offsetMinutes = ref(0)
const offsetTotalSeconds = computed(() => (offsetHours.value * 3600) + (offsetMinutes.value * 60))

// 单文件修正
const showEditModal = ref(false)
const editingFile = ref<ExifFile | null>(null)
const editTimeValue = ref<number | null>(null)
const editLoading = ref(false)

// ── 时区工具 ──────────────────────────────────────────────────────────────────
function utcToLocal(utcStr: string | null): string {
  if (!utcStr) return '-'
  // 手动加 8h，避免依赖系统时区
  const d = new Date(utcStr)
  const shifted = new Date(d.getTime() + 8 * 3600 * 1000)
  return shifted.toISOString().replace('T', ' ').slice(0, 19)
}

// n-date-picker 返回的是本机时区毫秒时间戳
// 固定视为 UTC+8，减 8h 转为 UTC ISO 字符串传给后端
function timestampToUtcIso(ts: number): string {
  return new Date(ts - 8 * 3600 * 1000).toISOString()
}

// UTC ISO 字符串 → 本机时间戳（给 n-date-picker 使用，假设系统 UTC+8）
function utcIsoToTimestamp(utcStr: string): number {
  const d = new Date(utcStr)
  return d.getTime() + 8 * 3600 * 1000
}

// ── 表格列 ────────────────────────────────────────────────────────────────────
const sourceTypeMap: Record<string, { type: 'success' | 'warning' | 'info' | 'default'; label: string }> = {
  exif: { type: 'success', label: 'EXIF' },
  filename: { type: 'warning', label: '文件名' },
  manual: { type: 'info', label: '手动' },
  fs: { type: 'default', label: '文件系统' },
  unknown: { type: 'default', label: '未知' },
}

const anomalyLabelMap: Record<string, string> = {
  no_exif: '无 EXIF',
  future_time: '未来时间',
  too_old: '时间过早',
  exif_fs_mismatch: 'EXIF/文件时间偏差大',
}

function renderAnomalyTag(anomaly: string | null) {
  if (!anomaly) return null
  const labels = anomaly.split(',').map(k => anomalyLabelMap[k] || k).join('、')
  return h(NTooltip, null, {
    trigger: () => h(NTag, { type: 'error', size: 'small' }, { default: () => '异常' }),
    default: () => labels,
  })
}

const columns = computed<DataTableColumns<ExifFile>>(() => [
  { type: 'selection', fixed: 'left' },
  {
    title: '文件名',
    key: 'file_name',
    width: 220,
    fixed: 'left',
    render: (row) => h(NEllipsis, { style: 'max-width: 200px' }, { default: () => row.file_name }),
  },
  { title: '格式', key: 'extension', width: 70 },
  {
    title: 'EXIF 时间',
    key: 'exif_time',
    width: 160,
    render: (row) => utcToLocal(row.exif_time),
  },
  {
    title: '文件修改时间',
    key: 'file_modified',
    width: 160,
    render: (row) => utcToLocal(row.file_modified),
  },
  {
    title: '最佳时间',
    key: 'best_time',
    width: 160,
    render: (row) => utcToLocal(row.best_time),
  },
  {
    title: '来源',
    key: 'time_source',
    width: 90,
    render: (row) => {
      const src = row.time_source || 'unknown'
      const cfg = sourceTypeMap[src] || { type: 'default', label: src }
      return h(NTag, { type: cfg.type, size: 'small' }, { default: () => cfg.label })
    },
  },
  {
    title: '异常',
    key: 'time_anomaly',
    width: 80,
    render: (row) => renderAnomalyTag(row.time_anomaly),
  },
  {
    title: '操作',
    key: 'action',
    width: 90,
    fixed: 'right',
    render: (row) => h(NButton, { size: 'tiny', onClick: () => openEditModal(row) }, { default: () => '修正时间' }),
  },
])

// ── 数据加载 ──────────────────────────────────────────────────────────────────
async function loadFiles() {
  tableLoading.value = true
  try {
    const res = await listExifFiles(props.taskId, {
      filter: filterMode.value,
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
    })
    fileList.value = res.data.files
    pagination.value.itemCount = res.data.total
    stats.value = res.data.stats
    hasResult.value = true
  } catch {
    // 无数据时静默处理
  } finally {
    tableLoading.value = false
  }
}

function handleFilterChange() {
  pagination.value.page = 1
  checkedRowKeys.value = []
  loadFiles()
}

function handlePageChange(page: number) {
  pagination.value.page = page
  checkedRowKeys.value = []
  loadFiles()
}

// ── 分析 EXIF ─────────────────────────────────────────────────────────────────
function handleAnalyze() {
  analyzing.value = true
  progressCurrent.value = 0
  progressTotal.value = 0

  startExifAnalyze(props.taskId).catch(() => {
    analyzing.value = false
    message.error('启动失败，请检查后端日志')
  })

  const ws = connectTaskWs(props.taskId, (event, data) => {
    if (event === 'exif_start') {
      progressTotal.value = data.total
    } else if (event === 'exif_progress') {
      progressCurrent.value = data.current
      progressTotal.value = data.total
    } else if (event === 'exif_complete') {
      analyzing.value = false
      ws.close()
      loadFiles()
      message.success(`分析完成：${data.total} 张图片，${data.has_anomaly} 个异常`)
    } else if (event === 'exif_error') {
      analyzing.value = false
      ws.close()
      message.error(`分析失败：${data.message}`)
    }
  })
}

// ── 批量偏移 ──────────────────────────────────────────────────────────────────
function handleBatchOffset() {
  const seconds = offsetTotalSeconds.value
  if (seconds === 0) return

  const sign = seconds > 0 ? '+' : ''
  const h = Math.abs(Math.floor(seconds / 3600))
  const m = Math.abs(Math.floor((seconds % 3600) / 60))
  const desc = `${sign}${h > 0 ? h + ' 小时 ' : ''}${m > 0 ? m + ' 分钟' : ''}`.trim() || `${sign}${seconds} 秒`

  dialog.warning({
    title: '确认批量偏移',
    content: `将对选中的 ${checkedRowKeys.value.length} 个文件时间偏移 ${sign}${seconds} 秒（${desc}），此操作会修改文件的 EXIF（JPEG），确认继续？`,
    positiveText: '确认',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const res = await batchOffsetExifTime(props.taskId, checkedRowKeys.value as number[], seconds)
        message.success(`已偏移 ${res.data.updated} 个文件${res.data.errors.length > 0 ? `，${res.data.errors.length} 个失败` : ''}`)
        checkedRowKeys.value = []
        loadFiles()
      } catch {
        message.error('偏移失败')
      }
    },
  })
}

// ── 单文件修正 ────────────────────────────────────────────────────────────────
function openEditModal(file: ExifFile) {
  editingFile.value = file
  // 将 best_time（UTC）转为 UTC+8 时间戳给 date-picker
  editTimeValue.value = file.best_time ? utcIsoToTimestamp(file.best_time) : null
  showEditModal.value = true
}

async function handleSetTime() {
  if (!editingFile.value || editTimeValue.value === null) return
  editLoading.value = true
  try {
    // 将 date-picker 的 timestamp（视为 UTC+8）转为 UTC ISO 字符串
    const utcIso = timestampToUtcIso(editTimeValue.value)
    // 后端接受 UTC+8 展示时间，所以传 local 时间字符串（直接用 +8h 格式）
    const localStr = new Date(editTimeValue.value).toISOString().replace('T', ' ').slice(0, 19)
    await setFileExifTime(editingFile.value.id, localStr)
    message.success('时间已修正')
    showEditModal.value = false
    loadFiles()
  } catch {
    message.error('修正失败')
  } finally {
    editLoading.value = false
  }
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
onMounted(async () => {
  await taskStore.fetchTask(props.taskId)
  // 尝试加载已有分析结果
  await loadFiles()
})
</script>
