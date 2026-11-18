/**
 * Inline SVG icon set.
 *
 * `@element-plus/icons-vue` is not a declared dependency of this package, so the
 * handful of navigation glyphs are drawn here instead of adding a package.
 */

<script setup lang="ts">
import { computed } from 'vue'

type IconName =
  | 'overview'
  | 'players'
  | 'watchlist'
  | 'scouting'
  | 'squad'
  | 'development'
  | 'performance'
  | 'transfers'
  | 'agent'
  | 'data'
  | 'refresh'
  | 'settings'
  | 'back'
  | 'alert'
  | 'check'

const props = withDefaults(
  defineProps<{
    /** Icon to draw; unknown names render an empty box. */
    name: IconName
    /** Square size in pixels. */
    size?: number
  }>(),
  { size: 18 },
)

/** 24×24 stroke paths, one or more per icon. */
const ICON_PATHS: Record<IconName, string[]> = {
  overview: ['M4 4h7v7H4z', 'M13 4h7v4.5h-7z', 'M13 10.5h7V20h-7z', 'M4 13h7v7H4z'],
  players: [
    'M9 11.5a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2Z',
    'M2.6 20a6.4 6.4 0 0 1 12.8 0',
    'M16.4 6.4a3 3 0 0 1 0 5.6',
    'M18.2 20a5.6 5.6 0 0 0-3-4.9',
  ],
  watchlist: ['M6.5 3.5h11v17l-5.5-4-5.5 4z'],
  squad: [
    'M8.6 3.4h6.8v3.2H8.6z',
    'M4.6 6.6h14.8v13.8H4.6z',
    'M9.2 12.4v3.6',
    'M14.8 12.4v3.6',
  ],
  development: ['M4 18.6h16', 'M6.2 15.4l3.4-3.6 3 2.4 4.6-6', 'M17.2 8.2h2.6v2.6'],
  performance: [
    'M4 20V9.4',
    'M9.4 20V4.6',
    'M14.8 20v-7.2',
    'M20.2 20v-4.4',
  ],
  scouting: [
    'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z',
    'M12 16.2a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4Z',
    'M12 13.1a1.1 1.1 0 1 0 0-2.2 1.1 1.1 0 0 0 0 2.2Z',
  ],
  transfers: ['M4 8.2h13.4', 'M14.2 4.8 17.6 8.2l-3.4 3.4', 'M20 15.8H6.6', 'M9.8 12.4 6.4 15.8l3.4 3.4'],
  agent: ['M4.5 5h15v10.4h-9.2L4.5 19.6z', 'M8.2 9h7.6', 'M8.2 12.2h4.8'],
  data: [
    'M12 3.4c4.3 0 7.8 1.3 7.8 2.9S16.3 9.2 12 9.2 4.2 7.9 4.2 6.3 7.7 3.4 12 3.4Z',
    'M4.2 6.3v11.4c0 1.6 3.5 2.9 7.8 2.9s7.8-1.3 7.8-2.9V6.3',
    'M4.2 12c0 1.6 3.5 2.9 7.8 2.9s7.8-1.3 7.8-2.9',
  ],
  refresh: ['M19.6 12a7.6 7.6 0 1 1-2.2-5.4', 'M19.8 4.2v4h-4'],
  settings: [
    'M4 7.5h4.4',
    'M15.6 7.5H20',
    'M12 5.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z',
    'M4 12h8.4',
    'M15.6 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z',
    'M4 16.5h2.4',
    'M10.6 14.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z',
    'M13.6 16.5H20',
  ],
  back: ['M14.5 5.5 8 12l6.5 6.5'],
  alert: ['M12 3.8 21 19.6H3z', 'M12 9.6v4.2', 'M12 16.4h.01'],
  check: ['m5 12.6 4.4 4.4L19 7.4'],
}

/** Paths of the selected icon. */
const paths = computed(() => ICON_PATHS[props.name] ?? [])
</script>

<template>
  <svg
    class="sm-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(path, index) in paths" :key="index" :d="path" />
  </svg>
</template>

<style scoped>
.sm-icon {
  display: block;
  flex: 0 0 auto;
}
</style>
