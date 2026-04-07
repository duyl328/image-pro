<template>
  <div ref="container" style="position: relative; width: 100%; background: #1a1a2e; border-radius: 8px; overflow: hidden; user-select: none;">
    <svg
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      @mousemove="onMouseMove"
      @mouseleave="tooltip.visible = false"
      @wheel.prevent="onWheel"
      @mousedown="onMouseDown"
      @mouseup="onMouseUp"
    >
      <!-- 轨迹线 -->
      <polyline
        v-if="projectedTrack.length > 1"
        :points="projectedTrack.map(p => `${p[0]},${p[1]}`).join(' ')"
        fill="none"
        stroke="#4a9eff"
        stroke-width="1.5"
        stroke-opacity="0.6"
        stroke-linejoin="round"
        stroke-linecap="round"
      />

      <!-- 照片点 -->
      <g v-for="photo in projectedPhotos" :key="photo.file_id">
        <circle
          :cx="photo.x"
          :cy="photo.y"
          r="5"
          :fill="qualityColor[photo.match_quality] || '#aaa'"
          stroke="#fff"
          stroke-width="1"
          style="cursor: pointer"
          @mouseenter="showTooltip(photo, $event)"
        />
      </g>

      <!-- 空状态 -->
      <text v-if="!track.length && !photos.length" x="50%" y="50%" text-anchor="middle" fill="#666" font-size="14">
        暂无轨迹数据
      </text>
    </svg>

    <!-- Tooltip -->
    <div
      v-if="tooltip.visible"
      :style="{
        position: 'absolute',
        left: tooltip.x + 12 + 'px',
        top: tooltip.y - 10 + 'px',
        background: 'rgba(0,0,0,0.85)',
        color: '#fff',
        padding: '6px 10px',
        borderRadius: '4px',
        fontSize: '12px',
        pointerEvents: 'none',
        maxWidth: '240px',
        lineHeight: '1.6',
        zIndex: 10,
      }"
    >
      <div style="font-weight: 600; margin-bottom: 2px">{{ tooltip.photo?.file_name }}</div>
      <div>时间：{{ tooltip.photo?.best_time || '-' }}</div>
      <div>坐标：{{ fmtCoord(tooltip.photo?.lat, tooltip.photo?.lng) }}</div>
      <div>偏差：{{ fmtOffset(tooltip.photo?.time_offset_sec) }}</div>
      <div>
        质量：
        <span :style="{ color: qualityColor[tooltip.photo?.match_quality || ''] }">
          {{ qualityLabel[tooltip.photo?.match_quality || ''] || '-' }}
        </span>
      </div>
    </div>

    <!-- 图例 -->
    <div style="position: absolute; bottom: 8px; left: 12px; display: flex; gap: 12px; font-size: 11px; color: #aaa;">
      <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#4a9eff;margin-right:4px"></span>轨迹</span>
      <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#18a058;margin-right:4px"></span>良好</span>
      <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f0a020;margin-right:4px"></span>偏差大</span>
    </div>

    <!-- 缩放提示 -->
    <div style="position: absolute; top: 8px; right: 12px; font-size: 11px; color: #555;">
      滚轮缩放 · 拖拽平移
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'

interface PhotoPoint {
  file_id: number
  file_name: string
  lat: number
  lng: number
  time_offset_sec: number | null
  match_quality: string
  best_time: string | null
}

const props = defineProps<{
  track: [number, number][]   // [[lat, lng], ...]
  photos: PhotoPoint[]
  height?: number
}>()

const container = ref<HTMLDivElement | null>(null)
const width = ref(800)
const svgHeight = computed(() => props.height ?? 400)

// ── 缩放/平移状态 ──────────────────────────────────────────────────────────
const scale = ref(1)
const offset = ref({ x: 0, y: 0 })
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0 })

// ── 坐标映射 ───────────────────────────────────────────────────────────────
const PADDING = 32

interface Bounds {
  minLat: number; maxLat: number; minLng: number; maxLng: number
}

const bounds = computed<Bounds | null>(() => {
  const all: [number, number][] = [
    ...props.track,
    ...props.photos.map(p => [p.lat, p.lng] as [number, number]),
  ]
  if (!all.length) return null
  const lats = all.map(p => p[0])
  const lngs = all.map(p => p[1])
  return {
    minLat: Math.min(...lats), maxLat: Math.max(...lats),
    minLng: Math.min(...lngs), maxLng: Math.max(...lngs),
  }
})

