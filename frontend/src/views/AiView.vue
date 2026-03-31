<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">AI 筛图</n-h2>
      <n-space>
        <n-button v-if="showTrainButton" type="primary" @click="handleTrain" :loading="training">
          {{ training ? '训练中...' : '训练模型' }}
        </n-button>
        <n-button v-if="showPredictButton" @click="handlePredict" :loading="predicting">
          {{ predicting ? '推理中...' : '生成建议' }}
        </n-button>
        <n-button v-if="hasResults" @click="showModelDialog = true">模型管理</n-button>
      </n-space>
    </div>

    <!-- Extract progress -->
    <n-card v-if="extracting" title="特征提取中" style="margin-bottom: 16px">
      <n-progress type="line" :percentage="extractProgress" :processing="true" indicator-placement="inside" />
      <n-text depth="3" style="margin-top: 8px; display: block">
        {{ extractCurrent }} / {{ extractTotal }} 图片
      </n-text>
    </n-card>

    <!-- Cold start -->
    <n-card v-if="needsColdStart && !extracting" title="⚠ AI 模型尚未就绪" style="margin-bottom: 16px">
      <n-space vertical>
        <n-text>需要标注至少 {{ labelStats.min_required }} 张图片才能开始训练。</n-text>
        <n-text>当前已标注：{{ labelStats.total }} / {{ labelStats.min_required }}</n-text>
        <n-progress
          type="line"
          :percentage="coldStartProgress"
          :status="labelStats.ready ? 'success' : 'default'"
        />
        <n-text depth="3">请在下方浏览图片并标记"保留"或"删除"。</n-text>
      </n-space>
    </n-card>

    <!-- Training progress -->
    <n-card v-if="training" title="🔄 正在训练模型..." style="margin-bottom: 16px">
      <n-space vertical>
        <n-text>训练进度：Epoch {{ trainStatus.epoch || 0 }}/{{ trainStatus.max_epochs || 50 }}</n-text>
        <n-progress
          type="line"
          :percentage="trainProgress"
          :processing="true"
        />
        <n-text depth="3">当前验证准确率：{{ (trainStatus.val_accuracy * 100).toFixed(1) }}%</n-text>
        <n-text depth="3">最佳验证准确率：{{ (trainStatus.best_accuracy * 100).toFixed(1) }}%</n-text>
      </n-space>
    </n-card>

    <!-- Results -->
    <template v-if="hasResults && !extracting && !training">
      <!-- Stats -->
      <n-grid :x-gap="16" :y-gap="16" :cols="4" style="margin-bottom: 24px">
        <n-gi>
          <n-card>
            <n-statistic label="全部图片" :value="resultStats.total" tabular-nums />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card>
            <n-statistic label="建议保留" :value="resultStats.keep" tabular-nums>
              <template #prefix><n-text type="success">🟢</n-text></template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card>
            <n-statistic label="建议删除" :value="resultStats.delete" tabular-nums>
              <template #prefix><n-text type="error">🔴</n-text></template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card>
            <n-statistic label="已修正" :value="resultStats.corrected" tabular-nums />
          </n-card>
        </n-gi>
      </n-grid>

      <!-- Filters and actions -->
      <n-card style="margin-bottom: 16px">
        <n-space>
          <n-select
            v-model:value="filters.prediction"
            :options="predictionOptions"
            placeholder="AI 建议"
            style="width: 150px"
            size="small"
          />
          <n-select
            v-model:value="filters.confidence"
            :options="confidenceOptions"
            placeholder="置信度"
            style="width: 150px"
            size="small"
          />
          <n-select
            v-model:value="filters.labelStatus"
            :options="labelStatusOptions"
            placeholder="标记状态"
            style="width: 150px"
            size="small"
          />
          <n-button @click="loadPredictions" size="small">应用筛选</n-button>
          <n-divider vertical />
          <n-button
            type="error"
            @click="handleExecuteDelete"
            :disabled="resultStats.delete === 0"
            size="small"
          >
            执行删除 ({{ resultStats.delete }})
          </n-button>
        </n-space>
      </n-card>

      <!-- Main content: Grid + Preview -->
      <n-grid :x-gap="16" :cols="3" style="margin-bottom: 16px">
        <n-gi :span="1">
          <n-card title="图片列表" size="small">
            <n-virtual-list
              :item-size="138"
              :items="predictionRows"
              style="max-height: 800px"
            >
              <template #default="{ item: row }">
                <div style="display: flex; gap: 8px; margin-bottom: 8px">
                  <div
                    v-for="(item, colIdx) in row"
                    :key="item.file_id"
                    :style="{
                      flex: 1,
                      cursor: 'pointer',
                      border: `3px solid ${getBorderColor(item)}`,
                      borderRadius: '4px',
                      overflow: 'hidden',
                    }"
                    @click="selectItem(predictions.indexOf(item))"
                  >
                    <img
                      :src="getThumbnailUrl(item.file_id)"
                      style="width: 100%; height: 120px; object-fit: cover; display: block"
                    />
                  </div>
                </div>
              </template>
            </n-virtual-list>
          </n-card>
        </n-gi>
        <n-gi :span="2">
          <n-card title="预览" size="small">
            <div v-if="currentPreview" style="text-align: center">
              <img
                :src="currentPreview.thumbnail"
                style="max-width: 100%; max-height: 850px; object-fit: contain; cursor: pointer"
                @click="showFullImage"
              />
              <n-divider />
              <n-descriptions :column="2" size="small" label-placement="left">
                <n-descriptions-item label="文件名" :span="2">{{ currentPreview.file_name }}</n-descriptions-item>
                <n-descriptions-item label="AI 建议">
                  <n-tag :type="currentPreview.ai_prediction === 'keep' ? 'success' : 'error'" size="small">
                    {{ currentPreview.ai_prediction === 'keep' ? '保留' : '删除' }}
                  </n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="置信度">
                  {{ (currentPreview.ai_confidence * 100).toFixed(1) }}%
                </n-descriptions-item>
                <n-descriptions-item label="用户标记" :span="2">
                  <n-tag v-if="currentPreview.user_label" :type="currentPreview.user_label === 'keep' ? 'success' : 'error'" size="small">
                    {{ currentPreview.user_label === 'keep' ? '保留' : '删除' }}
                  </n-tag>
                  <n-text v-else depth="3">未标记</n-text>
                </n-descriptions-item>
              </n-descriptions>
              <n-divider />
              <n-space justify="center">
                <n-button type="success" @click="handleLabelAndNext(currentPreview.file_id, 'keep')">
                  保留 (→ / K)
                </n-button>
                <n-button type="error" @click="handleLabelAndNext(currentPreview.file_id, 'delete')">
                  删除 (Del / D)
                </n-button>
              </n-space>
            </div>
            <n-empty v-else description="点击左侧缩略图查看预览" />
          </n-card>
        </n-gi>
      </n-grid>
    </template>

    <n-empty v-if="!hasResults && !extracting && !needsColdStart && !training" description="点击「生成建议」开始 AI 筛图" />

    <!-- Model management dialog -->
    <n-modal v-model:show="showModelDialog" preset="card" title="模型管理" style="width: 700px">
      <n-data-table :columns="modelColumns" :data="models" size="small" :max-height="400" />
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h } from 'vue'
import { useMessage, useDialog, NTag, NButton } from 'naive-ui'
import { useTaskStore } from '../stores/task'
import {
  startExtract, getExtractStatus, getLabelStats, startTraining, getTrainStatus,
  startPredict, getPredictions, listModels, rollbackModel, executeAiDelete,
  batchLabel, getThumbnailUrl, connectTaskWs
} from '../api'

