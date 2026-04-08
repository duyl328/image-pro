<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">{{ text.title }}</n-h2>
      <n-space>
        <n-button @click="loadEmptyFolderData" :loading="loading">{{ text.refresh }}</n-button>
        <n-button
          type="error"
          @click="confirmDeleteAll"
          :loading="deleting"
          :disabled="!emptyFolders.length"
        >
          {{ text.deleteAll }} ({{ emptyFolders.length }})
        </n-button>
      </n-space>
    </div>

    <n-alert type="info" style="margin-bottom: 16px">
      {{ text.tip }}
    </n-alert>

    <n-card size="small" style="margin-bottom: 16px">
      <n-space justify="space-between" align="center" :wrap="false">
        <n-statistic :label="text.statLabel" :value="emptyFolders.length" />
        <n-text depth="3" style="text-align: right">
          {{ taskStore.currentTask?.folder_path || rootPath }}
        </n-text>
      </n-space>
    </n-card>

    <n-spin :show="loading || deleting">
      <n-card :title="text.listTitle">
        <n-empty v-if="!emptyFolders.length" :description="text.emptyState" />
        <n-scrollbar v-else style="max-height: calc(100vh - 280px)">
          <div
            v-for="item in emptyFolders"
            :key="item.absolute_path"
            style="padding: 12px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06)"
          >
            <div style="display: flex; justify-content: space-between; gap: 16px; align-items: flex-start">
              <div style="min-width: 0">
                <n-text strong>{{ item.relative_path }}</n-text>
                <div style="margin-top: 4px">
                  <n-text depth="3" style="font-size: 12px">{{ item.absolute_path }}</n-text>
                </div>
              </div>
              <n-tag size="small" type="default">{{ text.depthLabel }} {{ item.depth }}</n-tag>
            </div>
          </div>
        </n-scrollbar>
      </n-card>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { deleteEmptyFolders, listEmptyFolders } from '../api'
import { useTaskStore } from '../stores/task'

interface EmptyFolderItem {
  relative_path: string
  absolute_path: string
  depth: number
}

const props = defineProps<{ taskId: number }>()
const message = useMessage()
const dialog = useDialog()
const taskStore = useTaskStore()
const text = {
  title: '\u7a7a\u6587\u4ef6\u5939',
  refresh: '\u5237\u65b0',
  deleteAll: '\u4e00\u952e\u5220\u9664',
  tip: '\u5c06\u9012\u5f52\u6e05\u7406\u5f53\u524d\u4efb\u52a1\u76ee\u5f55\u4e0b\u7684\u7a7a\u6587\u4ef6\u5939\uff0c\u4e0d\u4f1a\u5220\u9664\u4efb\u52a1\u6839\u76ee\u5f55\uff0c\u4e5f\u4e0d\u4f1a\u5220\u9664\u5305\u542b\u6587\u4ef6\u7684\u76ee\u5f55\u3002',
  statLabel: '\u53ef\u6e05\u7406\u7a7a\u6587\u4ef6\u5939',
  listTitle: '\u7a7a\u6587\u4ef6\u5939\u5217\u8868',
  emptyState: '\u672a\u53d1\u73b0\u53ef\u6e05\u7406\u7684\u7a7a\u6587\u4ef6\u5939',
  depthLabel: '\u5c42\u7ea7',
  loadError: '\u52a0\u8f7d\u7a7a\u6587\u4ef6\u5939\u5931\u8d25',
  confirmTitle: '\u786e\u8ba4\u5220\u9664\u7a7a\u6587\u4ef6\u5939',
  confirmContent: (count: number) => `\u5c06\u5220\u9664 ${count} \u4e2a\u7a7a\u6587\u4ef6\u5939\u3002\u8be5\u64cd\u4f5c\u4e0d\u4f1a\u5220\u9664\u4efb\u52a1\u6839\u76ee\u5f55\uff0c\u4e5f\u4e0d\u4f1a\u5220\u9664\u5305\u542b\u6587\u4ef6\u7684\u76ee\u5f55\u3002`,
  confirmDelete: '\u5220\u9664',
  confirmCancel: '\u53d6\u6d88',
  partialSuccess: (deleted: number, failed: number) => `\u5df2\u5220\u9664 ${deleted} \u4e2a\u7a7a\u6587\u4ef6\u5939\uff0c${failed} \u4e2a\u5220\u9664\u5931\u8d25`,
  success: (deleted: number) => `\u5df2\u5220\u9664 ${deleted} \u4e2a\u7a7a\u6587\u4ef6\u5939`,
  deleteError: '\u5220\u9664\u7a7a\u6587\u4ef6\u5939\u5931\u8d25',
}

const loading = ref(false)
const deleting = ref(false)
const rootPath = ref('')
const emptyFolders = ref<EmptyFolderItem[]>([])

onMounted(async () => {
  await initializeView()
})

watch(
  () => props.taskId,
  async (newTaskId, oldTaskId) => {
    if (newTaskId === oldTaskId) return
    resetViewState()
    await initializeView()
  }
)

function resetViewState() {
  loading.value = false
  deleting.value = false
  rootPath.value = ''
  emptyFolders.value = []
}

async function initializeView() {
  await taskStore.fetchTask(props.taskId)
  await loadEmptyFolderData()
}

async function loadEmptyFolderData() {
  loading.value = true
  try {
    const res = await listEmptyFolders(props.taskId)
    rootPath.value = res.data.root_path
    emptyFolders.value = res.data.items
  } catch (e: any) {
    message.error(e.response?.data?.detail || text.loadError)
  } finally {
    loading.value = false
  }
}

function confirmDeleteAll() {
  const count = emptyFolders.value.length
  if (!count) return

  dialog.warning({
    title: text.confirmTitle,
    content: text.confirmContent(count),
    positiveText: text.confirmDelete,
    negativeText: text.confirmCancel,
    onPositiveClick: async () => {
      deleting.value = true
      try {
        const res = await deleteEmptyFolders(props.taskId)
        const failed = res.data.errors?.length || 0
        if (failed > 0) {
          message.warning(text.partialSuccess(res.data.deleted, failed))
        } else {
          message.success(text.success(res.data.deleted))
        }
        await loadEmptyFolderData()
      } catch (e: any) {
        message.error(e.response?.data?.detail || text.deleteError)
      } finally {
        deleting.value = false
      }
    },
  })
}
</script>
