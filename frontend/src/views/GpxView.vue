<template>
  <div>
    <!-- 顶部标题 + 操作区 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">GPS 匹配</n-h2>
      <n-space>
        <n-button v-if="hasResult" type="error" secondary @click="handleClear">清空匹配</n-button>
        <n-button type="primary" :loading="matching" :disabled="matching || gpxPaths.length === 0" @click="handleMatch">
          {{ matching ? '匹配中...' : '开始匹配' }}
        </n-button>
      </n-space>
    </div>

    <!-- GPX 路径输入 -->
    <n-card title="GPX 文件路径" style="margin-bottom: 16px">
      <n-dynamic-input
        v-model:value="gpxPaths"
        :min="1"
        placeholder="粘贴 GPX 文件的本地路径，例如：D:\tracks\2023-08-15.gpx"
        :disabled="matching"
      />
      <n-text depth="3" style="font-size: 12px; margin-top: 8px; display: block">
        支持多个 GPX 文件（多设备、多天轨迹），时间重叠时自动取最近轨迹点
      </n-text>
    </n-card>

    <!-- 进度卡片 -->
    <n-card v-if="matching" title="匹配进度" style="margin-bottom: 16px">
      <n-space vertical :size="8">
        <n-text>已处理 {{ progressCurrent }} / {{ progressTotal }} 个文件</n-text>
        <n-progress
          type="line"
          :percentage="progressTotal > 0 ? Math.round((progressCurrent / progressTotal) * 100) : 0"
          :processing="matching"
          indicator-placement="inside"
        />
      </n-space>
    </n-card>

    <!-- 统计卡片 -->
    <n-grid v-if="hasResult && !matching" :x-gap="16" :y-gap="16" :cols="4" style="margin-bottom: 24px">
      <n-gi>
        <n-card>
          <n-statistic label="参与匹配" :value="stats.total" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="匹配良好 (≤5分钟)" :value="stats.good" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="偏差较大 (>5分钟)" :value="stats.warning" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="无匹配" :value="stats.no_match" tabular-nums />
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 轨迹图 -->
    <n-collapse v-if="hasResult && !matching" style="margin-bottom: 16px">
      <n-collapse-item title="轨迹图" name="map">
        <n-spin :show="trackLoading">
          <gpx-track-map :track="trackData" :photos="photoPoints" :height="420" />
        </n-spin>
      </n-collapse-item>
    </n-collapse>

    <!-- 筛选 + 批量写入工具栏 -->
    <div v-if="hasResult && !matching" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
        <n-tabs v-model:value="filterMode" type="segment" @update:value="handleFilterChange">
          <n-tab-pane name="all" tab="全部" />
          <n-tab-pane name="good" tab="匹配良好" />
          <n-tab-pane name="warning" tab="偏差较大" />
          <n-tab-pane name="no_match" tab="无匹配" />
        </n-tabs>

        <!-- 批量写入工具栏（有勾选时显示） -->
        <n-card v-if="checkedRowKeys.length > 0" size="small" style="flex: 1; min-width: 420px">
          <n-space align="center">
            <n-text>已选 {{ checkedRowKeys.length }} 个文件，写入模式：</n-text>
            <n-radio-group v-model:value="writeMode" size="small">
              <n-radio-button value="fill_only">仅补写无 GPS</n-radio-button>
              <n-radio-button value="overwrite">覆盖所有</n-radio-button>
            </n-radio-group>
            <n-button type="primary" size="small" @click="handleExecuteWrite">
              写入 GPS 到 EXIF
            </n-button>
          </n-space>
        </n-card>
      </div>
    </div>

    <!-- 结果列表 -->
    <n-spin :show="tableLoading">
      <n-data-table
        v-if="hasResult || matchList.length > 0"
        :columns="columns"
        :data="matchList"
        :row-key="(row: GpxMatchRow) => row.file_id"
        :checked-row-keys="checkedRowKeys"
        @update:checked-row-keys="(keys: number[]) => checkedRowKeys = keys"
        :pagination="pagination"
        @update:page="handlePageChange"
        :scroll-x="1100"
        size="small"
      />
      <n-empty v-else-if="!matching" description="请输入 GPX 文件路径后点击「开始匹配」" style="padding: 60px 0" />
    </n-spin>
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
  startGpxMatch,
  getGpxResults,
  getGpxTrack,
  executeGpsWrite,
  clearGpxMatches,
  connectTaskWs,
} from '../api/index'
import { useTaskStore } from '../stores/task'
import GpxTrackMap from '../components/gpx/GpxTrackMap.vue'

