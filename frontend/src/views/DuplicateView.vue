<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">重复与相似检测</n-h2>
      <n-space>
        <n-select
          v-model:value="similarityLevel"
          :options="similarityOptions"
          style="width: 120px"
          size="small"
        />
        <n-button type="primary" :loading="detecting" @click="handleDetect" :disabled="detecting">
          {{ detecting ? '检测中...' : '开始检测' }}
        </n-button>
        <n-button
          v-if="hasResults"
          type="error"
          :disabled="!hasMarkedDeletions"
          @click="handleExecute"
        >
          执行删除 ({{ deletionCount }})
        </n-button>
      </n-space>
    </div>

    <!-- Progress -->
    <n-card v-if="detecting" title="检测进度" style="margin-bottom: 16px">
      <n-space vertical :size="8">
        <n-text>{{ progressText }}</n-text>
        <n-progress type="line" :percentage="50" :processing="true" indicator-placement="inside" />
      </n-space>
    </n-card>

    <!-- Results summary -->
    <n-grid v-if="hasResults && !detecting" :x-gap="16" :y-gap="16" :cols="4" style="margin-bottom: 24px">
      <n-gi>
        <n-card>
          <n-statistic label="完全重复组" :value="exactGroupCount" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="相似组" :value="similarGroupCount" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="涉及文件" :value="totalFileCount" tabular-nums />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card>
          <n-statistic label="可释放空间" :value="savableSpaceMB" tabular-nums>
            <template #suffix>MB</template>
          </n-statistic>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- Filter tabs -->
    <n-tabs v-if="hasResults && !detecting" v-model:value="groupTypeFilter" type="segment" style="margin-bottom: 16px">
      <n-tab-pane name="all" tab="全部" />
      <n-tab-pane name="exact" tab="完全重复" />
      <n-tab-pane name="similar" tab="相似" />
    </n-tabs>

    <!-- Group cards -->
    <n-space v-if="hasResults && !detecting" vertical :size="16">
      <n-card v-for="group in filteredGroups" :key="group.id" size="small">
        <template #header>
          <n-space align="center">
            <n-tag :type="group.group_type === 'exact' ? 'error' : 'warning'" size="small">
              {{ group.group_type === 'exact' ? '完全重复' : '相似' }}
            </n-tag>
            <n-text>{{ group.file_count }} 个文件</n-text>
            <n-button size="tiny" @click="acceptRecommendation(group)">接受推荐</n-button>
          </n-space>
        </template>

        <div style="display: flex; gap: 12px; flex-wrap: wrap">
          <div
            v-for="member in group.members"
            :key="member.member_id"
            :class="['dup-card', memberClass(member)]"
            style="width: 200px; border: 2px solid; border-radius: 8px; padding: 8px; position: relative"
          >
            <!-- Thumbnail -->
            <div style="width: 100%; height: 140px; background: #333; border-radius: 4px; overflow: hidden; margin-bottom: 8px; display: flex; align-items: center; justify-content: center">
              <img
                v-if="member.thumbnail_path"
                :src="getThumbnailUrl(member.file_id)"
                style="max-width: 100%; max-height: 100%; object-fit: contain"
              />
              <n-text v-else depth="3">无缩略图</n-text>
            </div>

            <!-- Info -->
            <n-ellipsis :line-clamp="1" style="font-size: 12px">{{ member.file_name }}</n-ellipsis>
            <n-text depth="3" style="font-size: 11px; display: block">
              {{ formatSize(member.file_size) }} &middot; {{ member.extension }}
            </n-text>

            <!-- Badges -->
            <n-tag v-if="member.is_recommended" type="success" size="tiny"
              style="position: absolute; top: 4px; right: 4px">
              推荐保留
            </n-tag>

            <!-- Actions -->
            <n-space style="margin-top: 8px" :size="4">
              <n-button
                size="tiny"
                :type="member.user_action === 'keep' ? 'success' : 'default'"
                @click="setAction(group.id, member.member_id, 'keep')"
              >保留</n-button>
              <n-button
                size="tiny"
                :type="member.user_action === 'delete' ? 'error' : 'default'"
                @click="setAction(group.id, member.member_id, 'delete')"
              >删除</n-button>
            </n-space>
          </div>
        </div>
      </n-card>

      <n-pagination
        v-if="totalGroups > pageSize"
        v-model:page="currentPage"
        :page-count="Math.ceil(totalGroups / pageSize)"
        @update:page="loadGroups"
        style="justify-content: center"
      />
    </n-space>

    <n-empty v-if="!hasResults && !detecting" description="点击「开始检测」查找重复与相似文件" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { useTaskStore } from '../stores/task'
import {
  startDuplicateDetection, listDuplicateGroups,
  setMemberAction, executeDeletions,
  getThumbnailUrl, connectTaskWs,
} from '../api'

