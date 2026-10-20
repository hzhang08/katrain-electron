const { contextBridge, ipcRenderer, webUtils } = require("electron");
contextBridge.exposeInMainWorld("katrain", {
  input: (data) => ipcRenderer.send("input", data),
  onHost: (callback) =>
    ipcRenderer.on("host", (_event, data) => callback(data)),
  restart: () => ipcRenderer.invoke("recover"),
  open: () => ipcRenderer.invoke("open"),
  drop: (files) =>
    ipcRenderer.invoke(
      "drop",
      Array.from(files, (file) => webUtils.getPathForFile(file)),
    ),
});
