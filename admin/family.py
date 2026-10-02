#!/usr/bin/env python3
"""Factory Family admin backend — local only, stdlib only.
Usage: python3 family.py  (serves http://127.0.0.1:8471)
Yules's private floor: see every member, read the log, run the house.
"""
import http.server, json, os, sqlite3, urllib.parse, subprocess, tempfile, zipfile, shutil
from datetime import datetime

try:
    from brain import ask as brain_ask
except ImportError:
    brain_ask = None

HOME = os.path.expanduser("~")
# BASE resolves to the family project root no matter where it's cloned
BASE = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SOULS = os.path.join(BASE, "souls")
DB = os.path.join(HOME, ".factory", "family.db")
PORT = 8471

MEMBERS = ["wick", "foreman", "archivist", "scout", "tinker", "guardian", "greeter"]

def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS log
                 (id INTEGER PRIMARY KEY, ts TEXT, member TEXT, kind TEXT, text TEXT)""")
    return c

def log(member, kind, text):
    c = db()
    c.execute("INSERT INTO log (ts, member, kind, text) VALUES (?,?,?,?)",
              (datetime.now().isoformat(timespec="seconds"), member, kind, text))
    c.commit(); c.close()

def read_soul(name):
    p = os.path.join(SOULS, name + ".md")
    return open(p).read() if os.path.exists(p) else ""

NETLIFY_CLI = os.path.join(HOME, "workspace", "skills", "netlify", "bin", "netlify")
GITHUB_CLI = "/opt/hatch/bin/github"
WORKSPACE = os.path.join(HOME, "workspace")

def safe_path(p):
    """Only allow paths inside the user's home dir."""
    full = os.path.realpath(os.path.join(HOME, p.lstrip("/")))
    if not full.startswith(os.path.realpath(HOME) + os.sep):
        raise ValueError("outside home dir")
    return full

