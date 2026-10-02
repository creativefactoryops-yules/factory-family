"""Greeter brain — three layers, best to worst.
1. Gemini (online, smart)   — needs GEMINI_API_KEY env; chains models so quota
                              never kills it: flash (~20/day) -> flash-lite (~500/day)
                              -> gemma (~14k/day). Override with GEMINI_MODELS env.
2. Local Llama via Ollama   — needs ollama running; model via OLLAMA_MODEL env
3. Keyword brain             — never dies, always answers
Returns (answer, layer_name). Layer 1 failure falls through silently.
"""
import json, os, re, urllib.request

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
# Free-tier daily budgets (per model): flash ~20/day, lite ~500/day, gemma ~14k/day.
# Chain them best-to-cheapest so one model's quota never kills the brain.
GEMINI_MODELS = os.environ.get(
    "GEMINI_MODELS",
    "gemini-3.8-flash,gemini-3.5-flash-lite,gemma-4-26b-a4b-it",
).split(",")
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
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp)

def gemini_ask(q):
    """Try each Gemini model in order; a 429/quota error falls to the next model."""
    if not GEMINI_KEY:
        return None
    last = None
    for model in GEMINI_MODELS:
        model = model.strip()
        if not model:
            continue
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={GEMINI_KEY}")
            d = _post(url, {"system_instruction": {"parts": [{"text": SYSTEM}]},
                            "contents": [{"parts": [{"text": q}]}]})
            return d["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            last = e
            continue
    # every model exhausted — let the outer chain fall through to llama
    return None

def llama_ask(q):
    d = _post("http://127.0.0.1:11434/api/generate",
              {"model": OLLAMA_MODEL, "prompt": f"{SYSTEM}\n\nVisitor: {q}\nGreeter:",
               "stream": False}, timeout=60)
    return d.get("response", "").strip()

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
