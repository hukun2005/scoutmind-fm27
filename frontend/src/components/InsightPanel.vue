/**
 * 结论面板：把「先看结论、再看依据」固定为页面第一层。
 *
 * 只负责排版与状态色，不生成任何业务结论；调用方必须传入真实字段，
 * 无数据时写明「数据不足」，不得用 0 或推测填充。
 * `badge` 用于标注结论来源（例如「规则生成」「数据事实」），避免把推测写成事实。
 */

<script setup lang="ts">
import type { InsightItem, InsightTone } from '../types/ui'

withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    /** 面板整体状态色。 */
    tone?: InsightTone
    /** 结论来源标注，例如「规则生成」。 */
    badge?: string
    /** 结构化结论条目。 */
    items?: InsightItem[]
    /** 数据时间、来源或边界说明。 */
    footnote?: string
    /** 紧凑模式，用于侧栏或高密度页面。 */
    dense?: boolean
  }>(),
  { title: '结论', subtitle: '', tone: 'info', badge: '', items: () => [], footnote: '', dense: false },
)
</script>

<template>
  <section class="insight" :class="[`insight--${tone}`, { 'insight--dense': dense }]" aria-label="结论摘要">
    <header v-if="title || badge || $slots.actions" class="insight__head">
      <div class="insight__titles">
        <h2 v-if="title" class="insight__title">{{ title }}</h2>
        <p v-if="subtitle" class="insight__subtitle">{{ subtitle }}</p>
      </div>
      <div class="insight__meta">
        <span v-if="badge" class="insight__badge">{{ badge }}</span>
        <slot name="actions" />
      </div>
    </header>

    <div v-if="$slots.default" class="insight__body">
      <slot />
    </div>

    <ul v-if="items.length > 0" class="insight__items">
      <li v-for="(item, index) in items" :key="`${item.label ?? 'item'}-${index}`" class="insight__item">
        <span v-if="item.label" class="insight__label">{{ item.label }}</span>
        <span class="insight__text" :class="item.tone ? `insight__text--${item.tone}` : undefined">{{ item.text }}</span>
      </li>
    </ul>

    <footer v-if="footnote || $slots.footer" class="insight__foot">
      <slot name="footer">{{ footnote }}</slot>
    </footer>
  </section>
</template>

<style scoped>
.insight {
  --insight-accent: var(--sm-accent-cyan);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--sm-space-3);
  padding: var(--sm-space-4);
  border: 1px solid var(--sm-border);
  border-left: 3px solid var(--insight-accent);
  border-radius: var(--sm-radius-lg);
  background:
    radial-gradient(520px 180px at 100% 0%, rgba(49, 95, 206, 0.05), transparent 72%),
    var(--sm-surface);
}

.insight--success {
  --insight-accent: var(--sm-status-success);
}

.insight--warning {
  --insight-accent: var(--sm-status-warning);
}

.insight--danger {
  --insight-accent: var(--sm-status-danger);
}

.insight--neutral {
  --insight-accent: var(--sm-border-strong);
}

.insight--dense {
  gap: var(--sm-space-2);
  padding: var(--sm-space-3);
}

.insight__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sm-space-3);
}

.insight__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.insight__title {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-md);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: 0.01em;
}

.insight__subtitle {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-xs);
  line-height: 1.5;
}

.insight__meta {
  display: flex;
  align-items: center;
  gap: var(--sm-space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.insight__badge {
  padding: 2px var(--sm-space-2);
  border: 1px solid color-mix(in srgb, var(--insight-accent) 34%, transparent);
  border-radius: var(--sm-radius-pill);
  background: color-mix(in srgb, var(--insight-accent) 10%, transparent);
  color: var(--sm-text-secondary);
  font-size: var(--sm-fs-2xs);
  white-space: nowrap;
}

.insight__body {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  line-height: 1.65;
}

.insight__items {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sm-space-2) var(--sm-space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.insight__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding-left: var(--sm-space-3);
  border-left: 2px solid color-mix(in srgb, var(--insight-accent) 45%, transparent);
}

.insight__label {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  font-weight: var(--sm-fw-semibold);
  letter-spacing: var(--sm-tracking-label);
}

.insight__text {
  color: var(--sm-text-primary);
  font-size: var(--sm-fs-sm);
  line-height: 1.55;
}

.insight__text--success {
  color: var(--sm-status-success);
}

.insight__text--warning {
  color: var(--sm-status-warning);
}

.insight__text--danger {
  color: var(--sm-status-danger);
}

.insight__text--neutral {
  color: var(--sm-text-secondary);
}

.insight__foot {
  color: var(--sm-text-3);
  font-size: var(--sm-fs-2xs);
  line-height: 1.6;
}

@media (max-width: 720px) {
  .insight__head {
    flex-direction: column;
    align-items: flex-start;
  }

  .insight__items {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
