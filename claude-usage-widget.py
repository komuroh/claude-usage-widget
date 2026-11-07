#!/usr/bin/env python3
# claude-usage-widget.py  (Windows)
# Always-on-top mini window showing Claude plan usage (5-hour + weekly).
# Session capture (cookie DB -> cached credentials) is built in; use the
# "Refresh session" button in the widget to close Desktop, capture, and relaunch.
#
# Deps: pycryptodome (Crypto.Cipher.AES), only exercised when refreshing the session.

import os, sys, json, ctypes, subprocess, threading, queue, time, sqlite3, tempfile, shutil, base64, glob
from ctypes import wintypes
from datetime import datetime, timezone
import urllib.request, urllib.error
import tkinter as tk

CACHE_FILE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "claude-usage", "session.bin")
POLL_MS = 60_000   # claude.ai usage endpoint; 60s is safe
CLAUDE_PROC = "Claude.exe"

# ---- DPAPI unprotect (to read the cache) ----
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_unprotect(data):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 0, ctypes.byref(bo)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(bo.pbData, bo.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(bo.pbData)

def dpapi_protect(data):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(bi), None, None, None, None, 0, ctypes.byref(bo)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(bo.pbData, bo.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(bo.pbData)

def load_cache():
    with open(CACHE_FILE, "rb") as f:
        return json.loads(dpapi_unprotect(f.read()).decode("utf-8"))

def save_cache(cookies):
    d = os.path.dirname(CACHE_FILE)
    os.makedirs(d, exist_ok=True)
    with open(CACHE_FILE, "wb") as f:
        f.write(dpapi_protect(json.dumps(cookies).encode("utf-8")))

# ---------- in-process session capture (was get-desktop-session.py --save) ----------
def _find_claude_base():
    """Locate the Claude Desktop profile folder (has both Local State and
    Network\\Cookies). Checks the classic (non-packaged) install location first,
    then scans %LOCALAPPDATA%\\Packages\\*Claude* for MSIX installs instead of
    hardcoding one publisher-hash folder name (that hash can differ per install/
    distribution channel)."""
    def _valid(p):
        return (os.path.exists(os.path.join(p, "Local State")) and
                os.path.exists(os.path.join(p, "Network", "Cookies")))

    classic = os.path.join(os.environ.get("APPDATA", ""), "Claude")
    if _valid(classic):
        return classic

    local = os.environ.get("LOCALAPPDATA", "")
    for pkg_dir in glob.glob(os.path.join(local, "Packages", "*Claude*")):
        cand = os.path.join(pkg_dir, "LocalCache", "Roaming", "Claude")
        if _valid(cand):
            return cand
    return None

def _get_master_key(base):
    with open(os.path.join(base, "Local State"), "r", encoding="utf-8") as f:
        ls = json.load(f)
    blob = base64.b64decode(ls["os_crypt"]["encrypted_key"])
    return dpapi_unprotect(blob[5:])  # strip "DPAPI" prefix

def _decrypt_cookie_value(enc, key):
    if enc[:3] in (b"v10", b"v11"):
        from Crypto.Cipher import AES  # bundled by PyInstaller; not needed at plain `pythonw` runtime unless refreshing
        nonce, tag, cipher = enc[3:15], enc[-16:], enc[15:-16]
        plain = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(cipher, tag)
        try:
            return plain.decode("utf-8")
        except UnicodeDecodeError:
            return plain[32:].decode("utf-8")
    return dpapi_unprotect(enc).decode("utf-8")

def capture_session():
    """Read cookies from Claude Desktop's (closed) Cookies DB and refresh CACHE_FILE.
    Must be called while Claude Desktop is fully closed (the DB is exclusively locked
    while it runs). Raises on failure; caller decides what to log."""
    base = _find_claude_base()
    if not base:
        raise RuntimeError("Claude Desktop data folder not found")
    cookies_db = os.path.join(base, "Network", "Cookies")
    tmp = os.path.join(tempfile.gettempdir(), "cl_cookies_%d.db" % os.getpid())
    try:
        shutil.copy2(cookies_db, tmp)
    except (PermissionError, OSError) as e:
        raise RuntimeError("Cookie DB locked (Claude Desktop still running?): %s" % e)
    try:
        con = sqlite3.connect(tmp)
        rows = con.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%claude.ai'").fetchall()
        con.close()
    finally:
        try: os.remove(tmp)
        except OSError: pass
    key = _get_master_key(base)
    out = {}
    for name, enc in rows:
        try: out[name] = _decrypt_cookie_value(enc, key)
        except Exception: pass
    if "sessionKey" not in out:
        raise RuntimeError("sessionKey cookie not found (not logged in?)")
    save_cache(out)
    return out

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

def api_get(url, cookies):
    req = urllib.request.Request(url, headers={
        "Cookie": "; ".join("%s=%s" % (k, v) for k, v in cookies.items()),
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9", "Referer": "https://claude.ai/",
        "Origin": "https://claude.ai",
        "anthropic-anonymous-id": cookies.get("anthropic-device-id", ""),
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_usage(cookies):
    org = cookies.get("lastActiveOrg")
    if not org:
        org = api_get("https://claude.ai/api/organizations", cookies)[0]["uuid"]
    return api_get("https://claude.ai/api/organizations/%s/usage" % org, cookies)

def fmt_reset(iso):
    if not iso: return ""
    try:
        t = datetime.fromisoformat(iso).astimezone()
        return "reset " + t.strftime("%m/%d %H:%M")
    except Exception:
        return ""

# ---------- session refresh: close Desktop -> --save -> relaunch ----------
CREATE_NO_WINDOW = 0x08000000

def _is_claude_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % CLAUDE_PROC],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        return CLAUDE_PROC.lower() in out.stdout.lower()
    except Exception:
        return False

def _close_claude(log):
    if not _is_claude_running():
        log("Claude Desktop is not running.")
        return
    log("Closing Claude Desktop...")
    subprocess.run(["taskkill", "/F", "/IM", CLAUDE_PROC, "/T"],
                    capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    for _ in range(20):  # up to ~10s for the cookie DB file lock to release
        if not _is_claude_running():
            time.sleep(1.0)
            return
        time.sleep(0.5)
    log("warning: Claude Desktop still appears to be running")

def _get_claude_appid():
    # MSIX-packaged app: resolve the Start Menu AppID via Get-StartApps.
    ps = ("(Get-StartApps | Where-Object { $_.Name -like '*Claude*' } "
          "| Select-Object -First 1 -ExpandProperty AppID)")
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    appid = out.stdout.strip()
    return appid or None

def _launch_claude(log):
    log("Relaunching Claude Desktop...")
    appid = _get_claude_appid()
    if appid:
        subprocess.Popen(["explorer.exe", "shell:appsFolder\\%s" % appid])
    else:
        log("error: could not resolve Claude Desktop AppID via Get-StartApps")

def _run_save(log):
    log("Capturing session...")
    try:
        capture_session()
    except Exception as e:
        log("error: capture failed: %.150s" % e)
        return False
    return True

def refresh_session_worker(log, done):
    try:
        was_running = _is_claude_running()
        _close_claude(log)
        ok = _run_save(log)
        if was_running:
            _launch_claude(log)
        log("Done." if ok else "Finished with errors.")
    except Exception as e:
        log("error: %.120s" % e)
    finally:
        done()

# ---------- UI ----------
BG="#1f1e1d"; ACCENT="#d97757"; GREEN="#7a9e7e"; FG="#eeeeee"; SUB="#999999"; TRACK="#333333"

class Widget:
    def __init__(self, root):
        self.root = root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG)
        try: root.attributes("-alpha", 0.95)
        except Exception: pass

        self.cookies = None
        pad = tk.Frame(root, bg=BG); pad.pack(fill="both", expand=True, padx=12, pady=10)

        top = tk.Frame(pad, bg=BG); top.pack(fill="x")
        tk.Label(top, text="Claude Usage", fg=ACCENT, bg=BG,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(top, text="✕", fg=SUB, bg=BG, cursor="hand2",
                 font=("Segoe UI", 10)).pack(side="right")
        top.winfo_children()[-1].bind("<Button-1>", lambda e: root.destroy())

        self.v5 = tk.Label(pad, text="--%", fg=FG, bg=BG, font=("Segoe UI", 22, "bold"))
        self.v5.pack(anchor="w", pady=(6,0))
        self.b5 = self._bar(pad, ACCENT)
        self.r5 = tk.Label(pad, text="5h window", fg=SUB, bg=BG, font=("Segoe UI", 8))
        self.r5.pack(anchor="w")

        self.v7 = tk.Label(pad, text="weekly --%", fg="#cccccc", bg=BG, font=("Segoe UI", 11))
        self.v7.pack(anchor="w", pady=(8,0))
        self.b7 = self._bar(pad, GREEN)
        self.r7 = tk.Label(pad, text="", fg=SUB, bg=BG, font=("Segoe UI", 8))
        self.r7.pack(anchor="w")

        self.stat = tk.Label(pad, text="", fg="#666666", bg=BG, font=("Segoe UI", 8))
        self.stat.pack(anchor="w", pady=(8,0))

        self._log_q = queue.Queue()
        self._refreshing = False
        self.refresh_btn = tk.Label(pad, text="Refresh session (close & reopen)",
                                     fg=ACCENT, bg=BG, cursor="hand2",
                                     font=("Segoe UI", 8, "underline"))
        self.refresh_btn.pack(anchor="w", pady=(4,0))
        self.refresh_btn.bind("<Button-1>", self._on_refresh_click)
        self.root.after(200, self._drain_log_queue)

        # drag to move
        for w in (root, pad, top):
            w.bind("<Button-1>", self._press)
            w.bind("<B1-Motion>", self._drag)

        # bottom-right placement
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry("+%d+%d" % (sw-260, sh-280))

        self.refresh()

    def _bar(self, parent, color):
        c = tk.Canvas(parent, width=196, height=6, bg=TRACK, highlightthickness=0)
        c.pack(anchor="w", pady=(2,0))
        c.rect = c.create_rectangle(0, 0, 0, 6, fill=color, width=0)
        return c

    def _set_bar(self, c, pct):
        w = max(0, min(100, pct)) / 100.0 * 196
        c.coords(c.rect, 0, 0, w, 6)

    def _press(self, e): self._x, self._y = e.x, e.y
    def _drag(self, e):
        self.root.geometry("+%d+%d" % (self.root.winfo_x()+e.x-self._x,
                                       self.root.winfo_y()+e.y-self._y))

    def _on_refresh_click(self, _e=None):
        if self._refreshing:
            return
        self._refreshing = True
        self.refresh_btn.config(text="Working...", fg=SUB, cursor="")
        t = threading.Thread(
            target=refresh_session_worker,
            args=(lambda msg: self._log_q.put(msg), lambda: self._log_q.put("__DONE__")),
            daemon=True)
        t.start()

    def _drain_log_queue(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                if msg == "__DONE__":
                    self._refreshing = False
                    self.refresh_btn.config(text="Refresh session (close & reopen)",
                                             fg=ACCENT, cursor="hand2")
                    self.cookies = None  # force reload from the fresh cache
                    self.refresh()
                else:
                    self.stat.config(text=msg)
        except queue.Empty:
            pass
        self.root.after(200, self._drain_log_queue)

    def refresh(self):
        try:
            if self.cookies is None:
                self.cookies = load_cache()
            u = fetch_usage(self.cookies)
            fh, sd = u.get("five_hour") or {}, u.get("seven_day") or {}
            p5 = float(fh.get("utilization") or 0)
            p7 = float(sd.get("utilization") or 0)
            self.v5.config(text="%.0f%%" % p5); self._set_bar(self.b5, p5)
            self.r5.config(text="5h window / " + fmt_reset(fh.get("resets_at")))
            self.v7.config(text="weekly %.0f%%" % p7); self._set_bar(self.b7, p7)
            self.r7.config(text=fmt_reset(sd.get("resets_at")))
            # red when high
            self.v5.config(fg="#e05555" if p5 >= 90 else FG)
            self.stat.config(text="updated " + datetime.now().strftime("%H:%M:%S"))
        except FileNotFoundError:
            self.stat.config(text="No cache. Click 'Refresh session' below.")
        except urllib.error.HTTPError as e:
            self.stat.config(text="HTTP %s (session expired? rerun --save)" % e.code)
        except Exception as e:
            self.stat.config(text="err: %.40s" % e)
        self.root.after(POLL_MS, self.refresh)

def main():
    root = tk.Tk()
    Widget(root)
    root.mainloop()

if __name__ == "__main__":
    main()