const props = defineProps<{ taskId: number }>()
const message = useMessage()
const dialog = useDialog()
const taskStore = useTaskStore()

const detecting = ref(false)
const progressText = ref('')
const similarityLevel = ref('standard')
const groupTypeFilter = ref('all')
const groups = ref<any[]>([])
const totalGroups = ref(0)
const currentPage = ref(1)
const pageSize = 20
const hasResults = ref(false)

let ws: WebSocket | null = null

const similarityOptions = [
  { label: '宽松', value: 'loose' },
  { label: '标准', value: 'standard' },
  { label: '严格', value: 'strict' },
]

const exactGroupCount = computed(() => groups.value.filter(g => g.group_type === 'exact').length)
const similarGroupCount = computed(() => groups.value.filter(g => g.group_type === 'similar').length)
const totalFileCount = computed(() => groups.value.reduce((sum, g) => sum + g.file_count, 0))

const savableSpaceMB = computed(() => {
  let bytes = 0
  for (const g of groups.value) {
    const members = g.members || []
    const sorted = [...members].sort((a: any, b: any) => (b.file_size || 0) - (a.file_size || 0))
    // All except the largest can be freed
    for (let i = 1; i < sorted.length; i++) {
      bytes += sorted[i].file_size || 0
    }
  }
  return Math.round(bytes / 1024 / 1024)
})

const filteredGroups = computed(() => {
  if (groupTypeFilter.value === 'all') return groups.value
  return groups.value.filter(g => g.group_type === groupTypeFilter.value)
})

const deletionCount = computed(() => {
  let count = 0
  for (const g of groups.value) {
    for (const m of g.members || []) {
      if (m.user_action === 'delete') count++
    }
  }
  return count
})

const hasMarkedDeletions = computed(() => deletionCount.value > 0)

function formatSize(bytes: number | null) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function memberClass(member: any) {
  if (member.user_action === 'keep') return 'border-green'
  if (member.user_action === 'delete') return 'border-red'
  if (member.is_recommended) return 'border-blue'
  return 'border-default'
}

onMounted(async () => {
  await taskStore.fetchTask(props.taskId)
  await loadGroups()
})

onUnmounted(() => {
  ws?.close()
})

async function loadGroups() {
  try {
    const res = await listDuplicateGroups(props.taskId, {
      page: currentPage.value,
      page_size: pageSize,
      group_type: groupTypeFilter.value === 'all' ? undefined : groupTypeFilter.value,
    })
    groups.value = res.data.items
    totalGroups.value = res.data.total
    hasResults.value = totalGroups.value > 0
  } catch { /* ignore */ }
}

async function handleDetect() {
  detecting.value = true
  progressText.value = '正在初始化...'

  ws = connectTaskWs(props.taskId, (event, data) => {
    if (event === 'dup_start') {
      progressText.value = `开始检测: ${data.total_files} 个文件, ${data.image_files} 张图片`
    } else if (event === 'dup_pipeline_a_progress') {
      progressText.value = `完全重复检测 — ${data.stage}: ${JSON.stringify(data)}`
    } else if (event === 'dup_pipeline_b_progress') {
      progressText.value = `相似检测 — ${data.stage}: ${JSON.stringify(data)}`
    } else if (event === 'dup_complete') {
      detecting.value = false
      message.success(`检测完成: ${data.exact_groups} 组完全重复, ${data.similar_groups} 组相似`)
      loadGroups()
      ws?.close()
    }
  })

  try {
    await startDuplicateDetection(props.taskId, similarityLevel.value)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '启动检测失败')
    detecting.value = false
  }
}

async function setAction(groupId: number, memberId: number, action: string) {
  try {
    await setMemberAction(props.taskId, groupId, memberId, action)
    // Update local state
    for (const g of groups.value) {
      if (g.id === groupId) {
        for (const m of g.members) {
          if (m.member_id === memberId) {
            m.user_action = action
          }
        }
      }
    }
  } catch {
    message.error('操作失败')
  }
}

function acceptRecommendation(group: any) {
  for (const m of group.members) {
    const action = m.is_recommended ? 'keep' : 'delete'
    setAction(group.id, m.member_id, action)
  }
}

function handleExecute() {
  dialog.warning({
    title: '确认执行删除',
    content: `确定要将 ${deletionCount.value} 个文件移到回收站吗？此操作可从回收站恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const res = await executeDeletions(props.taskId)
        message.success(`已删除 ${res.data.deleted} 个文件`)
        if (res.data.errors?.length) {
          message.warning(`${res.data.errors.length} 个文件删除失败`)
        }
        await loadGroups()
      } catch {
        message.error('执行删除失败')
      }
    },
  })
}
</script>

<style scoped>
.border-green { border-color: #18a058 !important; }
.border-red { border-color: #d03050 !important; opacity: 0.7; }
.border-blue { border-color: #2080f0 !important; }
.border-default { border-color: #555 !important; }
</style>
