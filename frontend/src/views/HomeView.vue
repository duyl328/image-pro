<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px">
      <n-h2 style="margin: 0">任务列表</n-h2>
      <n-space>
        <n-button v-if="selectedIds.length" type="error" @click="confirmBatchDelete">
          批量删除 ({{ selectedIds.length }})
        </n-button>
        <n-button type="primary" @click="showCreate = true">新建任务</n-button>
      </n-space>
    </div>

    <n-spin :show="loading">
      <n-grid :x-gap="16" :y-gap="16" :cols="3" v-if="tasks.length">
        <n-gi v-for="task in tasks" :key="task.id">
          <n-card hoverable @click="enterTask(task)" style="cursor: pointer">
            <template #header>
              <n-space align="center" :size="8" :wrap="false">
                <n-checkbox
                  :checked="selectedIds.includes(task.id)"
                  @update:checked="(v: boolean) => toggleSelect(task.id, v)"
                  @click.stop
                />
                <n-ellipsis :line-clamp="1">{{ task.name || task.folder_path }}</n-ellipsis>
              </n-space>
            </template>
            <template #header-extra>
              <n-tag :type="getStatusType(task.status)" size="small">{{ task.status }}</n-tag>
            </template>
            <n-space vertical :size="8">
              <n-text depth="3" style="font-size: 12px">
                <n-ellipsis :line-clamp="1">{{ task.folder_path }}</n-ellipsis>
              </n-text>
              <n-space :size="16">
                <n-statistic label="文件" :value="task.file_count" tabular-nums />
                <n-statistic label="图片" :value="task.image_count" tabular-nums />
                <n-statistic label="视频" :value="task.video_count" tabular-nums />
              </n-space>
            </n-space>
            <template #action>
              <n-space justify="end">
                <n-button text type="error" @click.stop="confirmDelete(task)">删除</n-button>
              </n-space>
            </template>
          </n-card>
        </n-gi>
      </n-grid>
      <n-empty v-else description="暂无任务，点击右上角创建" />
    </n-spin>

    <!-- Create task modal -->
    <n-modal v-model:show="showCreate" preset="dialog" title="新建任务" positive-text="创建" negative-text="取消"
      @positive-click="handleCreate" :loading="creating">
      <n-form>
      <n-form-item label="文件夹路径">
          <n-input-group>
            <n-input v-model:value="newFolderPath" placeholder="输入文件夹绝对路径，如 D:\Photos\2024" />
            <n-button @click="handlePickFolder" :loading="picking">浏览</n-button>
          </n-input-group>
        </n-form-item>
        <n-form-item label="任务名称（可选）">
          <n-input v-model:value="newTaskName" placeholder="默认使用文件夹名" />
        </n-form-item>
      </n-form>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog } from 'naive-ui'
import { useTaskStore, type TaskInfo } from '../stores/task'
import { createTask, deleteTask as apiDeleteTask, pickFolder } from '../api'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const taskStore = useTaskStore()

const loading = ref(false)
const tasks = ref<TaskInfo[]>([])
const showCreate = ref(false)
const creating = ref(false)
const picking = ref(false)
const newFolderPath = ref('')
const newTaskName = ref('')
const selectedIds = ref<number[]>([])

onMounted(async () => {
  loading.value = true
  await taskStore.fetchTasks()
  tasks.value = taskStore.tasks
  loading.value = false
})

function getStatusType(status: string) {
  switch (status) {
    case 'scanning': return 'warning'
    case 'ready': return 'success'
    case 'completed': return 'info'
    default: return 'default'
  }
}

function enterTask(task: TaskInfo) {
  taskStore.setCurrentTask(task)
  router.push(`/task/${task.id}/scan`)
}

async function handlePickFolder() {
  picking.value = true
  try {
    const res = await pickFolder()
    newFolderPath.value = res.data.folder_path
  } catch { /* user cancelled */ }
  picking.value = false
}

async function handleCreate() {
  if (!newFolderPath.value.trim()) {
    message.error('请输入文件夹路径')
    return false
  }
  creating.value = true
  try {
    const res = await createTask(newFolderPath.value.trim(), newTaskName.value.trim() || undefined)
    message.success('任务创建成功')
    showCreate.value = false
    newFolderPath.value = ''
    newTaskName.value = ''
    await taskStore.fetchTasks()
    tasks.value = taskStore.tasks
    enterTask(res.data)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

function toggleSelect(id: number, checked: boolean) {
  if (checked) {
    selectedIds.value.push(id)
  } else {
    selectedIds.value = selectedIds.value.filter(x => x !== id)
  }
}

function confirmBatchDelete() {
  const count = selectedIds.value.length
  dialog.warning({
    title: '确认批量删除',
    content: `确定要删除选中的 ${count} 个任务吗？（不会删除原始文件和训练数据）`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await Promise.all(selectedIds.value.map(id => apiDeleteTask(id)))
        message.success(`已删除 ${count} 个任务`)
        selectedIds.value = []
        await taskStore.fetchTasks()
        tasks.value = taskStore.tasks
      } catch {
        message.error('部分任务删除失败')
      }
    },
  })
}

function confirmDelete(task: TaskInfo) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除任务「${task.name || task.folder_path}」吗？（不会删除原始文件）`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await apiDeleteTask(task.id)
        message.success('已删除')
        await taskStore.fetchTasks()
        tasks.value = taskStore.tasks
      } catch {
        message.error('删除失败')
      }
    },
  })
}
</script>
