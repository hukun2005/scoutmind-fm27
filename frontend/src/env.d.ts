/// <reference types="vite/client" />
/// <reference types="element-plus/global" />

/** 桌面外壳（Electron）通过 preload 暴露的只读信息；浏览器中为 undefined。 */
interface ScoutMindDesktopInfo {
  product: string
  version: string
  backend: { url: string; port: number | null; running: boolean }
  dataDir: string
  logsDir: string
}

interface Window {
  scoutmindDesktop?: {
    getInfo: () => Promise<ScoutMindDesktopInfo>
  }
}
