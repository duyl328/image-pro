import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
    },
    {
      path: '/task/:taskId',
      redirect: (to) => `/task/${to.params.taskId}/scan`,
    },
    {
      path: '/task/:taskId/scan',
      name: 'scan',
      component: () => import('../views/ScanView.vue'),
      props: (route) => ({ taskId: Number(route.params.taskId) }),
    },
    {
      path: '/task/:taskId/duplicates',
      name: 'duplicates',
      component: () => import('../views/DuplicateView.vue'),
      props: (route) => ({ taskId: Number(route.params.taskId) }),
    },
    {
      path: '/task/:taskId/ai',
      name: 'ai',
      component: () => import('../views/AiView.vue'),
      props: (route) => ({ taskId: Number(route.params.taskId) }),
    },
    {
      path: '/task/:taskId/exif',
      name: 'exif',
      component: () => import('../views/ExifView.vue'),
      props: (route) => ({ taskId: Number(route.params.taskId) }),
    },
    {
      path: '/task/:taskId/gpx',
      name: 'gpx',
      component: () => import('../views/GpxView.vue'),
      props: (route) => ({ taskId: Number(route.params.taskId) }),
    },
  ],
})

export default router
