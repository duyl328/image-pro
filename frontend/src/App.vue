<template>
  <n-config-provider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
      <n-layout has-sider style="height: 100vh">
        <!-- Sidebar: only show when inside a task -->
        <n-layout-sider
          v-if="taskStore.currentTask"
          bordered
          :width="200"
          :collapsed-width="64"
          :collapsed="appStore.sidebarCollapsed"
          show-trigger
          collapse-mode="width"
          @collapse="appStore.sidebarCollapsed = true"
          @expand="appStore.sidebarCollapsed = false"
        >
          <AppSidebar />
        </n-layout-sider>

        <n-layout>
          <n-layout-header bordered style="height: 56px; padding: 0 24px; display: flex; align-items: center">
            <AppHeader />
          </n-layout-header>
          <n-layout-content content-style="padding: 24px;" style="height: calc(100vh - 56px); overflow: auto">
            <router-view />
          </n-layout-content>
        </n-layout>
      </n-layout>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { darkTheme, zhCN, dateZhCN } from 'naive-ui'
import { useTaskStore } from './stores/task'
import { useAppStore } from './stores/app'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppHeader from './components/layout/AppHeader.vue'

const taskStore = useTaskStore()
const appStore = useAppStore()
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
</style>
