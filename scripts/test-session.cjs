// End-to-end persistence check using two independent Electron processes.
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const executable = process.env.ELECTRON_APP_PATH || require("electron");
const prefix = process.env.ELECTRON_APP_PATH ? [] : [root];
const output = process.env.ELECTRON_APP_PATH
  ? path.join(os.tmpdir(), "katrain-electron-packaged-smoke")
  : path.join(root, "test-output");
function run(args) {
  const result = spawnSync(executable, [...prefix, ...args], {
    stdio: "inherit",
    timeout: 180000,
  });
  if (result.error) throw result.error;
  if (result.status !== 0)
    throw Error(`Electron check exited with ${result.status}`);
}
run(["--smoke"]);
const result = JSON.parse(
  fs.readFileSync(path.join(output, "result.json"), "utf8"),
);
const snapshot = path.join(result.userData, "session.json");
if (!fs.existsSync(snapshot))
  throw Error("Normal quit did not save a snapshot");
const saved = JSON.parse(fs.readFileSync(snapshot, "utf8"));
if (!saved.game.nodes[saved.game.current_node].analysis.root)
  throw Error("No cached analysis saved");
// Prove restoration does not depend on the source game file.
fs.unlinkSync(path.join(result.userData, "smoke.sgf"));
run([`--restore-smoke=${result.userData}`]);
console.log("SESSION END-TO-END PASSED");
