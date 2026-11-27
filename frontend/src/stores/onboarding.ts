/**
 * 首次启动引导状态：只在用户从未完成/跳过引导时自动弹出，可从设置重新打开。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { asApiError, type ApiError } from '../api/client'
import { getOnboarding, type OnboardingResponse } from '../api/system'

const DISMISS_KEY = 'scoutmind.onboardingDismissed'

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === '1'
  } catch {
    return false
  }
}

function persistDismissed(value: boolean): void {
  try {
    if (value) window.localStorage.setItem(DISMISS_KEY, '1')
    else window.localStorage.removeItem(DISMISS_KEY)
  } catch {
    // 存储失败时仅在本次会话生效，不影响使用。
  }
}

export const useOnboardingStore = defineStore('onboarding', () => {
  const data = ref<OnboardingResponse | null>(null)
  const loading = ref(false)
  const error = ref<ApiError | null>(null)
  const visible = ref(false)
  const dismissed = ref(readDismissed())

  const hasData = computed(() => data.value?.data.has_players === true)
  const needsAttention = computed(() => data.value?.status !== 'ready')

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      data.value = await getOnboarding()
    } catch (caught) {
      error.value = asApiError(caught)
      data.value = null
    } finally {
      loading.value = false
    }
  }

  /**
   * 首次启动时自动打开。
   *
   * 只在检查成功且确实需要处理时弹出（没有数据或检查未通过）；接口不可用或已就绪时不打扰
   * 用户，也不阻塞其他页面操作。用户跳过/完成后不再自动弹出。
   */
  async function maybeOpen(): Promise<void> {
    if (dismissed.value) return
    await load()
    const payload = data.value
    if (!payload || !payload.data || typeof payload.data.has_players !== 'boolean') return
    if (!payload.data.has_players || payload.status === 'needs_attention') {
      visible.value = true
    }
  }

  /** 从设置重新打开引导。 */
  function reopen(): void {
    visible.value = true
    void load()
  }

  /** 跳过/完成引导。 */
  function dismiss(): void {
    visible.value = false
    dismissed.value = true
    persistDismissed(true)
  }

  /** 仅关闭当前弹窗，不改变"已跳过"状态。 */
  function close(): void {
    visible.value = false
  }

  return {
    data,
    loading,
    error,
    visible,
    dismissed,
    hasData,
    needsAttention,
    load,
    maybeOpen,
    reopen,
    dismiss,
    close,
  }
})
