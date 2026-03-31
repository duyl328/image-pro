import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getTask, listTasks } from '../api'

export interface TaskInfo {
  id: number
  folder_path: string
  name: string | null
  status: string
  file_count: number
  image_count: number
  video_count: number
  other_count: number
  created_at: string | null
  updated_at: string | null
}

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<TaskInfo[]>([])
  const currentTask = ref<TaskInfo | null>(null)

  async function fetchTasks() {
    const res = await listTasks()
    tasks.value = res.data
  }

  async function fetchTask(taskId: number) {
    const res = await getTask(taskId)
    currentTask.value = res.data
    return res.data
  }

  function setCurrentTask(task: TaskInfo | null) {
    currentTask.value = task
  }

  return { tasks, currentTask, fetchTasks, fetchTask, setCurrentTask }
})
