<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">扫描与文件构成</n-h2>
      <n-space>
        <n-button type="primary" :loading="scanning" @click="handleScan" :disabled="scanning">
          {{ scanning ? '扫描中...' : (hasScanResult ? '重新扫描' : '开始扫描') }}
        </n-button>
      </n-space>
    </div>

    <!-- Progress -->
    <n-card v-if="scanning" title="扫描进度" style="margin-bottom: 16px">
      <n-progress type="line" :percentage="scanProgress" :processing="scanning" indicator-placement="inside" />
      <n-text depth="3" style="margin-top: 8px; display: block">
        {{ scanCurrent }} / {{ scanTotal }} 文件
      </n-text>
    </n-card>

    <!-- Summary -->
    <template v-if="hasScanResult && !scanning">
      <!-- Type stats cards -->
      <n-grid :x-gap="16" :y-gap="16" :cols="4" style="margin-bottom: 24px">
        <n-gi>
          <n-card>
            <n-statistic label="总文件数" :value="summary.total" tabular-nums />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card>
            <n-statistic label="图片" :value="summary.by_type?.image || 0" tabular-nums>
              <template #suffix>
                <n-text depth="3"> / {{ summary.total }}</n-text>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card>
            <n-statistic label="视频" :value="summary.by_type?.video || 0" tabular-nums />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card>
            <n-statistic label="其他文件" :value="summary.by_type?.other || 0" tabular-nums />
          </n-card>
        </n-gi>
      </n-grid>

      <!-- Extension breakdown -->
      <n-card title="按扩展名统计" style="margin-bottom: 24px">
        <n-data-table :columns="extColumns" :data="extData" :pagination="false" size="small" :max-height="400" />
      </n-card>

      <!-- File list -->
      <n-card title="文件列表">
        <template #header-extra>
          <n-space>
            <n-select
              v-model:value="fileTypeFilter"
              :options="fileTypeOptions"
              placeholder="按类型筛选"
              clearable
              style="width: 150px"
              size="small"
            />
          </n-space>
        </template>
        <n-data-table
          :columns="fileColumns"
          :data="fileList"
          :pagination="filePagination"
          :loading="filesLoading"
          @update:page="handlePageChange"
          size="small"
          :max-height="500"
        />
      </n-card>
    </template>

    <n-empty v-if="!hasScanResult && !scanning" description="点击「开始扫描」分析文件夹内容" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { useMessage, NTag, NText } from 'naive-ui'
import { useTaskStore } from '../stores/task'
import { startScan, getScanSummary, listFiles, connectTaskWs } from '../api'

const props = defineProps<{ taskId: number }>()
const message = useMessage()
const taskStore = useTaskStore()

const scanning = ref(false)
const scanTotal = ref(0)
const scanCurrent = ref(0)
const summary = ref<any>({})
const hasScanResult = ref(false)

// Files
const fileList = ref<any[]>([])
const filesLoading = ref(false)
const fileTypeFilter = ref<string | null>(null)
const filePagination = ref({ page: 1, pageSize: 50, itemCount: 0 })

// WebSocket
let ws: WebSocket | null = null

const scanProgress = computed(() =>
  scanTotal.value > 0 ? Math.round((scanCurrent.value / scanTotal.value) * 100) : 0
)

const fileTypeOptions = [
  { label: '图片', value: 'image' },
  { label: '视频', value: 'video' },
  { label: '其他', value: 'other' },
]

// Extension table
const extColumns = [
  { title: '扩展名', key: 'ext', width: 120 },
  {
    title: '数量',
    key: 'count',
    width: 100,
    sorter: (a: any, b: any) => a.count - b.count,
  },
  {
    title: '占比',
    key: 'percent',
    width: 100,
    render: (row: any) => `${((row.count / (summary.value.total || 1)) * 100).toFixed(1)}%`,
  },
]

const extData = computed(() => {
  if (!summary.value.by_extension) return []
  return Object.entries(summary.value.by_extension).map(([ext, count]) => ({
    ext,
    count: count as number,
  }))
})

// File table columns
function formatSize(bytes: number | null) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const fileColumns = [
  { title: '文件名', key: 'file_name', ellipsis: { tooltip: true }, minWidth: 200 },
  { title: '路径', key: 'relative_path', ellipsis: { tooltip: true }, minWidth: 200 },
  {
    title: '类型',
    key: 'file_type',
    width: 80,
    render: (row: any) => {
      const typeMap: Record<string, 'success' | 'info' | 'warning' | 'default'> = { image: 'success', video: 'info', other: 'warning' }
      return h(NTag, { type: typeMap[row.file_type] || 'default' as const, size: 'small' }, () => row.file_type)
    },
  },
  { title: '扩展名', key: 'extension', width: 80 },
  {
    title: '大小',
    key: 'file_size',
    width: 100,
    render: (row: any) => formatSize(row.file_size),
    sorter: (a: any, b: any) => (a.file_size || 0) - (b.file_size || 0),
  },
]

onMounted(async () => {
  await taskStore.fetchTask(props.taskId)
  if (taskStore.currentTask?.status === 'ready' || taskStore.currentTask?.status === 'completed') {
    await loadSummary()
    await loadFiles()
  }
})

onUnmounted(() => {
  ws?.close()
})

async function handleScan() {
  scanning.value = true
  scanCurrent.value = 0
  scanTotal.value = 0

  // Connect WebSocket
  ws = connectTaskWs(props.taskId, (event, data) => {
    if (event === 'scan_start') {
      scanTotal.value = data.total
    } else if (event === 'scan_progress') {
      scanCurrent.value = data.current
    } else if (event === 'scan_complete') {
      scanning.value = false
      message.success(`扫描完成: ${data.total} 个文件`)
      loadSummary()
      loadFiles()
      ws?.close()
    }
  })

  try {
    await startScan(props.taskId)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '启动扫描失败')
    scanning.value = false
  }
}

async function loadSummary() {
  try {
    const res = await getScanSummary(props.taskId)
    summary.value = res.data
    hasScanResult.value = true
  } catch { /* ignore */ }
}

async function loadFiles() {
  filesLoading.value = true
  try {
    const res = await listFiles(props.taskId, {
      page: filePagination.value.page,
      page_size: filePagination.value.pageSize,
      file_type: fileTypeFilter.value || undefined,
    })
    fileList.value = res.data.items
    filePagination.value.itemCount = res.data.total
  } catch { /* ignore */ }
  filesLoading.value = false
}

function handlePageChange(page: number) {
  filePagination.value.page = page
  loadFiles()
}
</script>