const props = defineProps<{ taskId: number }>()
const message = useMessage()
const dialog = useDialog()
const taskStore = useTaskStore()

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface GpxMatchRow {
  id: number
  file_id: number
  file_name: string
  relative_path: string
  extension: string
  best_time: string | null
  matched_lat: number | null
  matched_lng: number | null
  time_offset_sec: number | null
  match_quality: string
  user_confirmed: boolean
  original_has_gps: boolean
}

// ── 状态 ──────────────────────────────────────────────────────────────────────
const matching = ref(false)
const tableLoading = ref(false)
const progressCurrent = ref(0)
const progressTotal = ref(0)
const hasResult = ref(false)
const matchList = ref<GpxMatchRow[]>([])
const filterMode = ref<'all' | 'good' | 'warning' | 'no_match'>('all')
const checkedRowKeys = ref<number[]>([])
const stats = ref({ total: 0, good: 0, warning: 0, no_match: 0 })
const pagination = ref({ page: 1, pageSize: 50, itemCount: 0 })
const gpxPaths = ref<string[]>([''])
const writeMode = ref<'fill_only' | 'overwrite'>('fill_only')

// 轨迹图数据
const trackLoading = ref(false)
const trackData = ref<[number, number][]>([])
const photoPoints = ref<any[]>([])

// ── 工具函数 ──────────────────────────────────────────────────────────────────
function utcToLocal(utcStr: string | null): string {
  if (!utcStr) return '-'
  const d = new Date(utcStr)
  const shifted = new Date(d.getTime() + 8 * 3600 * 1000)
  return shifted.toISOString().replace('T', ' ').slice(0, 19)
}

function formatOffset(sec: number | null): string {
  if (sec === null) return '-'
  const sign = sec >= 0 ? '+' : '-'
  const abs = Math.abs(sec)
  const h = Math.floor(abs / 3600)
  const m = Math.floor((abs % 3600) / 60)
  const s = abs % 60
  if (h > 0) return `${sign}${h}h${m}m`
  if (m > 0) return `${sign}${m}m${s}s`
  return `${sign}${s}s`
}

function formatCoord(lat: number | null, lng: number | null): string {
  if (lat === null || lng === null) return '-'
  return `${lat.toFixed(6)}, ${lng.toFixed(6)}`
}

// ── 表格列 ────────────────────────────────────────────────────────────────────
const qualityConfig: Record<string, { type: 'success' | 'warning' | 'error'; label: string }> = {
  good: { type: 'success', label: '良好' },
  warning: { type: 'warning', label: '偏差大' },
  no_match: { type: 'error', label: '无匹配' },
}

const columns = computed<DataTableColumns<GpxMatchRow>>(() => [
  { type: 'selection', fixed: 'left', disabled: (row) => row.match_quality === 'no_match' },
  {
    title: '文件名',
    key: 'file_name',
    width: 220,
    fixed: 'left',
    render: (row) => h(NEllipsis, { style: 'max-width: 200px' }, { default: () => row.file_name }),
  },
  { title: '格式', key: 'extension', width: 70 },
  {
    title: '拍摄时间',
    key: 'best_time',
    width: 160,
    render: (row) => utcToLocal(row.best_time),
  },
  {
    title: '匹配坐标',
    key: 'coords',
    width: 180,
    render: (row) => {
      const coord = formatCoord(row.matched_lat, row.matched_lng)
      if (coord === '-') return '-'
      return h(
        NTooltip,
        null,
        {
          trigger: () => h('span', { style: 'cursor: pointer; color: #18a058', onClick: () => openMap(row) }, coord),
          default: () => '点击在浏览器中查看地图',
        }
      )
    },
  },
  {
    title: '时间偏差',
    key: 'time_offset_sec',
    width: 100,
    render: (row) => formatOffset(row.time_offset_sec),
  },
  {
    title: '匹配质量',
    key: 'match_quality',
    width: 100,
    render: (row) => {
      const cfg = qualityConfig[row.match_quality] || { type: 'default', label: row.match_quality }
      return h(NTag, { type: cfg.type, size: 'small' }, { default: () => cfg.label })
    },
  },
  {
    title: '原有GPS',
    key: 'original_has_gps',
    width: 80,
    render: (row) =>
      row.original_has_gps
        ? h(NTag, { type: 'info', size: 'small' }, { default: () => '有' })
        : '-',
  },
  {
    title: '已写入',
    key: 'user_confirmed',
    width: 70,
    render: (row) =>
      row.user_confirmed
        ? h(NTag, { type: 'success', size: 'small' }, { default: () => '✓' })
        : '-',
  },
])

