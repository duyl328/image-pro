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
  FolderOpenOutline,
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
const labels = {
  scan: '\u626b\u63cf\u6982\u89c8',
  duplicates: '\u67e5\u91cd\u68c0\u6d4b',
  exif: '\u65f6\u95f4/EXIF',
  gpx: 'GPS \u5339\u914d',
  emptyFolders: '\u7a7a\u6587\u4ef6\u5939',
  ai: 'AI \u7b5b\u56fe',
  logs: '\u64cd\u4f5c\u65e5\u5fd7',
}

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = computed(() => [
  { label: labels.scan, key: 'scan', icon: renderIcon(ScanOutline) },
  { label: labels.duplicates, key: 'duplicates', icon: renderIcon(CopyOutline) },
  { label: labels.exif, key: 'exif', icon: renderIcon(TimeOutline) },
  { label: labels.gpx, key: 'gpx', icon: renderIcon(LocationOutline) },
  { label: labels.emptyFolders, key: 'empty-folders', icon: renderIcon(FolderOpenOutline) },
  { label: labels.ai, key: 'ai', icon: renderIcon(SparklesOutline) },
  { label: labels.logs, key: 'logs', icon: renderIcon(ListOutline), disabled: true },
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
