"""Tinker's eyes — read-only inspection tools for the factory floor.

Stage 1 of making the family real: Tinker can LOOK at real state
(files, git history) but cannot change anything.

Safety rules (Guardian's future allowlist starts here):
- Every path is sandboxed under the user's home dir. Symlinks are
  resolved and escapes rejected with ValueError.
- No writes, no network, no arbitrary commands. The only subprocess
  allowed is `git log` (read-only).
- Reports are compact plain text, sized for prompt injection.
"""
import os
import subprocess
import time

HOME = os.path.realpath(os.path.expanduser("~"))
MAX_READ = 4000


def safe_path(p):
    """Resolve p under HOME or raise ValueError."""
    p = os.path.expanduser(p or "")
    if os.path.isabs(p):
        full = os.path.realpath(p)
    else:
        full = os.path.realpath(os.path.join(HOME, p))
    if full != HOME and not full.startswith(HOME + os.sep):
        raise ValueError("outside home dir: %r" % p)
    return full


def list_files(path):
    """Top-level listing: kind, size, date, name. Dotfiles skipped."""
    full = safe_path(path)
    if not os.path.isdir(full):
        return "%s: not a directory" % path
    rows = []
    for name in sorted(os.listdir(full)):
        if name.startswith("."):
            continue
        fp = os.path.join(full, name)
        try:
            st = os.stat(fp)
            kind = "dir " if os.path.isdir(fp) else "file"
            rows.append("%s %8d  %s  %s" % (
                kind, st.st_size,
                time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)), name))
        except OSError:
            rows.append("???? %s" % name)
    return "%s:\n%s" % (path, "\n".join(rows[:40]) if rows else "(empty)")


def read_file(path, max_chars=MAX_READ):
    """Read a text file, truncated. Binary-safe (replacement chars)."""
    full = safe_path(path)
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            data = f.read(max_chars + 1)
    except OSError as e:
        return "%s: unreadable (%s)" % (path, e)
    if len(data) > max_chars:
        data = data[:max_chars] + "\n...(truncated)"
    return "%s:\n%s" % (path, data)


def git_log(path, n=5):
    """Last n commits, one line each: date + message. Read-only."""
    full = safe_path(path)
    try:
        r = subprocess.run(
            ["git", "-C", full, "log", "-n%d" % n,
             "--format=%ad %h %s", "--date=short"],
            capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return "%s: git not installed" % path
    except subprocess.TimeoutExpired:
        return "%s: git timed out" % path
    if r.returncode != 0:
        return "%s: not a git repo (or git error)" % path
    out = r.stdout.strip()
    return "%s — last %d commits:\n%s" % (path, n, out if out else "(no commits)")


def project_status(path):
    """Compact card: last commit + newest files. The lie-detector feed."""
    full = safe_path(path)
    if not os.path.exists(full):
        return "%s: does not exist" % path
    lines = ["## " + path]
    try:
        r = subprocess.run(
            ["git", "-C", full, "log", "-n1",
             "--format=%ad %h %s", "--date=short"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            lines.append("last commit: " + r.stdout.strip())
        else:
            lines.append("last commit: (not a git repo or no commits)")
    except Exception as e:
        lines.append("last commit: (git unavailable: %s)" % e)
    newest = []
    if os.path.isdir(full):
        for root, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d != "node_modules"]
            for f in files:
                if f.startswith("."):
                    continue
                fp = os.path.join(root, f)
                try:
                    newest.append((os.stat(fp).st_mtime,
                                   os.path.relpath(fp, full)))
                except OSError:
                    pass
            if len(newest) > 400:
                break
    newest.sort(reverse=True)
    if newest:
        lines.append("newest files:")
        for mt, rel in newest[:5]:
            lines.append("  %s  %s" % (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)), rel))
    return "\n".join(lines)


def _watch_list():
    """Where Tinker looks by default. TINKER_WATCH env (colon-separated)
    wins, then ~/.factory/tinker_watch (one path per line), then defaults."""
    raw = os.environ.get("TINKER_WATCH", "").strip()
    if raw:
        return [p.strip() for p in raw.split(":") if p.strip()]
    watch_file = os.path.join(HOME, ".factory", "tinker_watch")
    try:
        with open(watch_file) as f:
            paths = [l.strip() for l in f
                     if l.strip() and not l.strip().startswith("#")]
        if paths:
            return paths
    except OSError:
        pass
    me = os.path.realpath(os.path.join(os.path.dirname(
        os.path.abspath(__file__)), ".."))
    return [me, os.path.join(HOME, "assistant-bot")]


def _paths_from_question(q):
    """Pull ~/... paths straight out of Yules's message."""
    found = []
    for tok in q.replace(",", " ").split():
        tok = tok.strip("'\"()[]")
        if tok.startswith("~/"):
            found.append(os.path.expanduser(tok))
    return found


def tinker_eyes(q):
    """Gather real state for a Tinker status question.

    Returns a compact plain-text report, or '' if nothing checkable
    was found. Never raises — callers inject whatever comes back.
    """
    try:
        seen, paths = set(), []
        for p in _paths_from_question(q) + _watch_list():
            try:
                full = safe_path(p)
            except ValueError:
                continue
            if full not in seen and os.path.exists(full):
                seen.add(full)
                paths.append((p, full))
        if not paths:
            return ""
        cards = []
        for shown, full in paths[:4]:
            try:
                cards.append(project_status(shown))
            except Exception as e:
                cards.append("## %s\n(eyes error: %s)" % (shown, e))
        return "\n\n".join(cards)
    except Exception as e:
        return "(eyes failed: %s)" % e
