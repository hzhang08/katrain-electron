const canvas = document.querySelector("#board"),
  context = canvas.getContext("2d", { alpha: false });
const status = document.querySelector("#status"),
  message = document.querySelector("#message"),
  ime = document.querySelector("#ime");
let composing = false,
  lastDown = { time: 0, x: 0, y: 0 };
window.katrain.onHost(async (event) => {
  if (event.type === "frame") {
    try {
      const image = new Image();
      image.src = `data:image/png;base64,${event.png}`;
      await image.decode();
      if (canvas.width !== event.width || canvas.height !== event.height) {
        canvas.width = event.width;
        canvas.height = event.height;
      }
      context.drawImage(image, 0, 0);
      status.hidden = true;
    } finally {
      window.katrain.input({ type: "ack" });
    }
  } else if (event.type === "ready") {
    resize();
    ime.focus();
  } else if (event.type === "fatal") {
    status.hidden = false;
    message.textContent = event.message;
    document.querySelector("#retry").hidden = false;
  }
});
const modifiers = (e) =>
  [
    e.shiftKey && "shift",
    e.ctrlKey && "ctrl",
    e.altKey && "alt",
    e.metaKey && "meta",
  ].filter(Boolean);
function pointer(type, e, extra = {}) {
  const rect = canvas.getBoundingClientRect();
  window.katrain.input({
    type,
    x: (e.clientX - rect.left) / rect.width,
    y: (e.clientY - rect.top) / rect.height,
    id: e.pointerId || 1,
    modifiers: modifiers(e),
    ...extra,
  });
}
canvas.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  ime.focus();
  canvas.setPointerCapture(e.pointerId);
  const double =
    performance.now() - lastDown.time < 300 &&
    Math.hypot(e.clientX - lastDown.x, e.clientY - lastDown.y) < 5;
  lastDown = { time: performance.now(), x: e.clientX, y: e.clientY };
  pointer("down", e, {
    button: ["left", "middle", "right"][e.button] || "left",
    double,
  });
});
canvas.addEventListener("pointermove", (e) => pointer("move", e));
canvas.addEventListener("pointerup", (e) => pointer("up", e));
canvas.addEventListener("pointercancel", () =>
  window.katrain.input({ type: "blur" }),
);
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    pointer("wheel", e, { button: e.deltaY > 0 ? "scrolldown" : "scrollup" });
  },
  { passive: false },
);
canvas.addEventListener("contextmenu", (e) => e.preventDefault());
const keys = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
  Enter: "enter",
  Escape: "escape",
  " ": "spacebar",
  Backspace: "backspace",
  Delete: "delete",
  Tab: "tab",
  Home: "home",
  End: "end",
  PageUp: "pageup",
  PageDown: "pagedown",
  Shift: "shift",
  Control: "ctrl",
  Alt: "alt",
  Meta: "meta",
};
for (const type of ["keydown", "keyup"])
  document.addEventListener(type, (e) => {
    if (composing || e.isComposing) return;
    const key = keys[e.key] || e.key.toLowerCase();
    window.katrain.input({
      type,
      key,
      modifiers: modifiers(e),
      text: e.key.length === 1 ? e.key : "",
    });
    if (type === "keydown" && e.key.length === 1 && !e.metaKey && !e.ctrlKey)
      window.katrain.input({ type: "text", text: e.key });
    if (!e.isComposing) e.preventDefault();
  });
ime.addEventListener("compositionstart", () => (composing = true));
ime.addEventListener("compositionend", (e) => {
  composing = false;
  window.katrain.input({ type: "text", text: e.data });
  ime.value = "";
});
window.addEventListener("blur", () => window.katrain.input({ type: "blur" }));
window.addEventListener("focus", () => ime.focus());
function resize() {
  window.katrain.input({
    type: "resize",
    width: innerWidth,
    height: innerHeight,
  });
}
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resize, 80);
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  window.katrain.drop(e.dataTransfer.files);
});
document.querySelector("#retry").addEventListener("click", () => {
  message.textContent = "Restarting KaTrain…";
  document.querySelector("#retry").hidden = true;
  window.katrain.restart();
});