const props = defineProps<{ taskId: number }>()
const message = useMessage()
const dialog = useDialog()
const taskStore = useTaskStore()

// State
const extracting = ref(false)
const extractTotal = ref(0)
const extractCurrent = ref(0)
const training = ref(false)
const predicting = ref(false)
const loading = ref(false)

const labelStats = ref({ total: 0, keep: 0, delete: 0, min_required: 200, ready: false })
const trainStatus = ref<any>({ status: 'idle', epoch: 0, max_epochs: 50, val_accuracy: 0, best_accuracy: 0 })
const predictions = ref<any[]>([])
const selectedIds = ref<number[]>([])
const currentPreview = ref<any>(null)
const currentIndex = ref(0)
const models = ref<any[]>([])
const showModelDialog = ref(false)

const pagination = ref({ page: 1, pageSize: 50, itemCount: 0 })
const filters = ref({
  prediction: null as string | null,
  confidence: null as string | null,
  labelStatus: null as string | null,
})

const resultStats = ref({ total: 0, keep: 0, delete: 0, corrected: 0 })

let ws: WebSocket | null = null

// Computed
const extractProgress = computed(() =>
  extractTotal.value > 0 ? Math.round((extractCurrent.value / extractTotal.value) * 100) : 0
)

const coldStartProgress = computed(() =>
  labelStats.value.min_required > 0
    ? Math.min(100, Math.round((labelStats.value.total / labelStats.value.min_required) * 100))
    : 0
)

const trainProgress = computed(() =>
  trainStatus.value.max_epochs > 0
    ? Math.round((trainStatus.value.epoch / trainStatus.value.max_epochs) * 100)
    : 0
)

