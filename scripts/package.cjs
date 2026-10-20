const path = require("node:path");
const fs = require("node:fs");
const { execFileSync } = require("node:child_process");
(async () => {
  const { packager } = await import("@electron/packager");
  const root = path.resolve(__dirname, "..");
  const resources = path.join(root, "build/resources");
  if (!fs.existsSync(path.join(resources, "backend/katrain-host")))
    throw Error("Run npm run build:backend first.");
  const apps = await packager({
    dir: root,
    out: path.join(root, "release"),
    name: "KaTrain Electron",
    platform: "darwin",
    arch: "arm64",
    appBundleId: "org.katrain.electron",
    appVersion: "1.0.0",
    buildVersion: "1.0.1",
    overwrite: true,
    asar: true,
    icon: path.join(root, "assets/icon.icns"),
    ignore: [
      /^\/build(?:\/|$)/,
      /^\/\.venv(?:\/|$)/,
      /^\/\.git(?:\/|$)/,
      /^\/backend(?:\/|$)/,
      /^\/scripts(?:\/|$)/,
      /^\/tests(?:\/|$)/,
      /^\/test-output(?:\/|$)/,
      /^\/release(?:\/|$)/,
    ],
    extendInfo: {
      NSHighResolutionCapable: true,
      CFBundleDocumentTypes: [
        {
          CFBundleTypeName: "Go game record",
          CFBundleTypeExtensions: ["sgf", "ngf", "gib"],
          CFBundleTypeRole: "Editor",
          LSHandlerRank: "Alternate",
        },
      ],
    },
  });
  for (const output of apps) {
    const app = path.join(output, "KaTrain Electron.app");
    for (const name of ["backend", "engine", "licenses", "build-info.json"])
      fs.cpSync(
        path.join(resources, name),
        path.join(app, "Contents/Resources", name),
        { recursive: true, verbatimSymlinks: true },
      );
    execFileSync("codesign", ["--force", "--deep", "--sign", "-", app], {
      stdio: "inherit",
    });
    const install = path.join(
      require("node:os").homedir(),
      "Applications/KaTrain Electron.app",
    );
    // Update only this separate app. Existing KaTrain and Workspace stay intact.
    if (process.env.KATRAIN_INSTALL === "1") {
      if (fs.existsSync(install)) fs.rmSync(install, { recursive: true });
      execFileSync("ditto", [app, install]);
      console.log("Installed:", install);
    }
    const zip = path.join(root, "release/KaTrain-Electron-mac-arm64.zip");
    execFileSync("ditto", [
      "-c",
      "-k",
      "--sequesterRsrc",
      "--keepParent",
      app,
      zip,
    ]);
    console.log("Packaged:", zip);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
