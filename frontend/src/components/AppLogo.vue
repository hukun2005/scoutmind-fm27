/**
 * ScoutMind 品牌标识（与 SVG / PNG / ICO 使用同一几何定义）。
 *
 * 变体：
 *   app   —— 深蓝圆角底板 + 白色 S（应用图标、导航品牌位）
 *   light —— 深蓝 S，用于浅色背景
 *   dark  —— 白色 S，用于深色背景
 *   mono  —— 单色 S，用于单色印刷或禁用彩色的场景
 */

<script setup lang="ts">
import { computed } from 'vue'

type LogoVariant = 'app' | 'light' | 'dark' | 'mono'

const props = withDefaults(
  defineProps<{
    variant?: LogoVariant
    size?: number
    /** 装饰性使用（旁边已有文字）时从无障碍树隐藏。 */
    decorative?: boolean
  }>(),
  { variant: 'app', size: 32, decorative: false },
)

/** 与 tools/brand/generate_brand_assets.py 中 S_PATH 完全一致。 */
const S_PATH = 'M174 64H108A34 34 0 0 0 108 132H148A34 34 0 0 1 148 200H82'

const stroke = computed(() => {
  if (props.variant === 'light') return '#1E3A8A'
  if (props.variant === 'mono') return '#172334'
  return '#FFFFFF'
})
const node = computed(() => (props.variant === 'mono' ? null : '#22D3EE'))
const tiled = computed(() => props.variant === 'app')
</script>

<template>
  <svg
    class="app-logo"
    :width="size"
    :height="size"
    viewBox="0 0 256 256"
    fill="none"
    :role="decorative ? undefined : 'img'"
    :aria-label="decorative ? undefined : 'ScoutMind FM27'"
    :aria-hidden="decorative ? 'true' : undefined"
    :focusable="decorative ? 'false' : undefined"
    data-testid="app-logo"
  >
    <rect v-if="tiled" width="256" height="256" rx="54" fill="#0B1B33" />
    <rect
      v-if="tiled"
      x="10"
      y="10"
      width="236"
      height="236"
      rx="44"
      stroke="#FFFFFF"
      stroke-opacity="0.12"
      stroke-width="2"
    />
    <path
      :d="S_PATH"
      :stroke="stroke"
      stroke-width="22"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle v-if="node" cx="128" cy="132" r="7" :fill="node" />
  </svg>
</template>

<style scoped>
.app-logo {
  display: block;
  flex: 0 0 auto;
}
</style>
