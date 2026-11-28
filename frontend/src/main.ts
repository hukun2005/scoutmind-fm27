/** Application entry: Element Plus (zh-CN), Pinia, router and the design tokens. */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/element.css'
import App from './App.vue'
import { router } from './router'
import { applyMotionPreference, getMotionPreference } from './utils/preferences'

// 产品通过全局浅色 Token 控制主题，不再依赖 html.dark 类。
// 用户选择的界面动效偏好在首屏渲染前生效。
applyMotionPreference(getMotionPreference())

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