const needsColdStart = computed(() => !labelStats.value.ready)
const showTrainButton = computed(() => labelStats.value.ready && !training.value)
const showPredictButton = computed(() => labelStats.value.ready && !predicting.value)
const hasResults = computed(() => predictions.value.length > 0)

// Group predictions into rows of 3
const predictionRows = computed(() => {
  const rows = []
  for (let i = 0; i < predictions.value.length; i += 3) {
    rows.push(predictions.value.slice(i, i + 3))
  }
  return rows
})


// Options
const predictionOptions = [
  { label: '全部', value: null },
  { label: '建议保留', value: 'keep' },
  { label: '建议删除', value: 'delete' },
]

const confidenceOptions = [
  { label: '全部', value: null },
  { label: '高 (>80%)', value: 'high' },
  { label: '中 (30-80%)', value: 'medium' },
  { label: '低 (<30%)', value: 'low' },
]

const labelStatusOptions = [
  { label: '全部', value: null },
  { label: '已标记', value: 'labeled' },
  { label: '未标记', value: 'unlabeled' },
  { label: '已修正', value: 'corrected' },
]

const modelColumns = [
  { title: '版本', key: 'version', width: 80 },
  { title: '样本数', key: 'training_samples', width: 100 },
  { title: '准确率', key: 'val_accuracy', width: 100, render: (row: any) => `${(row.val_accuracy * 100).toFixed(1)}%` },
  { title: '训练时间', key: 'training_time_sec', width: 100, render: (row: any) => `${row.training_time_sec}s` },
  {
    title: '状态',
    key: 'is_current',
    width: 80,
    render: (row: any) => row.is_current ? h(NTag, { type: 'success', size: 'small' }, () => '当前') : '-'
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (row: any) => !row.is_current
      ? h(NButton, { size: 'tiny', onClick: () => handleRollback(row.version) }, () => '回滚')
      : null
  },
]

// Lifecycle
onMounted(async () => {
  await taskStore.fetchTask(props.taskId)
  await checkExtractStatus()
  await loadLabelStats()
  await loadPredictions()
  connectWebSocket()
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  ws?.close()
  window.removeEventListener('keydown', handleKeydown)
})

// Keyboard shortcuts
function handleKeydown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

  if (e.key === 'Delete' || e.key === 'd' || e.key === 'D') {
    e.preventDefault()
    if (currentPreview.value) {
      handleLabelAndNext(currentPreview.value.file_id, 'delete')
    }
  } else if (e.key === 'ArrowRight' || e.key === 'k' || e.key === 'K') {
    e.preventDefault()
    if (currentPreview.value) {
      handleLabelAndNext(currentPreview.value.file_id, 'keep')
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    goToNext()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    goToPrev()
  }
}

function goToNext() {
  if (currentIndex.value < predictions.value.length - 1) {
    currentIndex.value++
    selectCurrent()
  }
}

function goToPrev() {
  if (currentIndex.value > 0) {
    currentIndex.value--
    selectCurrent()
  }
}

function selectCurrent() {
  const item = predictions.value[currentIndex.value]
  if (item) {
    currentPreview.value = { ...item, thumbnail: getThumbnailUrl(item.file_id) }
  }
}

function selectItem(idx: number) {
  currentIndex.value = idx
  selectCurrent()
}

function getBorderColor(item: any) {
  const isCurrent = currentPreview.value?.file_id === item.file_id
  if (isCurrent) return '#2080f0'
  if (item.user_label === 'keep') return '#18a058'
  if (item.user_label === 'delete') return '#d03050'
  return '#e0e0e0'
}


async function handleLabelAndNext(fileId: number, label: string) {
  try {
    await batchLabel(props.taskId, [fileId], label)
    await loadLabelStats()
    // Update local state
    const idx = predictions.value.findIndex(p => p.file_id === fileId)
    if (idx >= 0) {
      predictions.value[idx].user_label = label
    }
    goToNext()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '标记失败')
  }
}


// Methods
async function checkExtractStatus() {
  try {
    const res = await getExtractStatus(props.taskId)
    if (res.data.status === 'running') {
      extracting.value = true
      extractCurrent.value = res.data.progress
      extractTotal.value = res.data.total
    } else if (res.data.status === 'idle' || res.data.status === 'completed') {
      // Always trigger extraction when entering AI page
      await handleExtract()
    }
  } catch (e) {
    console.error('Check extract status failed:', e)
    // Try to start extraction anyway
    await handleExtract()
  }
}

async function handleExtract() {
  console.log('[AI] Starting feature extraction...')
  extracting.value = true
  try {
    const res = await startExtract(props.taskId)
    console.log('[AI] Extract started:', res.data)
    extractTotal.value = res.data.total
    extractCurrent.value = 0
    if (res.data.total === 0) {
      console.log('[AI] No images to extract')
      extracting.value = false
    }
  } catch (e: any) {
    console.error('[AI] Extract failed:', e)
    message.error(e.response?.data?.detail || '启动特征提取失败')
    extracting.value = false
  }
}

