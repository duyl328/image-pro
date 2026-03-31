<template>
  <n-menu
    :value="activeKey"
    :options="menuOptions"
    :collapsed="appStore.sidebarCollapsed"
    @update:value="handleSelect"
  />
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import {
  ScanOutline,
  CopyOutline,
  TimeOutline,
  LocationOutline,
  SparklesOutline,
  ListOutline,
} from '@vicons/ionicons5'
import { useTaskStore } from '../../stores/task'
import { useAppStore } from '../../stores/app'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const appStore = useAppStore()

const taskId = computed(() => taskStore.currentTask?.id)

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = computed(() => [
  { label: '扫描概览', key: 'scan', icon: renderIcon(ScanOutline) },
  { label: '查重检测', key: 'duplicates', icon: renderIcon(CopyOutline) },
  { label: '时间/EXIF', key: 'exif', icon: renderIcon(TimeOutline), disabled: true },
  { label: 'GPS 匹配', key: 'gpx', icon: renderIcon(LocationOutline), disabled: true },
  { label: 'AI 筛图', key: 'ai', icon: renderIcon(SparklesOutline), disabled: true },
  { label: '操作日志', key: 'logs', icon: renderIcon(ListOutline), disabled: true },
])

const activeKey = computed(() => {
  const name = route.name as string
  return name || 'scan'
})

function handleSelect(key: string) {
  if (taskId.value) {
    router.push(`/task/${taskId.value}/${key}`)
  }
}
</script>
