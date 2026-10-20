const fs = require('node:fs');
const path = require('node:path');

class RecentGames {
  constructor(file, limit = 12) {
    this.file = file;
    this.limit = limit;
    this.paths = [];
    try {
      const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
      if (Array.isArray(saved)) this.paths = [...new Set(saved.filter(p =>
        typeof p === 'string' && path.isAbsolute(p) && /\.(sgf|ngf|gib)$/i.test(p)
      ))].slice(0, limit);
    } catch {}
  }
  save() {
    const temp = this.file + '.tmp';
    fs.writeFileSync(temp, JSON.stringify(this.paths, null, 2));
    fs.renameSync(temp, this.file);
  }
  add(file) {
    if (typeof file !== 'string' || !path.isAbsolute(file) || !/\.(sgf|ngf|gib)$/i.test(file)) return false;
    const normalized = path.normalize(file);
    if (this.paths[0] === normalized) return false;
    this.paths = [normalized, ...this.paths.filter(p => p !== normalized)].slice(0, this.limit);
    this.save();
    return true;
  }
  remove(file) {
    this.paths = this.paths.filter(p => p !== file);
    this.save();
  }
  clear() { this.paths = []; this.save(); }
}
module.exports = { RecentGames };
