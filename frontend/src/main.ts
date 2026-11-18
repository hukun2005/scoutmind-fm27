/** Application entry: Element Plus (zh-CN, dark theme), Pinia, router and the design tokens. */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/element.css'
import App from './App.vue'
import { router } from './router'

// The product is a dark professional analysis console; Element Plus keys its dark theme off this class.
document.documentElement.classList.add('dark')

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
