"""Greeter brain — three layers, best to worst.
1. Gemini (online, smart) — key auto-loaded from ~/assistant-bot/.env (the working
   Telegram bot key — never asks Yules to retype it). Chains models on quota errors,
   with exponential backoff (1s, 2s, 4s) for 503/429, same as the Telegram bot.
2. Local Llama via Ollama   — needs ollama running; model via OLLAMA_MODEL env
3. Keyword brain             — never dies, always answers
Returns (answer, layer_name). Layer 1 failure falls through silently.
"""
import json, os, re, time, urllib.request, urllib.error


def _load_dotenv(path):
    """Stdlib .env parser — KEY=value, strips quotes, skips comments/blank lines."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                os.environ.setdefault(k, v)
    except OSError:
        pass


# Yules's Telegram assistant keeps its working Gemini key here — reuse it.
_load_dotenv(os.path.expanduser("~/assistant-bot/.env"))


def gemini_key():
    return os.environ.get("GEMINI_API_KEY", "")


def gemini_models():
    # GEMINI_MODEL (single, like the Telegram bot) wins; otherwise the chain.
    single = os.environ.get("GEMINI_MODEL", "").strip()
    if single:
        return [single]
    return [m.strip() for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.5-flash-lite,gemma-4-26b-a4b-it",
    ).split(",") if m.strip()]


OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b-instruct")

SYSTEM = (
    "You are the Greeter, the public soul of the --force ./buildyou factory family. "
    "ND-native, radically welcoming, endlessly patient. Rules: low overwhelm, "
    "explicit over implied, one thing at a time. Never assume what the visitor knows. "
    "If you don't know something, say so plainly and offer to find out — never fake an answer. "
    "Keep replies short, 2-4 sentences. Warm, direct, a little playful."
)


def _post(url, payload, timeout=25):
    r = urllib.request.Request(url, data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.load(resp), None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, str(e)


def gemini_ask(q):
    """Try each model in order; 503/429 gets exponential backoff (1s,2s,4s)."""
    key = gemini_key()
    if not key:
        return None
    for model in gemini_models():
        for wait in (1, 2, 4):
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            data, err = _post(url, {"system_instruction": {"parts": [{"text": SYSTEM}]},
                                    "contents": [{"parts": [{"text": q}]}]})
            if data:
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError, TypeError):
                    break  # malformed — try next model
            if err in (429, 503):
                time.sleep(wait)
                continue
            break  # other error (bad model name, auth) — next model
    return None


def llama_ask(q):
    d, _ = _post("http://127.0.0.1:11434/api/generate",
                 {"model": OLLAMA_MODEL, "prompt": f"{SYSTEM}\n\nVisitor: {q}\nGreeter:",
                  "stream": False}, timeout=60)
    if d:
        return (d.get("response") or "").strip()
    return None


KEYWORDS = [
    (r"^(hi|hello|hey|yo|sup)\b",
     "Hello, and welcome in. I'm the Greeter — the front door of this little kingdom. What's on your mind? One thing at a time, no rush."),
    (r"new here|just arrived|first time",
     "Wonderful — new faces are my favorite. Here's the tour in one line: this is a kind, ND-first corner of the internet. Ask me anything, build with me, or just look around. What brings you here today?"),
    (r"who (are|r) you|your name",
     "I'm the Greeter, one soul in the --force ./buildyou factory family. My whole job is making sure everyone who walks through this door feels welcome and un-lost."),
    (r"nd|neurodivergent|adhd|autis",
     "This place was built ND-first, not ND-accommodated. Low overwhelm, explicit over implied, one step at a time, no assumed knowledge, no shame for asking. If something here ever feels otherwise, tell me and I'll fix the wording."),
    (r"accessib",
     "Accessibility here isn't a feature list — it's the foundation. Bigger text toggle up top, calm mode, plain language, no time pressure. Tell me what you need and I'll adapt."),
    (r"build|make|create|project",
     "Love that energy. Tell me what you want to make — just the rough shape is fine — and we'll break it into small steps together. First step only, then the next."),
    (r"thank|thanks|thx",
     "Anytime. That's literally what I'm here for."),
    (r"bye|goodbye|see you",
     "See you soon. The door stays open."),
]


def keyword_ask(q):
    q = q.strip()
    for pat, ans in KEYWORDS:
        if re.search(pat, q, re.I):
            return ans
    return ("Good question — I don't have a real answer for that yet, and I'd rather say so "
            "than fake one. Want to tell me more about what you're after? We'll figure it out together.")


def ask(q):
    """Try each layer in order. Never raises on model failure."""
    for name, fn in (("gemini", gemini_ask), ("llama", llama_ask)):
        try:
            a = fn(q)
            if a:
                return a, name
        except Exception:
            continue
    return keyword_ask(q), "keyword"


# ---------- team chat ----------
from concurrent.futures import ThreadPoolExecutor

ROUTER = [
    ("tinker",    r"deploy|build|ship|netlify|vercel|github|push|site|app\b"),
    ("archivist", r"remember|recall|memory|log|note|history|earlier|before"),
    ("scout",     r"research|find out|verify|check|look up|search|is it true"),
    ("guardian",  r"safe|privacy|private|secur|leak|expos|permission"),
    ("foreman",   r"plan|organiz|steps|project|task|assign|status|stuck"),
    ("wick",      r"wick"),
    ("greeter",   r"^(hi|hello|hey|yo|sup)\b"),
]

def route(q):
    """Who should answer? Returns list of member names."""
    ql = q.lower()
    # explicit @-mentions win
    mentioned = [m for m in ("wick foreman archivist scout tinker guardian greeter".split())
                 if "@" + m in ql]
    if mentioned:
        return mentioned
    # "everyone / all of you / each of you" -> the whole team
    if re.search(r"\b(everyone|all of you|each of you|whole team|everybody|hey team|hi team|hello team)\b", ql):
        return ["wick", "foreman", "archivist", "scout", "tinker", "guardian", "greeter"]
    for member, pat in ROUTER:
        if re.search(pat, ql):
            return [member]
    return ["foreman"]  # default: the orchestrator triages


def member_ask(member, soul, history, q, model_offset=0):
    """One member answers in their own voice via Gemini.
    Tries the full model chain; model_offset spreads parallel members
    across different models so 7 simultaneous calls don't 429 one model."""
    key = gemini_key()
    if not key:
        return None
    models = gemini_models()
    models = models[model_offset:] + models[:model_offset]
    convo = "\n".join(history[-8:]) if history else ""
    prompt = (f"{soul}\n\nYou are {member}, one of Yules's factory family. "
              f"Reply as {member} in 2-3 sentences, in your voice. "
              f"Recent chat:\n{convo}\n\nYules: {q}\n{member}:")
    for model in models:
        for wait in (1, 2, 4):
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            data, err = _post(url, {"contents": [{"parts": [{"text": prompt}]}]})
            if data:
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError, TypeError) as e:
                    print(f"[brain] {member}: bad response shape: {e}", flush=True)
                    break
            if err in (429, 503):
                print(f"[brain] {member}: {model} got {err}, retry in {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"[brain] {member}: {model} failed: {err}", flush=True)
            break
    return None


def team_ask(q, souls, history):
    """One Gemini call speaks as the whole routed team — 1 API call no matter
    how many members answer, so the free tier never 429s."""
    members = route(q)
    key = gemini_key()
    if not key:
        return [(m, _offline_line(m, q)) for m in members]
    model = gemini_models()[0]
    soul_text = "\n\n".join(f"## {m}\n{souls.get(m, '')}" for m in members)
    convo = "\n".join(history[-8:]) if history else ""
    fmt = "\n".join(f"[{m}] <2-3 sentences as {m}>" for m in members)
    prompt = (
        f"You are the factory family, Yules's team of AI helpers. Their souls:\n\n"
        f"{soul_text}\n\nRecent chat:\n{convo}\n\nYules: {q}\n\n"
        f"Answer as EACH of these members: {', '.join(members)}. "
        f"Format exactly like this, one block per member:\n{fmt}\n"
        f"Keep every voice true to its soul. No extra commentary outside the blocks."
    )
    text = None
    for wait in (1, 2, 4, 8):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        data, err = _post(url, {"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        if data:
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                break
            except (KeyError, IndexError, TypeError) as e:
                print(f"[brain] team: bad response shape: {e}", flush=True)
                break
        if err in (429, 503):
            print(f"[brain] team: {model} got {err}, retry in {wait}s", flush=True)
            time.sleep(wait)
            continue
        print(f"[brain] team: {model} failed: {err}", flush=True)
        break
    if not text:
        return [(m, _offline_line(m, q)) for m in members]
    # parse [member] blocks
    out, current, buf = [], None, []
    for line in text.split("\n"):
        m = re.match(r"\[([a-z]+)\]\s*(.*)", line.strip(), re.I)
        if m and m.group(1).lower() in members:
            if current:
                out.append((current, "\n".join(buf).strip()))
            current, buf = m.group(1).lower(), [m.group(2)]
        elif current:
            buf.append(line)
    if current:
        out.append((current, "\n".join(buf).strip()))
    # keep routed order, fill any missing with offline line
    got = {m for m, _ in out}
    ordered = [p for m in members for p in out if p[0] == m]
    for m in members:
        if m not in got:
            ordered.append((m, _offline_line(m, q)))
    return ordered


def _offline_line(member, q):
    lines = {
        "wick": "I'm here. The brain's offline but I'm listening — say it again when we're back?",
        "foreman": "Noted. I'll pick this up the moment the brain's back online.",
        "archivist": "I'll log this for later — nothing gets lost.",
        "scout": "I'll dig into that as soon as I can reach the outside.",
        "tinker": "On the bench. I'll build it when the brain's back.",
        "guardian": "Staying watchful. Nothing leaves this room.",
        "greeter": "Hey — I'm here, just running on backup power right now.",
    }
    return lines.get(member, "Here.")
