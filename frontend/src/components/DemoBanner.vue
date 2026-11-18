/**
 * Demo-data banner.
 *
 * Visible when `meta.demo_mode` is true, or when any loaded record carried
 * `source === "synthetic_fixture"`. Dismissal lasts for the browser tab session.
 */

<script setup lang="ts">
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
</script>

<template>
  <el-alert
    v-if="session.showDemoBanner"
    class="demo-banner"
    type="warning"
    :closable="true"
    show-icon
    @close="session.dismissDemo()"
  >
    <template #title>
      <span class="demo-banner__title">演示数据（synthetic_fixture），不可用于真实决策</span>
    </template>
    <p class="demo-banner__text">
      后端当前返回演示数据：数值仅用于验证界面与统计口径，不代表任何真实 FM27 存档。
      导入真实扫描数据后，此横幅会自动消失。
    </p>
  </el-alert>
</template>

<style scoped>
.demo-banner {
  margin-bottom: var(--sm-space-3);
}

.demo-banner__title {
  font-weight: var(--sm-fw-semibold);
}

.demo-banner__text {
  margin-top: 2px;
  font-size: var(--sm-fs-xs);
  line-height: 1.6;
}
</style>
