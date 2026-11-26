'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// 只暴露只读的桌面信息接口，不暴露 ipcRenderer 或 Node.js 能力
contextBridge.exposeInMainWorld('scoutmindDesktop', {
  getInfo: () => ipcRenderer.invoke('desktop:info'),
});