// ── 打开地图 ──────────────────────────────────────────────────────────────────
function openMap(row: GpxMatchRow) {
  if (row.matched_lat !== null && row.matched_lng !== null) {
    window.open(`https://www.google.com/maps?q=${row.matched_lat},${row.matched_lng}`, '_blank')
  }
}

// ── 数据加载 ──────────────────────────────────────────────────────────────────
async function loadResults() {
  tableLoading.value = true
  try {
    const res = await getGpxResults(props.taskId, {
      filter: filterMode.value,
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
    })
    matchList.value = res.data.matches
    pagination.value.itemCount = res.data.total
    stats.value = res.data.stats
    hasResult.value = res.data.stats.total > 0
  } catch {
    // 无数据时静默
  } finally {
    tableLoading.value = false
  }
}

async function loadTrack() {
  trackLoading.value = true
  try {
    const res = await getGpxTrack(props.taskId)
    trackData.value = res.data.track
    photoPoints.value = res.data.photos
  } catch {
    // 静默
  } finally {
    trackLoading.value = false
  }
}

function handleFilterChange() {
  pagination.value.page = 1
  checkedRowKeys.value = []
  loadResults()
}

function handlePageChange(page: number) {
  pagination.value.page = page
  checkedRowKeys.value = []
  loadResults()
}

// ── 开始匹配 ──────────────────────────────────────────────────────────────────
function handleMatch() {
  const paths = gpxPaths.value.filter(p => p.trim())
  if (paths.length === 0) {
    message.warning('请输入至少一个 GPX 文件路径')
    return
  }

  matching.value = true
  progressCurrent.value = 0
  progressTotal.value = 0

  startGpxMatch(props.taskId, paths).catch(() => {
    matching.value = false
    message.error('启动失败，请检查后端日志')
  })

  const ws = connectTaskWs(props.taskId, (event, data) => {
    if (event === 'gpx_start') {
      progressTotal.value = data.total
    } else if (event === 'gpx_progress') {
      progressCurrent.value = data.current
      progressTotal.value = data.total
    } else if (event === 'gpx_complete') {
      matching.value = false
      ws.close()
      await loadResults()
      await loadTrack()
      message.success(
        `匹配完成：良好 ${data.matched_good}，偏差较大 ${data.matched_warning}，无匹配 ${data.no_match}`
      )
    } else if (event === 'gpx_error') {
      matching.value = false
      ws.close()
      message.error(`匹配失败：${data.message}`)
    }
  })
}

// ── 批量写入 ──────────────────────────────────────────────────────────────────
function handleExecuteWrite() {
  const count = checkedRowKeys.value.length
  const modeLabel = writeMode.value === 'fill_only' ? '仅为无 GPS 的文件写入坐标' : '覆盖所有文件的 GPS 坐标'

  dialog.warning({
    title: '确认写入 GPS',
    content: `将对选中的 ${count} 个文件执行：${modeLabel}。此操作会修改 JPEG 文件的 EXIF，确认继续？`,
    positiveText: '确认写入',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const res = await executeGpsWrite(props.taskId, checkedRowKeys.value as number[], writeMode.value)
        const msg = `已写入 ${res.data.written} 个文件，跳过 ${res.data.skipped} 个${res.data.errors.length > 0 ? `，${res.data.errors.length} 个失败` : ''}`
        message.success(msg)
        checkedRowKeys.value = []
        loadResults()
      } catch {
        message.error('写入失败')
      }
    },
  })
}

// ── 清空匹配 ──────────────────────────────────────────────────────────────────
function handleClear() {
  dialog.warning({
    title: '确认清空',
    content: '将清空所有 GPX 匹配记录并重置文件 GPS 字段（不会修改物理文件），确认继续？',
    positiveText: '确认清空',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await clearGpxMatches(props.taskId)
        hasResult.value = false
        matchList.value = []
        stats.value = { total: 0, good: 0, warning: 0, no_match: 0 }
        checkedRowKeys.value = []
        message.success('已清空匹配记录')
      } catch {
        message.error('清空失败')
      }
    },
  })
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
onMounted(async () => {
  await taskStore.fetchTask(props.taskId)
  await loadResults()
  if (hasResult.value) await loadTrack()
})
</script>
