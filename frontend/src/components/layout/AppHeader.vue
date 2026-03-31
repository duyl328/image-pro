<template>
  <div style="display: flex; align-items: center; gap: 16px; width: 100%">
    <n-button text @click="goHome" style="font-size: 18px; font-weight: bold">
      Image Pro
    </n-button>

    <template v-if="taskStore.currentTask">
      <n-divider vertical />
      <n-text depth="3" style="font-size: 14px">
        {{ taskStore.currentTask.name || taskStore.currentTask.folder_path }}
      </n-text>
      <n-tag :type="statusType" size="small">{{ taskStore.currentTask.status }}</n-tag>
    </template>

    <div style="flex: 1" />

    <n-button v-if="taskStore.currentTask" text @click="goHome">
      返回任务列表
    </n-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../../stores/task'

const router = useRouter()
const taskStore = useTaskStore()

const statusType = computed(() => {
  switch (taskStore.currentTask?.status) {
    case 'scanning': return 'warning'
    case 'ready': return 'success'
    case 'completed': return 'info'
    default: return 'default'
  }
})

function goHome() {
  taskStore.setCurrentTask(null)
  router.push('/')
}
</script>
