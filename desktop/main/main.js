'use strict';

const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, session, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

const PRODUCT = 'ScoutMind FM27';
const isDev = !app.isPackaged;

app.setName(PRODUCT);

let mainWindow = null;
let tray = null;
let backend = null;
let backendPort = 0;
let quitting = false;
let backendReady = false;
let origin = '';

function resourcesRoot() {
  return isDev ? path.join(__dirname, '..') : process.resourcesPath;
}

function backendExecutable() {
  if (isDev && process.env.SCOUTMIND_BACKEND_EXE) {
    return process.env.SCOUTMIND_BACKEND_EXE;
  }
  return path.join(resourcesRoot(), 'backend', 'ScoutMindFM27.exe');
}

function frontendDist() {
  return isDev ? path.join(__dirname, '..', '..', 'frontend', 'dist') : path.join(resourcesRoot(), 'frontend');
}

function dataDirectory() {
  return path.join(app.getPath('userData'), 'data');
}

function logsDirectory() {
  return path.join(app.getPath('userData'), 'logs');
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function waitForHealth(port, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/v1/health`);
      if (response.ok) return true;
    } catch {
      // 后端尚未就绪
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

function writeRuntimeInfo(payload) {
  const target = path.join(app.getPath('userData'), 'runtime.json');
  fs.writeFileSync(target, JSON.stringify(payload, null, 2), 'utf8');
}

async function startBackend() {
  const exe = backendExecutable();
  if (!fs.existsSync(exe)) {
    throw new Error(`找不到本地服务程序：${exe}\n请重新安装 ScoutMind FM27。`);
  }
  fs.mkdirSync(path.join(dataDirectory(), 'raw'), { recursive: true });
  fs.mkdirSync(logsDirectory(), { recursive: true });

  const logPath = path.join(logsDirectory(), 'backend.log');
  const attempts = 3;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    backendPort = await freePort();
    const logStream = fs.createWriteStream(logPath, { flags: 'a' });
    const child = spawn(exe, ['--headless', '--watch-stdin', '--port', String(backendPort)], {
      cwd: path.dirname(exe),
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        SCOUTMIND_DATA_DIR: dataDirectory(),
        SCOUTMIND_DATABASE_URL: `sqlite:///${path.join(dataDirectory(), 'scoutmind.db').replace(/\\/g, '/')}`,
        SCOUTMIND_FRONTEND_DIST: frontendDist(),
      },
    });
    backend = child;
    child.stdout.pipe(logStream);
    child.stderr.pipe(logStream);
    child.on('exit', (code) => {
      if (backend === child) backend = null;
      if (!quitting && backendReady && mainWindow) {
        dialog.showErrorBox(PRODUCT, `本地服务意外退出（代码 ${code}）。\n日志：${logPath}`);
      }
    });

    if (await waitForHealth(backendPort)) {
      backendReady = true;
      origin = `http://127.0.0.1:${backendPort}`;
      writeRuntimeInfo({ port: backendPort, pid: child.pid, startedAt: new Date().toISOString() });
      return origin;
    }

    // 端口可能落在 Windows 保留段（WinError 10013）或启动前被占用：换端口重试。
    try {
      child.kill();
    } catch {
      // 进程已退出时忽略
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
    logStream.end();
  }

  throw new Error(`本地服务启动超时。\n日志：${logPath}`);
}

function stopBackend() {
  if (!backend) return;
  const pid = backend.pid;
  backend = null;
  try {
    // /T 一并结束 uvicorn 派生的子进程，避免残留
    spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true });
  } catch {
    // 进程已退出时忽略
  }
}

function hardenSession(localOrigin) {
  const current = session.defaultSession;
  current.webRequest.onHeadersReceived((details, callback) => {
    if (!details.url.startsWith(localOrigin)) {
      callback({ responseHeaders: details.responseHeaders });
      return;
    }
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        ],
      },
    });
  });
  current.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    backgroundColor: '#F5F7FA',
    title: PRODUCT,
    icon: isDev
      ? path.join(__dirname, '..', 'build', 'icon.ico')
      : path.join(process.resourcesPath, 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
  mainWindow.on('close', (event) => {
    if (quitting) return;
    event.preventDefault();
    const choice = dialog.showMessageBoxSync(mainWindow, {
      type: 'question',
      buttons: ['退出', '取消'],
      defaultId: 1,
      cancelId: 1,
      title: PRODUCT,
      message: '退出 ScoutMind FM27？',
      detail: '退出后本地服务会停止，数据仍保留在本机。',
    });
    if (choice === 0) {
      quitting = true;
      app.quit();
    }
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(origin)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('did-fail-load', (_event, code, description) => {
    if (code === -3) return; // 主动取消
    dialog.showErrorBox(PRODUCT, `界面加载失败：${description}\n日志：${path.join(logsDirectory(), 'backend.log')}`);
  });

  mainWindow.loadURL(origin);
}

function buildMenu() {
  const template = [
    {
      label: '应用',
      submenu: [
        { label: '打开数据目录', click: () => shell.openPath(app.getPath('userData')) },
        { label: '打开日志目录', click: () => shell.openPath(logsDirectory()) },
        { type: 'separator' },
        { role: 'quit', label: '退出' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload', label: '刷新' },
        { role: 'resetZoom', label: '重置缩放' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '缩小' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: `关于 ${PRODUCT}`,
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: `关于 ${PRODUCT}`,
              message: `${PRODUCT} V${app.getVersion()}`,
              detail: `完全本地运行，无需联网。\n数据目录：${app.getPath('userData')}\n本地服务：${origin || '未启动'}`,
              buttons: ['确定'],
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createTray() {
  const iconPath = isDev
    ? path.join(__dirname, '..', 'build', 'icon.png')
    : path.join(process.resourcesPath, 'icon.png');
  const image = nativeImage.createFromPath(iconPath);
  tray = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image.resize({ width: 16, height: 16 }));
  tray.setToolTip(PRODUCT);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '显示主窗口', click: () => (mainWindow ? mainWindow.show() : createWindow()) },
      { label: '打开数据目录', click: () => shell.openPath(app.getPath('userData')) },
      { type: 'separator' },
      { label: '退出', click: () => { quitting = true; app.quit(); } },
    ])
  );
  tray.on('double-click', () => (mainWindow ? mainWindow.show() : createWindow()));
}

function registerIpc() {
  ipcMain.handle('desktop:info', (event) => {
    const senderUrl = event.senderFrame ? event.senderFrame.url : '';
    if (!origin || !senderUrl.startsWith(origin)) {
      throw new Error('untrusted sender');
    }
    let version = app.getVersion();
    return {
      product: PRODUCT,
      version,
      backend: { url: origin, port: backendPort, running: Boolean(backend) },
      dataDir: dataDirectory(),
      logsDir: logsDirectory(),
    };
  });
}

async function boot() {
  app.setAppUserModelId('com.scoutmind.fm27');
  registerIpc();
  try {
    await startBackend();
    hardenSession(origin);
    buildMenu();
    createTray();
    createWindow();
  } catch (error) {
    dialog.showErrorBox(PRODUCT, `${error.message || error}`);
    quitting = true;
    app.quit();
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
  app.whenReady().then(boot);
}

app.on('before-quit', () => {
  quitting = true;
  stopBackend();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
