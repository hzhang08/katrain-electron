const {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  dialog,
  shell,
  clipboard,
} = require("electron");
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { RecentGames } = require("./recent-games.cjs");

const restoreTest = process.argv
  .find((arg) => arg.startsWith("--restore-smoke="))
  ?.slice("--restore-smoke=".length);
const smoke = process.argv.includes("--smoke") || Boolean(restoreTest);
if (smoke)
  app.setPath(
    "userData",
    restoreTest ||
      fs.mkdtempSync(path.join(os.tmpdir(), "katrain-electron-test-")),
  );
app.setName("KaTrain Electron");
let window,
  backend,
  quitting = false,
  ready = false,
  pendingOpen,
  lastFrame;
const pending = new Map();
const testOutput = app.isPackaged
  ? path.join(os.tmpdir(), "katrain-electron-packaged-smoke")
  : path.join(__dirname, "../test-output");
const userData = app.getPath("userData");
fs.mkdirSync(userData, { recursive: true });
const log = fs.createWriteStream(path.join(userData, "backend.log"), {
  flags: "a",
});
const recentGames = new RecentGames(path.join(userData, "recent-games.json"));
function openGame(file) {
  if (ready) send({ type: "open", path: file });
  else pendingOpen = file;
}
async function openRecent(file) {
  try {
    if (!fs.statSync(file).isFile()) throw Error("Not a file");
    fs.accessSync(file, fs.constants.R_OK);
  } catch {
    recentGames.remove(file);
    menu();
    await dialog.showMessageBox(window, { type: "warning", message: "This game is no longer available.", detail: file, buttons: ["OK"] });
    return;
  }
  openGame(file);
}
function send(data) {
  if (backend?.stdin.writable) backend.stdin.write(JSON.stringify(data) + "\n");
}
function action(name, args = []) {
  send({ type: "action", action: name, args });
}
function key(key, modifiers = []) {
  send({ type: "keydown", key, modifiers });
  send({ type: "keyup", key, modifiers });
}
async function openFile() {
  const choice = await dialog.showOpenDialog(window, {
    properties: ["openFile"],
    filters: [{ name: "Go game records", extensions: ["sgf", "ngf", "gib"] }],
  });
  if (choice.filePaths[0]) openGame(choice.filePaths[0]);
}
function bootBackend() {
  ready = false;
  const resources = app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, "../build/resources");
  const executable = app.isPackaged
    ? path.join(resources, "backend/katrain-host")
    : path.join(__dirname, "../.venv/bin/python");
  const args = app.isPackaged
    ? []
    : ["-u", path.join(__dirname, "../backend/host.py")];
  backend = spawn(executable, args, {
    cwd: userData,
    env: {
      ...process.env,
      KATRAIN_ELECTRON_DATA: userData,
      KATRAIN_ELECTRON_RESOURCES: resources,
      KATRAIN_ELECTRON_TEST: smoke ? "1" : "0",
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  backend.stderr.on("data", (data) => log.write(data));
  backend.on("error", (error) =>
    window?.webContents.send("host", { type: "fatal", message: error.message }),
  );
  createInterface({ input: backend.stdout }).on("line", (line) => {
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      log.write(line + "\n");
      return;
    }
    if (event.type === "ready") {
      ready = true;
      if (pendingOpen) {
        send({ type: "open", path: pendingOpen });
        pendingOpen = null;
      }
    }
    if (event.type === "game-opened") {
      try {
        if (recentGames.add(event.path)) menu();
      } catch (error) { log.write(`Could not save recent games: ${error.message}\n`); }
    }
    if (event.type === "session-saved" && quitting) {
      setTimeout(() => {
        backend?.kill("SIGKILL");
        app.exit(0);
      }, 8000).unref();
    }
    if (event.type === "save-error") {
      quitting = false;
      dialog.showMessageBox(window, {
        type: "error",
        message: "KaTrain is still open because saving failed.",
        detail: event.message,
        buttons: ["OK"],
      });
    }
    if (event.type === "session-warning") {
      log.write(event.message + "\n");
      dialog.showMessageBox(window, {
        type: "warning",
        message: event.message,
        buttons: ["OK"],
      });
    }
    if (event.type === "frame") lastFrame = event;
    if (event.type === "inspection") {
      pending.get(event.request)?.(event);
      pending.delete(event.request);
      return;
    }
    window?.webContents.send("host", event);
  });
  backend.on("exit", (code, signal) => {
    backend = null;
    for (const resolve of pending.values())
      resolve({ error: "Backend exited" });
    pending.clear();
    if (quitting) {
      log.end();
      app.exit(code || 0);
    } else
      window?.webContents.send("host", {
        type: "fatal",
        message: `KaTrain stopped (${signal || code}). Your latest recovery SGF is in the app data folder.`,
      });
  });
}
function menu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "KaTrain Electron",
        submenu: [
          { role: "about" },
          { type: "separator" },
          {
            label: "Settings",
            accelerator: "CmdOrCtrl+,",
            click: () => key("f8"),
          },
          { type: "separator" },
          { role: "hide" },
          { role: "hideOthers" },
          { role: "unhide" },
          { type: "separator" },
          { role: "quit" },
        ],
      },
      {
        label: "File",
        submenu: [
          {
            label: "New Game…",
            accelerator: "CmdOrCtrl+N",
            click: () => action("new-game-popup"),
          },
          { label: "Open Game…", accelerator: "CmdOrCtrl+O", click: openFile },
          {
            label: "Open Recent",
            submenu: recentGames.paths.length ? [
              ...recentGames.paths.map(file => ({
                label: `${path.basename(file)} — ${path.dirname(file)}`,
                click: () => openRecent(file),
              })),
              { type: "separator" },
              { label: "Clear Recent Games", click: () => { recentGames.clear(); menu(); } },
            ] : [{ label: "No Recent Games", enabled: false }],
          },
          {
            label: "Save Game",
            accelerator: "CmdOrCtrl+S",
            click: () => action("save-game"),
          },
          {
            label: "Save Game As…",
            accelerator: "CmdOrCtrl+Shift+S",
            click: () => action("save-game-as-popup"),
          },
          { type: "separator" },
          {
            label: "Open Recovery Game",
            click: () => {
              const file = path.join(userData, "recovery.sgf");
              if (fs.existsSync(file)) send({ type: "open", path: file });
            },
          },
          { label: "Show App Data", click: () => shell.openPath(userData) },
          { type: "separator" },
          { role: "close" },
        ],
      },
      {
        label: "Edit",
        submenu: [
          {
            label: "Copy",
            accelerator: "CmdOrCtrl+C",
            click: () => key("c", ["meta"]),
          },
          {
            label: "Paste",
            accelerator: "CmdOrCtrl+V",
            click: () => key("v", ["meta"]),
          },
          {
            label: "Select All",
            accelerator: "CmdOrCtrl+A",
            click: () => key("a", ["meta"]),
          },
        ],
      },
      {
        label: "Game",
        submenu: [
          { label: "Previous Move", click: () => action("undo", [1]) },
          { label: "Next Move", click: () => action("redo", [1]) },
          { label: "Start", click: () => action("undo", [9999]) },
          { label: "End", click: () => action("redo", [9999]) },
          { label: "AI Move", click: () => action("ai-move") },
        ],
      },
      { label: "View", submenu: [{ role: "togglefullscreen" }] },
      {
        label: "Help",
        submenu: [
          {
            label: "KaTrain Manual",
            click: () =>
              shell.openExternal(
                "https://github.com/sanderland/katrain#manual",
              ),
          },
          {
            label: "Show Backend Log",
            click: () =>
              shell.showItemInFolder(path.join(userData, "backend.log")),
          },
        ],
      },
    ]),
  );
}
app.on("open-file", (event, file) => {
  event.preventDefault();
  openGame(file);
});
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", (_event, argv) => {
    const file = argv.find((a) => /\.(sgf|ngf|gib)$/i.test(a));
    if (file) openGame(file);
    window?.show();
  });
  app.whenReady().then(async () => {
    let bounds = { width: 1360, height: 960 };
    try {
      bounds = JSON.parse(
        fs.readFileSync(path.join(userData, "window.json"), "utf8"),
      );
    } catch {}
    window = new BrowserWindow({
      ...bounds,
      minWidth: 960,
      minHeight: 720,
      title: "KaTrain Electron",
      backgroundColor: "#22303d",
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        backgroundThrottling: false,
      },
    });
    window.on("resize", () => {
      const [width, height] = window.getContentSize();
      send({ type: "resize", width, height });
    });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.on("close", (event) => {
      if (backend) {
        event.preventDefault();
        if (!quitting) app.quit();
      }
      fs.writeFileSync(
        path.join(userData, "window.json"),
        JSON.stringify(window.getNormalBounds()),
      );
    });
    window.on("closed", () => {
      window = null;
      app.quit();
    });
    ipcMain.on("input", (event, data) => {
      if (
        event.sender !== window?.webContents ||
        !data ||
        typeof data !== "object"
      )
        return;
      if (
        [
          "ack",
          "resize",
          "down",
          "up",
          "move",
          "wheel",
          "keydown",
          "keyup",
          "text",
          "blur",
        ].includes(data.type)
      )
        send(data);
    });
    ipcMain.handle("recover", () => {
      if (!backend) bootBackend();
    });
    ipcMain.handle("open", openFile);
    ipcMain.handle("drop", (_event, files) => {
      const file = files.find(
        (p) => typeof p === "string" && /\.(sgf|ngf|gib)$/i.test(p),
      );
      if (file) openGame(file);
    });
    ipcMain.handle("clipboard", () => clipboard.readText());
    await window.loadFile(path.join(__dirname, "index.html"));
    menu();
    bootBackend();
    window.show();
    if (smoke)
      (restoreTest ? runRestoreSmoke() : runSmoke()).catch(async (error) => {
        fs.mkdirSync(testOutput, { recursive: true });
        fs.writeFileSync(path.join(testOutput, "failure.txt"), error.stack);
        console.error(error);
        if (window)
          fs.writeFileSync(
            path.join(testOutput, "failure.png"),
            (await window.webContents.capturePage()).toPNG(),
          );
        send({ type: "quit" });
        await delay(500);
        app.exit(1);
      });
  });
  app.on("before-quit", (event) => {
    if (backend) {
      event.preventDefault();
      if (quitting) return;
      quitting = true;
      send({ type: "quit" });
    }
  });
}
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function inspect() {
  const request = String(Date.now()) + Math.random();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(request);
      reject(Error("Inspection timeout"));
    }, 10000);
    pending.set(request, (data) => {
      clearTimeout(timer);
      resolve(data);
    });
    send({ type: "inspect", request });
  });
}
async function until(fn, timeout = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const result = await fn();
    if (result) return result;
    await delay(250);
  }
  throw Error("Timed out waiting for UI");
}
async function runSmoke() {
  const assert = require("node:assert/strict");
  const output = testOutput;
  fs.mkdirSync(output, { recursive: true });
  await until(() => ready && lastFrame);
  await until(() => window.webContents.executeJavaScript('document.querySelector("#status").hidden'));
  await delay(1500);
  let state = await inspect();
  assert.equal(state.depth, 0);
  assert.equal(state.stones.length, 0);
  assert.equal(state.board.length, 361);
  const [x, y] = state.board[3 * 19 + 3];
  // Real Electron mouse events, through the canvas and bridge, to Kivy.
  const dimensions = await window.webContents.executeJavaScript(
    "({width:innerWidth,height:innerHeight})",
  );
  const point = {
    x: Math.round((x / state.size[0]) * dimensions.width),
    y: Math.round((1 - y / state.size[1]) * dimensions.height),
  };
  window.webContents.sendInputEvent({ type: "mouseMove", ...point });
  window.webContents.sendInputEvent({
    type: "mouseDown",
    button: "left",
    clickCount: 1,
    ...point,
  });
  window.webContents.sendInputEvent({
    type: "mouseUp",
    button: "left",
    clickCount: 1,
    ...point,
  });
  await until(async () => (await inspect()).depth === 1);
  // Real engine results must arrive, not mock recommendations.
  state = await until(async () => {
    const s = await inspect();
    return s.analysis?.root?.visits > 0 && s;
  }, 90000);
  const engineVisits = state.analysis.root.visits;
  fs.writeFileSync(
    path.join(output, "board.png"),
    (await window.webContents.capturePage()).toPNG(),
  );
  action("undo", [1]);
  await until(async () => (await inspect()).depth === 0);
  action("redo", [1]);
  await until(async () => (await inspect()).depth === 1);
  action("new-game-popup");
  await until(async () => (await inspect()).popup);
  await delay(300);
  fs.writeFileSync(
    path.join(output, "new-game.png"),
    (await window.webContents.capturePage()).toPNG(),
  );
  key("escape");
  await until(async () => !(await inspect()).popup);
  // Load a game with a variation; exercise parsing, navigation and analysis.
  const sgf = path.join(userData, "smoke.sgf");
  fs.writeFileSync(
    sgf,
    "(;GM[1]FF[4]SZ[19]PB[Electron Black]PW[Electron White];B[dd](;W[pp])(;W[qq]))",
  );
  send({ type: "open", path: sgf });
  await delay(1000);
  action("redo", [9999]);
  await until(async () => (await inspect()).depth === 2);
  await until(() => recentGames.paths[0] === sgf);
  const recentMenu = Menu.getApplicationMenu().items.find(item => item.label === "File")
    .submenu.items.find(item => item.label === "Open Recent");
  assert.ok(recentMenu.submenu.items[0].label.includes("smoke.sgf"));
  recentMenu.submenu.items[0].click();
  await until(async () => (await inspect()).depth === 0);
  action("redo", [9999]);
  await until(async () => (await inspect()).depth === 2);
  assert.equal(recentGames.paths.filter(file => file === sgf).length, 1);
  assert.deepEqual(new RecentGames(path.join(userData, "recent-games.json")).paths, recentGames.paths);
  action("ai-move");
  await until(async () => (await inspect()).depth === 3, 90000);
  state = await inspect();
  const tabPoint = {
    x: Math.round((state.notesTab[0] / state.size[0]) * dimensions.width),
    y: Math.round((1 - state.notesTab[1] / state.size[1]) * dimensions.height),
  };
  window.webContents.sendInputEvent({
    type: "mouseDown",
    button: "left",
    clickCount: 1,
    ...tabPoint,
  });
  window.webContents.sendInputEvent({
    type: "mouseUp",
    button: "left",
    clickCount: 1,
    ...tabPoint,
  });
  await delay(400);
  state = await inspect();
  const [nx, ny, nw, nh] = state.noteBounds;
  const notePoint = {
    x: Math.round(((nx + nw / 2) / state.size[0]) * dimensions.width),
    y: Math.round((1 - (ny + nh / 2) / state.size[1]) * dimensions.height),
  };
  window.webContents.sendInputEvent({
    type: "mouseDown",
    button: "left",
    clickCount: 1,
    ...notePoint,
  });
  window.webContents.sendInputEvent({
    type: "mouseUp",
    button: "left",
    clickCount: 1,
    ...notePoint,
  });
  await delay(300);
  window.focus();
  window.webContents.focus();
  window.webContents.sendInputEvent({ type: "keyDown", keyCode: "A" });
  window.webContents.sendInputEvent({ type: "keyUp", keyCode: "A" });
  await until(async () => (await inspect()).note.toLowerCase().includes("a"));
  action("save-game");
  await until(() => fs.readFileSync(sgf, "utf8").includes("C["));
  key("escape");
  key("f8");
  await until(async () => (await inspect()).popup);
  await delay(300);
  fs.writeFileSync(
    path.join(output, "settings.png"),
    (await window.webContents.capturePage()).toPNG(),
  );
  key("escape");
  await until(async () => !(await inspect()).popup);
  window.setContentSize(1100, 800);
  await delay(700);
  state = await inspect();
  state = await until(async () => {
    const current = await inspect();
    return (
      current.logicalSize[0] === 1100 &&
      current.logicalSize[1] === 800 &&
      current
    );
  });
  assert.equal(state.logicalSize[0], 1100);
  assert.equal(state.logicalSize[1], 800);
  fs.writeFileSync(
    path.join(output, "loaded.png"),
    (await window.webContents.capturePage()).toPNG(),
  );
  fs.writeFileSync(
    path.join(output, "result.json"),
    JSON.stringify(
      { passed: true, engineVisits, userData, packaged: app.isPackaged },
      null,
      2,
    ),
  );
  console.log("ELECTRON SMOKE PASSED", output);
  app.quit();
}

async function runRestoreSmoke() {
  const assert = require("node:assert/strict");
  const saved = JSON.parse(
    fs.readFileSync(path.join(userData, "session.json"), "utf8"),
  );
  await until(() => ready && lastFrame);
  await until(() => window.webContents.executeJavaScript('document.querySelector("#status").hidden'));
  await delay(2500);
  const state = await inspect();
  assert.equal(state.restored, true);
  assert.equal(state.nodeCount, saved.game.nodes.length);
  assert.deepEqual(
    state.analysis,
    saved.game.nodes[saved.game.current_node].analysis,
  );
  assert.equal(state.note, saved.game.nodes[saved.game.current_node].note);
  assert.equal(
    state.queryCounter,
    0,
    "Cached session must reopen with zero analysis requests",
  );
  assert.equal(state.selectedMode, "analyze");
  fs.writeFileSync(
    path.join(testOutput, "restored.png"),
    (await window.webContents.capturePage()).toPNG(),
  );
  console.log(
    "SESSION RESTORE PASSED: fresh process, exact cached analysis, notes, variations, zero reanalysis",
  );
  app.quit();
}
