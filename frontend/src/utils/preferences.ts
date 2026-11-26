/**
 * 外观偏好：界面动效开关。
 *
 * 默认跟随系统（`prefers-reduced-motion`），用户可在「系统设置 → 外观」中手动关闭动效。
 * 偏好写入 localStorage，并在启动时立即应用，避免首屏动画闪现。
 */

const MOTION_KEY = 'scoutmind.motion'

/** `auto` 跟随系统；`reduced` 强制关闭动效。 */
export type MotionPreference = 'auto' | 'reduced'

/** 读取已保存的动效偏好。 */
export function getMotionPreference(): MotionPreference {
  try {
    return window.localStorage.getItem(MOTION_KEY) === 'reduced' ? 'reduced' : 'auto'
  } catch {
    return 'auto'
  }
}

/** 把偏好应用为根节点属性（CSS 在 base.css 中读取）。 */
export function applyMotionPreference(preference: MotionPreference): void {
  document.documentElement.dataset.reduceMotion = preference === 'reduced' ? '1' : '0'
}

/** 保存并立即应用偏好。 */
export function setMotionPreference(preference: MotionPreference): void {
  try {
    window.localStorage.setItem(MOTION_KEY, preference)
  } catch {
    // 存储失败时只影响下次启动，当前会话仍然生效。
  }
  applyMotionPreference(preference)
}