def tinker_deploy_netlify(site_name, src):
    """Zip src and deploy to Netlify as site_name. Returns (ok, message)."""
    src = safe_path(src)
    if not os.path.exists(src):
        return False, "source not found"
    tmp = tempfile.mkdtemp()
    zpath = os.path.join(tmp, "site.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.isdir(src):
            for root, _, files in os.walk(src):
                for f in files:
                    fp = os.path.join(root, f)
                    z.write(fp, os.path.relpath(fp, src))
        else:
            z.write(src, os.path.basename(src))
    try:
        r = subprocess.run([NETLIFY_CLI, "deploy", site_name, zpath],
                           capture_output=True, text=True, timeout=180)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            return True, out.strip()[:500]
        return False, out.strip()[:500]
    except FileNotFoundError:
        return False, "netlify CLI not installed on this machine"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def tinker_ship_github(repo, src, message="ship it via Tinker"):
    """Push files from src to owner/repo on GitHub. Returns (ok, message)."""
    src = safe_path(src)
    if not os.path.exists(src):
        return False, "source not found"
    files = []
    if os.path.isdir(src):
        for root, _, fs in os.walk(src):
            for f in fs:
                fp = os.path.join(root, f)
                with open(fp, "rb") as fh:
                    content = fh.read()
                try:
                    files.append({"path": os.path.relpath(fp, src),
                                  "content": content.decode("utf-8")})
                except UnicodeDecodeError:
                    continue  # skip binaries for now
    else:
        with open(src, encoding="utf-8") as fh:
            files.append({"path": os.path.basename(src), "content": fh.read()})
    if "/" not in repo:
        return False, "repo must be owner/name"
    owner, name = repo.split("/", 1)
    payload = {"owner": owner, "repo": name, "branch": "main",
               "message": message, "files": files}
    try:
        r = subprocess.run([GITHUB_CLI, "call-tool", "--name", "push_files",
                            "--arguments-json", json.dumps(payload)],
                           capture_output=True, text=True, timeout=180)
        out = (r.stdout or "") + (r.stderr or "")
        ok = '"ok": true' in out or '"ok":true' in out
        return ok, out.strip()[:500]
    except Exception as e:
        return False, str(e)[:200]


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/floor":
            return self._send(200, ADMIN_HTML, "text/html")
        if self.path == "/greeter":
            p = os.path.join(BASE, "public", "greeter.html")
            if os.path.exists(p):
                return self._send(200, open(p).read(), "text/html")
            return self._send(404, "greeter not built yet", "text/plain")
        if self.path in ("/", "/den"):
            p = os.path.join(BASE, "public", "den.html")
            if os.path.exists(p):
                html = open(p).read()
                # Bake portraits server-side: no browser JS chain to break.
                try:
                    import re as _re
                    famimg = {}
                    pub = os.path.join(BASE, "public")
                    for n in range(1, 7):
                        fp = os.path.join(pub, f"img{n}.js")
                        if os.path.exists(fp):
                            for m in _re.finditer(r'window\.FAMIMG\["([^"]+)"\] = "(data:image/png;base64,[^"]+)"', open(fp).read()):
                                famimg[m.group(1)] = m.group(2)
                    def _fill(mo):
                        return f'<img src="{famimg[mo.group(1)]}"' if mo.group(1) in famimg else "<img"
                    html = _re.sub(r'<img data-fam="([^"]+)" src=""', _fill, html)
                except Exception:
                    pass
                return self._send(200, html, "text/html")
            return self._send(404, "den not built yet", "text/plain")
        if self.path.startswith("/img") and self.path.endswith(".js"):
            name = os.path.basename(self.path)
            p = os.path.realpath(os.path.join(BASE, "public", name))
            if not p.startswith(os.path.realpath(os.path.join(BASE, "public")) + os.sep):
                return self._send(404, "not found", "text/plain")
            if os.path.exists(p):
                return self._send(200, open(p).read(), "application/javascript")
            return self._send(404, "not found", "text/plain")
        if self.path.startswith("/creatures/"):
            name = os.path.basename(self.path)
            if not (name.endswith(".webp") or name.endswith(".png")):
                return self._send(404, "not found", "text/plain")
            p = os.path.realpath(os.path.join(BASE, "creatures", name))
            if not p.startswith(os.path.realpath(os.path.join(BASE, "creatures")) + os.sep):
                return self._send(404, "not found", "text/plain")
            if os.path.exists(p):
                ctype = "image/png" if name.endswith(".png") else "image/webp"
                return self._send(200, open(p, "rb").read(), ctype)
            return self._send(404, "not found", "text/plain")
        if self.path == "/api/heartbeat":
            layer = "keyword"
            try:
                import brain as _b
                if _b.gemini_key():
                    layer = "gemini"
                else:
                    import urllib.request as _u
                    _u.urlopen("http://127.0.0.1:11434/api/tags", timeout=2).read()
                    layer = "llama"
            except Exception:
                pass
            return self._send(200, json.dumps({
                "ok": True, "brain": layer,
                "ts": datetime.now().isoformat(timespec="seconds")}))
        if self.path == "/api/members":
            ms = [{"name": m, "soul": read_soul(m)} for m in MEMBERS]
            return self._send(200, json.dumps(ms))
        if self.path == "/api/log":
            c = db()
            rows = c.execute("SELECT ts, member, kind, text FROM log ORDER BY id DESC LIMIT 200").fetchall()
            c.close()
            return self._send(200, json.dumps(
                [{"ts": r[0], "member": r[1], "kind": r[2], "text": r[3]} for r in rows]))
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/note":
            log(data.get("member", "wick"), "note", data.get("text", ""))
            return self._send(200, '{"ok": true}')
        if self.path == "/api/chat":
            q = data.get("text", data.get("q", "")).strip()
            if not q:
                return self._send(200, json.dumps({"answer": "Say something first — I'm listening.", "layer": "none"}))
            if brain_ask:
                answer, layer = brain_ask(q)
            else:
                answer, layer = "The brain isn't wired up yet.", "none"
            log("greeter", f"chat:{layer}", q[:120])
            return self._send(200, json.dumps({"answer": answer, "reply": answer, "layer": layer}))
        if self.path == "/api/tinker/deploy":
            # Tinker: deploy straight from the family floor.
            # {target: "netlify"|"github", site|repo, src}
            try:
                target = data.get("target", "")
                src = data.get("src", "")
                if target == "netlify":
                    ok, msg = tinker_deploy_netlify(data.get("site", ""), src)
                    log("tinker", "deploy:netlify", f"{data.get('site')}: {'ok' if ok else 'FAILED'}")
                elif target == "github":
                    ok, msg = tinker_ship_github(data.get("repo", ""), src)
                    log("tinker", "deploy:github", f"{data.get('repo')}: {'ok' if ok else 'FAILED'}")
                else:
                    return self._send(200, json.dumps({"ok": False, "message": "target must be netlify or github"}))
                return self._send(200, json.dumps({"ok": ok, "message": msg}))
            except ValueError as e:
                return self._send(200, json.dumps({"ok": False, "message": str(e)}))
        return self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass

ADMIN_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory Floor — Admin</title>
<style>
body{background:#0a0a0a;color:#33ff66;font-family:monospace;max-width:900px;margin:0 auto;padding:20px}
h1{font-size:1.4em} .card{border:1px solid #1f5c2e;padding:12px;margin:10px 0;border-radius:6px}
.mname{color:#9f9;font-weight:bold} pre{white-space:pre-wrap;color:#8a8;font-size:.85em}
.logline{border-bottom:1px dotted #1f5c2e;padding:4px 0;font-size:.85em}
input,button{background:#111;color:#3f6;border:1px solid #1f5c2e;padding:8px;font-family:monospace;border-radius:4px}
</style></head><body>
<h1>❯ y_ · factory floor — admin</h1>
<p>local only. the family, the souls, the log.</p>
<script src="/img1.js"></script>
<script src="/img2.js"></script>
<script src="/img3.js"></script>
<script src="/img4.js"></script>
<script src="/img5.js"></script>
<script src="/img6.js"></script>
<h2>members</h2><div id="members"></div>
<h2>log</h2><div id="log"></div>
<h2>tinker — ship it</h2>
<div class="card">
<select id="dtarget"><option value="netlify">netlify</option><option value="github">github</option></select>
<input id="dname" placeholder="site name (netlify) or owner/repo (github)" style="width:40%">
<input id="dsrc" placeholder="path from home, e.g. family/public/den.html" style="width:35%">
<button onclick="deploy()">deploy</button>
<div id="dout" style="margin-top:8px;font-size:.85em"></div></div>
<h2>note</h2>
<input id="note" placeholder="write to the family log…" style="width:70%">
<button onclick="sendNote()">log it</button>
<script>
async function load(){
 const m=await(await fetch('/api/members')).json();
 document.getElementById('members').innerHTML=m.map(x=>{
  const img=(window.FAMIMG&&window.FAMIMG[x.name])?`<img src="${window.FAMIMG[x.name]}" alt="${x.name}" style="width:72px;float:right;margin:0 0 8px 12px;filter:drop-shadow(0 4px 10px rgba(0,0,0,.5))">`:'';
  return `<div class="card"><span class="mname">${x.name}</span>${img}<pre>${x.soul}</pre><div style="clear:both"></div></div>`;
 }).join('');
 const l=await(await fetch('/api/log')).json();
 document.getElementById('log').innerHTML=l.map(x=>
  `<div class="logline">[${x.ts}] <b>${x.member}</b> (${x.kind}): ${x.text}</div>`).join('')||'<p>quiet on the floor.</p>';
}
async function sendNote(){
 const t=document.getElementById('note').value; if(!t)return;
 await fetch('/api/note',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({member:'yules',text:t})});
 document.getElementById('note').value=''; load();
}
async function deploy(){
 const t=document.getElementById('dtarget').value;
 const payload={target:t,src:document.getElementById('dsrc').value};
 if(t==='netlify')payload.site=document.getElementById('dname').value;
 else payload.repo=document.getElementById('dname').value;
 document.getElementById('dout').textContent='tinker is working…';
 const r=await(await fetch('/api/tinker/deploy',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
 document.getElementById('dout').textContent=(r.ok?'shipped: ':'failed: ')+r.message;
 load();
}
load(); setInterval(load,15000);
</script></body></html>"""

if __name__ == "__main__":
    log("foreman", "shift", "floor opened")
    print(f"factory floor admin on http://127.0.0.1:{PORT}  (local only)")
    http.server.HTTPServer(("127.0.0.1", PORT), H).serve_forever()
