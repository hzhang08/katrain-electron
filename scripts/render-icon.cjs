// Run with: node_modules/.bin/electron scripts/render-icon.cjs
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
app.whenReady().then(async () => {
  const assets = path.resolve(__dirname, '../assets');
  const window = new BrowserWindow({ width:1024, height:1024, useContentSize:true, show:false, transparent:true, frame:false, webPreferences:{sandbox:true,offscreen:true} });
  const svg = fs.readFileSync(path.join(assets, 'icon.svg'), 'utf8');
  await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<html style="margin:0;background:transparent"><body style="margin:0">${svg}</body></html>`));
  const picture = await window.webContents.capturePage();
  fs.writeFileSync(path.join(assets, 'icon.png'), picture.resize({width:1024,height:1024}).toPNG());
  const iconset = path.join(assets, 'icon.iconset');
  fs.mkdirSync(iconset, {recursive:true});
  for(const size of [16,32,128,256,512]) for(const scale of [1,2]) {
    const filename=`icon_${size}x${size}${scale===2?'@2x':''}.png`;
    fs.writeFileSync(path.join(iconset,filename),picture.resize({width:size*scale,height:size*scale}).toPNG());
  }
  execFileSync('iconutil',['-c','icns',iconset,'-o',path.join(assets,'icon.icns')]);
  fs.rmSync(iconset,{recursive:true});
  app.quit();
}).catch(error=>{console.error(error);app.exit(1);});
