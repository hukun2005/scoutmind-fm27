/** 区块容器：带标题、操作区与可选脚注的面板。 */

<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 分区标题；省略时渲染为无标题面板。 */
    title?: string
    /** 标题下方的简短说明。 */
    subtitle?: string
    /** 去掉主体内边距（表格与图表自行管理间距）。 */
    flush?: boolean
    /** 紧凑纵向间距，用于高密度仪表盘。 */
    dense?: boolean
    /** 顶部强调光线（用于当前关注的核心区块）。 */
    accent?: boolean
  }>(),
  { title: '', subtitle: '', flush: false, dense: false, accent: false },
)
</script>

<template>
  <section class="section-card" :class="{ 'section-card--dense': dense, 'section-card--accent': accent }">
    <header v-if="title || $slots.actions" class="section-card__head">
      <div class="section-card__titles">
        <h2 v-if="title" class="section-card__title">{{ title }}</h2>
        <p v-if="subtitle" class="section-card__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="section-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="section-card__body" :class="{ 'section-card__body--flush': flush }">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="section-card__footer">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.section-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--sm-border);
  border-radius: var(--sm-radius-lg);
  background: var(--sm-surface);
  box-shadow: var(--sm-shadow-1);
}

.section-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  border-radius: var(--sm-radius-lg) var(--sm-radius-lg) 0 0;
  background: linear-gradient(90deg, rgba(53, 106, 230, 0.35), rgba(53, 106, 230, 0.08) 42%, transparent);
  opacity: 0.55;
  pointer-events: none;
}

.section-card--accent::before {
  background: var(--sm-gradient-accent);
  opacity: 0.9;
}

.section-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-3);
  padding: var(--sm-space-3) var(--sm-space-4);
  border-bottom: 1px solid var(--sm-border);
}

.section-card--dense .section-card__head {
  padding: var(--sm-space-2) var(--sm-space-3);
}

.section-card__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.section-card__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.01em;
}

.section-card__subtitle {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
}

.section-card__actions {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.section-card__body {
  padding: var(--sm-space-4);
  min-width: 0;
}

.section-card--dense .section-card__body {
  padding: var(--sm-space-3);
}

.section-card__body--flush {
  padding: 0;
}

.section-card__footer {
  padding: var(--sm-space-2) var(--sm-space-4) var(--sm-space-3);
  border-top: 1px solid var(--sm-border);
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
}
</style>
