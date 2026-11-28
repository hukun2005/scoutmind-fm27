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
  | 'menu'
  | 'search'
  | 'close'
  | 'chevron-left'
  | 'chevron-right'
  | 'chevron-down'
  | 'chevron-up'
  | 'plus'
  | 'minus'
  | 'trash'
  | 'edit'
  | 'star'
  | 'eye'
  | 'filter'
  | 'sort'
  | 'bell'
  | 'sync'
  | 'info'
  | 'external'
  | 'compare'
  | 'sparkle'

const props = withDefaults(
  defineProps<{
    /** Icon to draw; unknown names render an empty box. */
    name: IconName
    /** Square size in pixels. */
    size?: number
    /** Fill the glyph with currentColor (used by the active star). */
    filled?: boolean
  }>(),
  { size: 18, filled: false },
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
  menu: ['M4 7h16', 'M4 12h16', 'M4 17h16'],
  search: ['M11 17.4a6.4 6.4 0 1 0 0-12.8 6.4 6.4 0 0 0 0 12.8Z', 'm15.8 15.8 4.2 4.2'],
  close: ['m6 6 12 12', 'M18 6 6 18'],
  'chevron-left': ['M14.5 5.5 8 12l6.5 6.5'],
  'chevron-right': ['m9.5 5.5 6.5 6.5-6.5 6.5'],
  'chevron-down': ['m6 9.5 6 6 6-6'],
  'chevron-up': ['m6 14.5 6-6 6 6'],
  plus: ['M12 5v14', 'M5 12h14'],
  minus: ['M5 12h14'],
  trash: ['M4 7h16', 'M9.5 7V4.6h5V7', 'M6.5 7l1 13h9l1-13', 'M10 11v5', 'M14 11v5'],
  edit: ['M4 20h4L18.2 9.8 14.2 5.8 4 16z', 'm13.2 6.8 4 4'],
  star: ['M12 3.6l2.6 5.3 5.9.9-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.8l5.9-.9z'],
  eye: [
    'M2.8 12S6.2 6.2 12 6.2 21.2 12 21.2 12 17.8 17.8 12 17.8 2.8 12 2.8 12Z',
    'M12 14.7a2.7 2.7 0 1 0 0-5.4 2.7 2.7 0 0 0 0 5.4Z',
  ],
  filter: ['M3.6 5.4h16.8l-6.6 7.6V20l-3.6-2v-5z'],
  sort: ['M8 5v14', 'm5 8 3-3 3 3', 'M16 19V5', 'm13 16 3 3 3-3'],
  bell: [
    'M6.2 9.4a5.8 5.8 0 0 1 11.6 0c0 4 1.4 5.4 1.4 5.4H4.8s1.4-1.4 1.4-5.4Z',
    'M10 18.4a2.1 2.1 0 0 0 4 0',
  ],
  sync: [
    'M19.4 12a7.4 7.4 0 0 1-12.4 5.4',
    'M4.6 12a7.4 7.4 0 0 1 12.4-5.4',
    'M4.4 4.4v4h4',
    'M19.6 19.6v-4h-4',
  ],
  info: ['M12 20.4a8.4 8.4 0 1 0 0-16.8 8.4 8.4 0 0 0 0 16.8Z', 'M12 11v5.2', 'M12 7.8h.01'],
  external: ['M14 4h6v6', 'M20 4l-8.4 8.4', 'M18 14v5H5V6h5'],
  compare: ['M7 4v16', 'M17 4v16', 'M3.6 8.2h6.8', 'M13.6 15.8h6.8'],
  sparkle: ['M12 3.4 13.8 9l5.6 1.8-5.6 1.8L12 18.2l-1.8-5.6L4.6 10.8 10.2 9z'],
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
    :fill="filled ? 'currentColor' : 'none'"
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
