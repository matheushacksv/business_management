<script setup lang="ts">
// Thin Chart.js wrapper (canvas, low memory). Only the pieces we use are registered.
import {
  BarController, BarElement, CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale,
  LineController, LineElement, PointElement, Tooltip,
} from 'chart.js'
import { Bar, Line } from 'vue-chartjs'

ChartJS.register(
  BarController, BarElement, CategoryScale, Filler, Legend, LinearScale,
  LineController, LineElement, PointElement, Tooltip,
)
ChartJS.defaults.font.family = 'Inter, system-ui, sans-serif'

export interface Series { label: string; data: number[]; color: string; fill?: boolean; type?: 'bar' | 'line' }

const props = defineProps<{ type: 'bar' | 'line'; labels: string[]; series: Series[]; money?: boolean; height?: number }>()

// Axis/grid/legend colors follow the theme (canvas can't read CSS classes)
const colorMode = useColorMode()
const ink = computed(() => (colorMode.value === 'dark'
  ? { text: 'rgba(255,255,255,0.6)', grid: 'rgba(255,255,255,0.08)' }
  : { text: 'rgba(15,23,42,0.6)', grid: 'rgba(15,23,42,0.08)' }))

const data = computed(() => ({
  labels: props.labels,
  datasets: props.series.map(s => ({
    type: s.type ?? props.type,
    label: s.label,
    data: s.data,
    borderColor: s.color,
    backgroundColor: s.fill || props.type === 'bar' ? `${s.color}33` : s.color,
    borderWidth: 2,
    borderRadius: 6,
    fill: s.fill ?? false,
    tension: 0.3,
    pointRadius: 0,
    pointHoverRadius: 4,
  })),
}))

const options = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false as const, // no per-frame work
  interaction: { mode: 'index' as const, intersect: false },
  plugins: {
    legend: { labels: { usePointStyle: true, boxWidth: 8, color: ink.value.text } },
    tooltip: {
      callbacks: props.money
        ? { label: (ctx: any) => `${ctx.dataset.label}: ${formatMoney(ctx.parsed.y)}` }
        : {},
    },
  },
  scales: {
    y: {
      grid: { color: ink.value.grid },
      border: { color: ink.value.grid },
      ticks: {
        color: ink.value.text,
        ...(props.money
          ? { callback: (v: any) => new Intl.NumberFormat('pt-BR', { notation: 'compact', style: 'currency', currency: 'BRL' }).format(v) }
          : {}),
      },
    },
    x: { grid: { display: false }, border: { color: ink.value.grid }, ticks: { color: ink.value.text } },
  },
}))
</script>

<template>
  <div :style="{ height: `${height ?? 280}px` }">
    <Bar v-if="type === 'bar'" :data="(data as any)" :options="(options as any)" />
    <Line v-else :data="(data as any)" :options="(options as any)" />
  </div>
</template>