async function loadLabelStats() {
  try {
    const res = await getLabelStats()
    labelStats.value = res.data
  } catch { /* ignore */ }
}

async function handleTrain() {
  training.value = true
  try {
    await startTraining()
    pollTrainStatus()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '启动训练失败')
    training.value = false
  }
}

async function pollTrainStatus() {
  const interval = setInterval(async () => {
    try {
      const res = await getTrainStatus()
      trainStatus.value = res.data
      if (res.data.status === 'completed') {
        clearInterval(interval)
        training.value = false
        message.success(`训练完成！准确率: ${(res.data.accuracy * 100).toFixed(1)}%`)
        await loadLabelStats()
        await handlePredict()
      } else if (res.data.status === 'failed') {
        clearInterval(interval)
        training.value = false
        message.error('训练失败: ' + res.data.error)
      }
    } catch {
      clearInterval(interval)
      training.value = false
    }
  }, 1000)
}

async function handlePredict() {
  predicting.value = true
  try {
    const res = await startPredict(props.taskId)
    message.success(`推理完成: 保留 ${res.data.keep}, 删除 ${res.data.delete}`)
    await loadPredictions()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '推理失败')
  }
  predicting.value = false
}

async function loadPredictions() {
  loading.value = true
  try {
    const allItems: any[] = []
    let page = 1
    const pageSize = 500

    while (true) {
      const params: any = {
        page,
        page_size: pageSize,
        sort_by: 'confidence',
        sort_order: 'asc',
      }
      if (filters.value.prediction) params.prediction = filters.value.prediction
      if (filters.value.confidence === 'high') {
        params.confidence_min = 0.8
      } else if (filters.value.confidence === 'medium') {
        params.confidence_min = 0.3
        params.confidence_max = 0.8
      } else if (filters.value.confidence === 'low') {
        params.confidence_max = 0.3
      }
      if (filters.value.labelStatus) params.label_status = filters.value.labelStatus

      const res = await getPredictions(props.taskId, params)
      allItems.push(...res.data.items)

      if (allItems.length >= res.data.total || res.data.items.length < pageSize) {
        break
      }
      page++
    }

    predictions.value = allItems
    pagination.value.itemCount = allItems.length

    // Update stats
    resultStats.value.total = allItems.length
    resultStats.value.keep = allItems.filter((x: any) => x.ai_prediction === 'keep').length
    resultStats.value.delete = allItems.filter((x: any) => x.ai_prediction === 'delete').length
    resultStats.value.corrected = allItems.filter((x: any) => x.is_corrected).length

    // Auto-select first item
    if (predictions.value.length > 0 && !currentPreview.value) {
      currentIndex.value = 0
      selectCurrent()
    }
  } catch { /* ignore */ }
  loading.value = false
}

async function handleSingleLabel(fileId: number, label: string) {
  try {
    await batchLabel(props.taskId, [fileId], label)
    message.success('标记成功')
    await loadLabelStats()
    await loadPredictions()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '标记失败')
  }
}

async function handleExecuteDelete() {
  dialog.warning({
    title: '确认删除',
    content: `即将删除 ${resultStats.value.delete} 个文件，移动到系统回收站。确认继续？`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const res = await executeAiDelete(props.taskId)
        message.success(`已删除 ${res.data.deleted} 个文件，释放 ${(res.data.freed_bytes / 1024 / 1024).toFixed(1)} MB`)
        await loadPredictions()
      } catch (e: any) {
        message.error(e.response?.data?.detail || '删除失败')
      }
    }
  })
}

async function handleRollback(version: number) {
  try {
    await rollbackModel(version)
    message.success(`已回滚到版本 ${version}`)
    await loadModels()
    await handlePredict()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '回滚失败')
  }
}

async function loadModels() {
  try {
    const res = await listModels()
    models.value = res.data
  } catch { /* ignore */ }
}

function showFullImage() {
  if (currentPreview.value) {
    window.open(getThumbnailUrl(currentPreview.value.file_id).replace('/thumbnail', '/original'))
  }
}

function connectWebSocket() {
  ws = connectTaskWs(props.taskId, (event, data) => {
    if (event === 'extract_progress') {
      extractCurrent.value = data.progress
      extractTotal.value = data.total
    } else if (event === 'extract_completed') {
      extracting.value = false
      message.success('特征提取完成')
      loadLabelStats()
    } else if (event === 'extract_failed') {
      extracting.value = false
      message.error('特征提取失败: ' + data.error)
    }
  })
}
</script>








