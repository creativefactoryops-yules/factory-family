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

CHAT_HIST = []

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
        if self.path == "/":
            return self._send(200, ADMIN_HTML, "text/html")
        if self.path == "/greeter":
            p = os.path.join(BASE, "public", "greeter.html")
            if os.path.exists(p):
                return self._send(200, open(p).read(), "text/html")
            return self._send(404, "greeter not built yet", "text/plain")
        if self.path == "/den":
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
                return self._send(200, json.dumps({"replies": [["greeter", "Say something first — I'm listening."]], "layer": "none"}))
            souls = {m: read_soul(m) for m in MEMBERS}
            hist = CHAT_HIST[-10:]
            try:
                import brain as _b
                replies = _b.team_ask(q, souls, hist)
                layer = "gemini" if _b.gemini_key() else "local"
            except Exception:
                replies = [("greeter", "The brain isn't wired up yet.")]
                layer = "none"
            CHAT_HIST.append(f"Yules: {q}")
            for m, r in replies:
                CHAT_HIST.append(f"{m}: {r[:200]}")
                log(m, f"chat:{layer}", q[:120])
            return self._send(200, json.dumps({"replies": replies, "layer": layer}))
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
<title>❯ y_ · factory floor</title>
<style>
:root{--grn:#33ff66;--dim:#1f5c2e;--amb:#ffb347;--txt:#c9e8c9}
body{background:#070707;color:var(--grn);font-family:ui-monospace,Menlo,monospace;max-width:860px;margin:0 auto;padding:16px;font-size:15px}
h1{font-size:1.25em;margin:.4em 0}.sub{color:#6a8a6a;font-size:.85em}
#beat{color:var(--amb);font-size:.85em;margin:8px 0}
.card{border:1px solid var(--dim);padding:10px 12px;margin:8px 0;border-radius:6px;background:#0b0f0b}
.sec{color:var(--amb);margin:1.2em 0 .4em;font-weight:bold}
#chat{height:46vh;min-height:280px;overflow-y:auto;border:1px solid var(--dim);border-radius:6px;padding:10px;background:#050705}
#chat .sys{color:#5a7a5a;font-style:italic}
#chat .you{color:#fff;margin:8px 0}
#chat .you b{color:var(--amb)}
#chat .msg{margin:8px 0}
#chat .msg b{color:var(--grn)}
#chat .typing{color:#5a7a5a;animation:blink 1s infinite}
@keyframes blink{50%{opacity:.3}}
.row{display:flex;gap:8px;margin-top:8px}
#qin{flex:1;background:#0b0f0b;color:var(--txt);border:1px solid var(--dim);padding:10px;font-family:inherit;font-size:1em;border-radius:6px}
button{background:#0e1a0e;color:var(--grn);border:1px solid var(--dim);padding:10px 16px;font-family:inherit;border-radius:6px;cursor:pointer;font-size:1em}
button:active{background:#1a2e1a}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.chips button{padding:4px 10px;font-size:.8em}
.logline{border-bottom:1px dotted var(--dim);padding:3px 0;font-size:.82em;color:#8acb8a}
pre{white-space:pre-wrap;color:#8acb8a;font-size:.82em}
details{margin:8px 0}summary{cursor:pointer;color:var(--amb)}
.note{width:100%;box-sizing:border-box;background:#0b0f0b;color:var(--txt);border:1px solid var(--dim);padding:8px;font-family:inherit;border-radius:6px}
</style></head><body>
<h1>\u276f y_ \u00b7 factory floor</h1>
<p class="sub">local only \u00b7 the family, live \u00b7 <a href="/den" style="color:var(--amb)">the den</a></p>
<div id="beat">\u276f connecting\u2026</div>

<div class="sec">\u276f talk to the team</div>
<div class="chips">
<button onclick="ask('@foreman ')">@foreman</button>
<button onclick="ask('@tinker ')">@tinker</button>
<button onclick="ask('@scout ')">@scout</button>
<button onclick="ask('@archivist ')">@archivist</button>
<button onclick="ask('@guardian ')">@guardian</button>
<button onclick="ask('@wick ')">@wick</button>
<button onclick="ask('hey everyone, ')">@everyone</button>
</div>
<div id="chat"><div class="sys">\u276f floor online. type @name to talk to someone, or @everyone for the whole team.</div></div>
<div class="row"><input id="qin" placeholder="say something to the family\u2026" autocomplete="off"><button onclick="send()">send</button></div>

<div class="sec">\u276f the roster</div>
<div id="members"></div>

<details><summary>\u276f heartbeat log</summary><div id="log"></div></details>

<div class="sec">\u276f tinker \u2014 ship it</div>
<div class="card">
<select id="dtarget" style="background:#111;color:#3f6;border:1px solid var(--dim);padding:8px;font-family:inherit;border-radius:4px"><option value="netlify">netlify</option><option value="github">github</option></select>
<input id="dname" placeholder="site or owner/repo" class="note" style="width:38%">
<input id="dsrc" placeholder="path from home" class="note" style="width:38%">
<button onclick="deploy()">deploy</button>
<div id="dout" style="margin-top:8px;font-size:.85em"></div></div>

<div class="sec">\u276f note to the log</div>
<div class="row"><input id="note" class="note" placeholder="write to the family log\u2026"><button onclick="sendNote()">log it</button></div>

<script>
const chat=document.getElementById('chat'),qin=document.getElementById('qin');
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function add(html){chat.innerHTML+=html;chat.scrollTop=chat.scrollHeight;}
function ask(prefix){qin.value=prefix;qin.focus();}
qin.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
let busy=false;
async function send(){
 const q=qin.value.trim();if(!q||busy)return;busy=true;qin.value='';
 add('<div class="you"><b>yules:</b> '+esc(q)+'</div>');
 add('<div class="typing" id="ty">\u276f the team is thinking\u2026</div>');
 try{
  const r=await(await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:q})})).json();
  document.getElementById('ty').remove();
  (r.replies||[]).forEach(([m,t])=>add('<div class="msg"><b>'+esc(m)+':</b> '+esc(t)+'</div>'));
 }catch(e){const t=document.getElementById('ty');if(t)t.remove();add('<div class="sys">\u276f static. the floor is quiet \u2014 try again.</div>');}
 busy=false;loadLog();
}
async function beat(){
 try{const b=await(await fetch('/api/heartbeat')).json();
  document.getElementById('beat').textContent='\u276f floor is '+(b.ok?'live':'down')+' \u00b7 brain: '+b.brain+' \u00b7 '+b.ts;}catch(e){}
}
async function loadMembers(){
 const m=await(await fetch('/api/members')).json();
 document.getElementById('members').innerHTML=m.map(x=>'<div class="card"><b style="color:var(--grn)">'+esc(x.name)+'</b><pre>'+esc(x.soul.slice(0,300))+'</pre></div>').join('');
}
async function loadLog(){
 const l=await(await fetch('/api/log')).json();
 document.getElementById('log').innerHTML=l.slice(-30).reverse().map(x=>'<div class="logline">['+x.ts+'] <b>'+x.member+'</b> ('+x.kind+'): '+esc(x.text)+'</div>').join('')||'<p>quiet on the floor.</p>';
}
async function sendNote(){
 const t=document.getElementById('note').value;if(!t)return;
 await fetch('/api/note',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member:'yules',text:t})});
 document.getElementById('note').value='';loadLog();
}
async function deploy(){
 const t=document.getElementById('dtarget').value;
 const p={target:t,src:document.getElementById('dsrc').value};
 if(t==='netlify')p.site=document.getElementById('dname').value;else p.repo=document.getElementById('dname').value;
 document.getElementById('dout').textContent='tinker is working\u2026';
 const r=await(await fetch('/api/tinker/deploy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)})).json();
 document.getElementById('dout').textContent=JSON.stringify(r).slice(0,300);loadLog();
}
beat();setInterval(beat,15000);loadMembers();loadLog();
</script></body></html>"""

if __name__ == "__main__":
    log("foreman", "shift", "floor opened")
    print(f"factory floor admin on http://127.0.0.1:{PORT}  (local only)")
    http.server.HTTPServer(("127.0.0.1", PORT), H).serve_forever()