function project(lat: number, lng: number): [number, number] {
  const b = bounds.value
  if (!b) return [0, 0]
  const w = width.value - PADDING * 2
  const h = svgHeight.value - PADDING * 2
  const latRange = b.maxLat - b.minLat || 0.001
  const lngRange = b.maxLng - b.minLng || 0.001

  // 保持纵横比
  const scaleW = w / lngRange
  const scaleH = h / latRange
  const s = Math.min(scaleW, scaleH)
  const drawW = lngRange * s
  const drawH = latRange * s
  const xOff = PADDING + (w - drawW) / 2
  const yOff = PADDING + (h - drawH) / 2

  const x = xOff + (lng - b.minLng) * s
  const y = yOff + (b.maxLat - lat) * s  // y 轴翻转

  // 应用缩放和平移
  return [
    x * scale.value + offset.value.x,
    y * scale.value + offset.value.y,
  ]
}

const projectedTrack = computed(() =>
  props.track.map(([lat, lng]) => project(lat, lng))
)

const projectedPhotos = computed(() =>
  props.photos.map(p => {
    const [x, y] = project(p.lat, p.lng)
    return { ...p, x, y }
  })
)

// ── 交互 ───────────────────────────────────────────────────────────────────
function onWheel(e: WheelEvent) {
  const delta = e.deltaY > 0 ? 0.85 : 1.18
  const rect = container.value!.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top

  // 以鼠标为中心缩放
  offset.value.x = mx - (mx - offset.value.x) * delta
  offset.value.y = my - (my - offset.value.y) * delta
  scale.value *= delta
}

function onMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  isPanning.value = true
  panStart.value = { x: e.clientX - offset.value.x, y: e.clientY - offset.value.y }
}

function onMouseUp() {
  isPanning.value = false
}

function onMouseMove(e: MouseEvent) {
  if (isPanning.value) {
    const rect = container.value!.getBoundingClientRect()
    // 只有在 SVG 区域内才平移
    if (e.clientX >= rect.left && e.clientX <= rect.right) {
      offset.value.x = e.clientX - panStart.value.x
      offset.value.y = e.clientY - panStart.value.y
    }
  }
}

// ── Tooltip ───────────────────────────────────────────────────────────────
const tooltip = ref<{ visible: boolean; x: number; y: number; photo: PhotoPoint | null }>({
  visible: false, x: 0, y: 0, photo: null,
})

function showTooltip(photo: PhotoPoint & { x: number; y: number }, e: MouseEvent) {
  const rect = container.value!.getBoundingClientRect()
  tooltip.value = {
    visible: true,
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
    photo,
  }
}

// ── 格式化 ────────────────────────────────────────────────────────────────
const qualityColor: Record<string, string> = {
  good: '#18a058',
  warning: '#f0a020',
  no_match: '#d03050',
}

const qualityLabel: Record<string, string> = {
  good: '良好',
  warning: '偏差较大',
  no_match: '无匹配',
}

function fmtCoord(lat?: number, lng?: number) {
  if (lat == null || lng == null) return '-'
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`
}

function fmtOffset(sec?: number | null) {
  if (sec == null) return '-'
  const sign = sec >= 0 ? '+' : '-'
  const abs = Math.abs(sec)
  const h = Math.floor(abs / 3600)
  const m = Math.floor((abs % 3600) / 60)
  const s = abs % 60
  if (h > 0) return `${sign}${h}h${m}m`
  if (m > 0) return `${sign}${m}m${s}s`
  return `${sign}${s}s`
}

// ── 响应容器宽度 ──────────────────────────────────────────────────────────
let ro: ResizeObserver | null = null

onMounted(() => {
  if (container.value) {
    width.value = container.value.clientWidth || 800
    ro = new ResizeObserver(entries => {
      width.value = entries[0].contentRect.width
    })
    ro.observe(container.value)
  }
})

onUnmounted(() => ro?.disconnect())

// 数据变化时重置视图
watch(() => [props.track.length, props.photos.length], () => {
  scale.value = 1
  offset.value = { x: 0, y: 0 }
})
</script>
