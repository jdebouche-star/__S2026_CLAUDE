#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DX Cluster Board
================
A colourful live board of DX spots, collected from a list of well known
public DX clusters at the same time.

  * Tick the clusters you want (or add your own host:port) and press Connect
  * Spots from all clusters are merged: the same DX on the same frequency is
    shown once, with every spotter and a coloured dot for every cluster
  * Each band and mode has its own colour
  * Band activity bars at the top: click a bar to show / hide that band
  * Mode chips: click to show / hide CW, SSB, FT8, ...
  * Search box for DX call or country
  * New spots light up, old spots fade and are removed after N minutes
  * Click a spot to open the QRZ.com page of the DX station

Only the Python standard library is used (tkinter, socket, urllib, json),
so it runs as-is in Thonny on Windows: open the file and press F5.

On first start cty.dat (country-files.com) is downloaded next to the script
to show the country of each DX station. Without it the board still works,
only the country column stays empty.

Run with  --demo  to see the board with made-up spots (no internet needed).
"""

import json
import os
import queue
import random
import re
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone

import tkinter as tk
from tkinter import messagebox, ttk


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_NAME = "DX Cluster Board"
APP_VERSION = "1.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "dx_cluster_board.json")
CTY_FILE = os.path.join(APP_DIR, "cty.dat")     # shared with dx_spot_map.py
CTY_URLS = [
    "https://www.country-files.com/cty/cty.dat",
    "https://www.country-files.com/bigcty/cty.dat",
]
HTTP_AGENT = "Mozilla/5.0 (DXClusterBoard %s)" % APP_VERSION

# Well known public clusters: (name, host, port, on by default)
# The list can be changed in the program and is saved in the settings file.
DEFAULT_CLUSTERS = [
    ("VE7CC", "dxc.ve7cc.net", 23, True),
    ("W3LPL", "w3lpl.net", 7373, False),
    ("NC7J", "dxc.nc7j.com", 7373, False),
    ("GB7DJK", "gb7djk.dxcluster.net", 7300, True),
    ("DL9GTB", "cluster.dl9gtb.de", 8000, True),
    ("ON0DXK", "on0dxk.dyndns.org", 8000, False),
    ("DXFun", "dxfun.com", 8000, False),
    ("HamQTH", "hamqth.com", 7300, False),
    ("RBN CW", "telnet.reversebeacon.net", 7000, False),
    ("RBN FT8", "telnet.reversebeacon.net", 7001, False),
]

# One colour per cluster (dots in the spot list and the status panel)
CLUSTER_PALETTE = ["#ff5e7e", "#ffb347", "#ffe066", "#7cff6b", "#3ee0d0",
                   "#4da3ff", "#a77bff", "#ff7ae0", "#c0c0c0", "#ff9e5e"]

# name, low kHz, high kHz, colour
BANDS = [
    ("160m", 1800, 2000, "#ff3b3b"),
    ("80m", 3500, 4000, "#ff8c00"),
    ("60m", 5060, 5450, "#ffc800"),
    ("40m", 7000, 7300, "#fff200"),
    ("30m", 10100, 10150, "#a8ff00"),
    ("20m", 14000, 14350, "#00ff6a"),
    ("17m", 18068, 18168, "#00ffd0"),
    ("15m", 21000, 21450, "#00b4ff"),
    ("12m", 24890, 24990, "#5c7cff"),
    ("10m", 28000, 29700, "#b45cff"),
    ("6m", 50000, 54000, "#ff4de6"),
    ("4m", 70000, 71000, "#ff85a8"),
    ("2m", 144000, 148000, "#e8e8e8"),
]
BAND_NAMES = [b[0] for b in BANDS]
BAND_COLOR = {b[0]: b[3] for b in BANDS}

MODES = ["CW", "SSB", "FT8", "FT4", "RTTY", "DIGI"]
MODE_COLOR = {
    "CW": "#ffe600",
    "SSB": "#ff4d4d",
    "FT8": "#00e5ff",
    "FT4": "#4dff88",
    "RTTY": "#ff9a1f",
    "DIGI": "#d27dff",
}

# Top of the CW segment and bottom of the phone segment per band (kHz).
# Only used when a spot does not say which mode it is.
CW_TOP = {"160m": 1838, "80m": 3570, "60m": 5354, "40m": 7040, "30m": 10130,
          "20m": 14070, "17m": 18095, "15m": 21070, "12m": 24915,
          "10m": 28070, "6m": 50100, "4m": 70100, "2m": 144150}
SSB_BOTTOM = {"160m": 1843, "80m": 3600, "60m": 5354, "40m": 7060,
              "30m": 99999, "20m": 14100, "17m": 18110, "15m": 21150,
              "12m": 24930, "10m": 28300, "6m": 50100, "4m": 70100,
              "2m": 144150}
FT8_DIALS = [1840, 3573, 5357, 7074, 10136, 14074, 18100, 21074, 24915,
             28074, 50313, 70154, 144174]
FT4_DIALS = [3575.5, 7047.5, 10140, 14080, 18104, 21140, 24919, 28180,
             50318, 144170]
MODE_WORDS = [
    (re.compile(r"\bFT8\b"), "FT8"),
    (re.compile(r"\bFT4\b"), "FT4"),
    (re.compile(r"\bRTTY\b"), "RTTY"),
    (re.compile(r"\bCW\b"), "CW"),
    (re.compile(r"\b(SSB|USB|LSB|PHONE)\b"), "SSB"),
    (re.compile(r"\b(B?PSK\d*|JT65|JT9|JS8|MSK144|Q65|OLIVIA|SSTV|MFSK\d*|"
                r"DIGI|VARAC|FST4)\b"), "DIGI"),
]

# Look
BG = "#0b1020"
PANEL = "#131a33"
PANEL2 = "#1a2342"
ROW_A = "#111830"
ROW_B = "#151d3a"
ROW_HOVER = "#26335f"
FG = "#e8ecff"
DIM = "#8892b8"
ACCENT = "#ffcc33"
NEW_GLOW = "#fff27a"
STATUS_COLOR = {"connected": "#3dff8c", "receiving": "#3dff8c",
                "connecting": "#ffd23d", "reconnect": "#ff9a3d",
                "error": "#ff4d6d", "off": "#59607d"}

FONT = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
MONO = "Consolas" if sys.platform.startswith("win") else "Courier"

ROW_H = 30
DEDUP_SECONDS = 600       # same call within 1 kHz in 10 min = same spot
MAX_SPOTS = 3000
NEW_SECONDS = 45          # how long a fresh spot glows

CALL_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "QRPP", "A", "B", "R", "LH",
                 "J", "E", "PM", "LGT", "BCN", "N", "T", "X"}
CALL_RE = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9/]{3,15}$")
SPOT_RE = re.compile(
    r"^DX de\s+([^\s:]+):?\s+(\d+(?:\.\d+)?)\s+([A-Za-z0-9/]+)\s+(.*)\s(\d{4})Z")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def band_of(khz):
    for name, lo, hi, _ in BANDS:
        if lo <= khz <= hi:
            return name
    return None


def infer_mode(khz, band, comment):
    """Mode from the spot comment, else from the frequency (band plan)."""
    text = (comment or "").upper()
    for rx, mode in MODE_WORDS:
        if rx.search(text):
            return mode
    for d in FT8_DIALS:
        if d - 0.5 <= khz <= d + 3.5:
            return "FT8"
    for d in FT4_DIALS:
        if d - 0.5 <= khz <= d + 3.5:
            return "FT4"
    if band is None:
        return "DIGI"
    if khz < CW_TOP.get(band, 0):
        return "CW"
    if khz >= SSB_BOTTOM.get(band, 1e9):
        return "SSB"
    return "DIGI"


def clean_spotter(raw):
    """'KM3T-2-#' -> 'KM3T', 'DL1ABC-7' -> 'DL1ABC'."""
    s = raw.upper().rstrip(":").replace("-#", "")
    return re.sub(r"-\d+$", "", s)


def _looks_like_call(p):
    return bool(re.match(r"^[A-Z0-9]{1,3}\d[A-Z]{1,5}$", p))


def home_call(call):
    """The station's own call: 'EA8/ON4XX/P' -> 'ON4XX'."""
    parts = [p for p in call.upper().split("/") if p]
    if len(parts) <= 1:
        return parts[0] if parts else call.upper()
    cands = [p for p in parts
             if p not in CALL_SUFFIXES and not (len(p) == 1 and p.isdigit())]
    if not cands:
        return parts[0]
    return max(cands, key=lambda p: (_looks_like_call(p), len(p)))


def location_prefix(call):
    """The part that tells where the station is: 'EA8/ON4XX' -> 'EA8'."""
    parts = [p for p in call.upper().split("/") if p]
    if "MM" in parts or "AM" in parts:
        return None
    hc = home_call(call)
    others = [p for p in parts if p != hc and p not in CALL_SUFFIXES]
    if not others or (len(others[0]) == 1 and others[0].isdigit()):
        return hc
    return others[0]


def parse_spot_line(line, rbn=False):
    m = SPOT_RE.match(line)
    if not m:
        return None
    spotter, freq, call, comment, hhmm = m.groups()
    call = call.upper()
    if not CALL_RE.match(call):
        return None
    try:
        khz = float(freq)
    except ValueError:
        return None
    band = band_of(khz)
    comment = re.sub(r"\s+", " ", comment.strip())
    if rbn:
        word = (comment.split() or [""])[0].upper()
        mode = word if word in ("CW", "RTTY", "FT8", "FT4") else "DIGI"
    else:
        mode = infer_mode(khz, band, comment)
    return {"spotter": clean_spotter(spotter), "freq": khz, "call": call,
            "band": band, "mode": mode, "comment": comment, "time": hhmm}


def download(urls, path, log):
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HTTP_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 1000:
                raise ValueError("file too small")
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
            return True
        except Exception as e:  # noqa: BLE001 - report and try the next URL
            log("cty.dat download failed (%s): %s" % (url, e), "err")
    return False


def blend(c1, c2, f):
    """Mix two #rrggbb colours, f=0 -> c1, f=1 -> c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * f) for x, y in zip(a, b))


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
# cty.dat: prefix -> country
# ---------------------------------------------------------------------------

class CtyDatabase:
    OVERRIDES = re.compile(r"\(.*?\)|\[.*?\]|<.*?>|\{.*?\}|~.*?~")

    def __init__(self):
        self.prefixes = {}
        self.exact = {}

    def load(self, path):
        with open(path, "r", encoding="latin-1") as f:
            text = f.read()
        for record in text.split(";"):
            fields = record.split(":")
            if len(fields) < 9:
                continue
            entity = (fields[0].strip(), fields[3].strip())   # name, continent
            for item in ":".join(fields[8:]).split(","):
                p = self.OVERRIDES.sub("", item).strip()
                if p.startswith("="):
                    self.exact[p[1:]] = entity
                elif p:
                    self.prefixes[p] = entity
        return len(self.prefixes)

    def find(self, call):
        call = call.upper()
        if call in self.exact:
            return self.exact[call]
        loc = location_prefix(call)
        if not loc:
            return ("Mobile at sea / air", "")
        if loc in self.exact:
            return self.exact[loc]
        for i in range(len(loc), 0, -1):
            ent = self.prefixes.get(loc[:i])
            if ent:
                return ent
        return None


# ---------------------------------------------------------------------------
# Telnet connection to one cluster
# ---------------------------------------------------------------------------

class ClusterConnection(threading.Thread):
    IAC, DONT, DO, WONT, WILL = 255, 254, 253, 252, 251

    def __init__(self, idx, name, host, port, callsign, out_q):
        super().__init__(daemon=True)
        self.idx = idx
        self.cname = name
        self.host = host
        self.port = port
        self.callsign = callsign
        self.out_q = out_q
        self.rbn = "reversebeacon" in host.lower()
        self.stop_event = threading.Event()
        self.sock = None

    def log(self, text, level="info"):
        self.out_q.put(("log", "[%s] %s" % (self.cname, text), level))

    def status(self, state, text=""):
        self.out_q.put(("status", self.idx, state, text))

    def stop(self):
        self.stop_event.set()
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def _telnet_filter(self, data):
        """Strip telnet negotiation and refuse every option."""
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == self.IAC and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (self.DO, self.DONT, self.WILL, self.WONT) and i + 2 < len(data):
                    try:
                        if cmd == self.DO:
                            self.sock.sendall(bytes([self.IAC, self.WONT, data[i + 2]]))
                        elif cmd == self.WILL:
                            self.sock.sendall(bytes([self.IAC, self.DONT, data[i + 2]]))
                    except OSError:
                        pass
                    i += 3
                elif cmd == self.IAC:
                    out.append(self.IAC)
                    i += 2
                else:
                    i += 2
            else:
                out.append(b)
                i += 1
        return bytes(out)

    def run(self):
        delay = 5
        while not self.stop_event.is_set():
            try:
                self.status("connecting", "connecting")
                self.sock = socket.create_connection((self.host, self.port), timeout=20)
                self.sock.settimeout(1.0)
                self.status("connected", "connected")
                self.log("connected to %s:%d" % (self.host, self.port), "ok")
                self._session()
                delay = 5
            except OSError as e:
                if not self.stop_event.is_set():
                    self.log("connection problem: %s" % e, "err")
                    self.status("error", str(e)[:40])
            finally:
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
            if self.stop_event.is_set():
                break
            self.status("reconnect", "retry in %ds" % delay)
            self.stop_event.wait(delay)
            delay = min(delay * 2, 120)
        self.status("off", "off")

    def _session(self):
        buf = b""
        logged_in = False
        t0 = time.time()
        info_lines = 0
        spots = 0
        while not self.stop_event.is_set():
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                data = None
            if data == b"":
                raise ConnectionError("closed by remote host")
            if data:
                buf += self._telnet_filter(data)
            if not logged_in:
                tail = buf.rsplit(b"\n", 1)[-1].lower()
                if b"call" in tail or b"login" in tail or time.time() - t0 > 10:
                    self.sock.sendall((self.callsign + "\r\n").encode("ascii"))
                    logged_in = True
                    self.log("logged in as %s" % self.callsign)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("latin-1").strip("\r\x07 \t")
                if not line:
                    continue
                dx = line.find("DX de")       # a prompt may sit in front of it
                if dx >= 0:
                    spot = parse_spot_line(line[dx:], self.rbn)
                    if spot:
                        spots += 1
                        if spots == 1:
                            self.status("receiving", "receiving spots")
                        spot["cluster"] = self.idx
                        self.out_q.put(("spot", spot))
                elif info_lines < 6:
                    info_lines += 1
                    self.log(line[:110], "dim")
            if len(buf) > 65536:
                buf = b""


class DemoSource(threading.Thread):
    """Made-up spots so the board can be seen without internet (--demo)."""
    CALLS = ["VP8LP", "3Y0K", "ZL7X", "JA1XYZ", "VK9DX", "A71AN", "PY2XB",
             "EA8/ON4XX", "TF3ML", "KH6LC", "ZS6BK", "9M2TO", "UA0SDX",
             "W1AW", "OX3LX", "FY5KE", "5B4AHJ", "HZ1TT", "T88WA", "K1N/P"]
    SPOTTERS = ["DL1ABC", "ON4UN", "G3XYZ", "K3LR", "JA7ABC", "VE3AB",
                "F5NBX", "OH2BH", "I2XYZ", "PA3EWP"]

    def __init__(self, n_clusters, out_q):
        super().__init__(daemon=True)
        self.n = max(1, n_clusters)
        self.out_q = out_q
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        for i in range(self.n):
            self.out_q.put(("status", i, "receiving", "demo"))
        while not self.stop_event.wait(random.uniform(0.3, 1.5)):
            name, lo, hi, _ = random.choice(BANDS[:11])
            khz = round(random.uniform(lo, min(hi, lo + 300)), 1)
            comment = random.choice(["", "CW", "FT8 -12dB", "SSB 59", "up 2",
                                     "TNX QSO", "RTTY", "loud!"])
            line = "DX de %s: %9.1f  %-12s %-30s %sZ" % (
                random.choice(self.SPOTTERS), khz, random.choice(self.CALLS),
                comment, datetime.now(timezone.utc).strftime("%H%M"))
            spot = parse_spot_line(line)
            if spot:
                spot["cluster"] = random.randrange(self.n)
                self.out_q.put(("spot", spot))


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------

class DxClusterBoard:
    def __init__(self, root, demo=False):
        self.root = root
        self.demo = demo
        self.q = queue.Queue()
        self.cty = CtyDatabase()
        self.settings = self._load_settings()
        self.clusters = self.settings["clusters"]
        self.connections = []
        self.status = {}               # idx -> (state, text)
        self.cluster_count = {}        # idx -> number of spots received
        self.spots = []                # newest first
        self.view = []                 # filtered spots, newest first
        self.band_on = set(self.settings.get("bands") or BAND_NAMES)
        self.mode_on = set(self.settings.get("modes") or MODES)
        self.offset = 0                # first visible row
        self.hover = None
        self.total = 0

        root.title("%s %s" % (APP_NAME, APP_VERSION))
        root.configure(bg=BG)
        root.geometry("1280x820")
        root.minsize(980, 600)
        self._style()
        self._build_ui()
        self._log("Welcome! Tick the clusters, enter your call and press Connect.", "ok")
        threading.Thread(target=self._load_cty, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._poll)
        root.after(1000, self._tick)
        if demo:
            root.after(300, self._toggle_connect)

    # ----- settings --------------------------------------------------------

    def _load_settings(self):
        s = {}
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, ValueError):
            pass
        if not isinstance(s.get("clusters"), list) or not s["clusters"]:
            s["clusters"] = [{"name": n, "host": h, "port": p, "on": on}
                             for n, h, p, on in DEFAULT_CLUSTERS]
        s.setdefault("callsign", "")
        s.setdefault("keep", 30)
        return s

    def _save_settings(self):
        self.settings.update({
            "callsign": self.call_var.get().strip().upper(),
            "keep": self._keep_minutes(),
            "clusters": self.clusters,
            "bands": sorted(self.band_on, key=BAND_NAMES.index),
            "modes": [m for m in MODES if m in self.mode_on],
        })
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except OSError as e:
            self._log("Could not save settings: %s" % e, "err")

    def _keep_minutes(self):
        try:
            return max(1, min(720, int(self.keep_var.get())))
        except (ValueError, tk.TclError):
            return 30

    def _cluster_color(self, idx):
        return CLUSTER_PALETTE[idx % len(CLUSTER_PALETTE)]

    # ----- UI --------------------------------------------------------------

    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG,
                     bordercolor=BG, arrowcolor=FG, lightcolor=PANEL2,
                     darkcolor=PANEL2)

    def _label(self, parent, text, **kw):
        opts = {"bg": parent["bg"], "fg": DIM, "font": (FONT, 9)}
        opts.update(kw)
        return tk.Label(parent, text=text, **opts)

    def _button(self, parent, text, cmd, color):
        b = tk.Label(parent, text=text, bg=color, fg="#10131f", cursor="hand2",
                     font=(FONT, 10, "bold"), padx=14, pady=5)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=blend(b["bg"], "#ffffff", 0.25)))
        b.bind("<Leave>", lambda e: b.configure(bg=b.color))
        b.color = color
        return b

    def _set_button_color(self, b, color):
        b.color = color
        b.configure(bg=color)

    def _entry(self, parent, var, width):
        return tk.Entry(parent, textvariable=var, width=width, bg=PANEL2, fg=FG,
                        insertbackground=FG, relief="flat", font=(FONT, 11),
                        highlightthickness=1, highlightbackground="#2c3866",
                        highlightcolor=ACCENT)

    def _build_ui(self):
        # --- title bar with rainbow stripe
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=14, pady=(10, 0))
        title = tk.Canvas(head, bg=BG, height=40, highlightthickness=0, width=360)
        title.pack(side="left")
        x = 2
        for i, ch in enumerate("DX Cluster Board"):
            col = BANDS[i % len(BANDS)][3] if ch != " " else BG
            t = title.create_text(x, 21, text=ch, anchor="w", fill=col,
                                  font=(FONT, 22, "bold"))
            x = title.bbox(t)[2] + 1
        self.clock = tk.Label(head, bg=BG, fg=ACCENT, font=(MONO, 18, "bold"))
        self.clock.pack(side="right")
        self.counter = tk.Label(head, bg=BG, fg=DIM, font=(FONT, 10))
        self.counter.pack(side="right", padx=16)
        stripe = tk.Canvas(self.root, bg=BG, height=4, highlightthickness=0)
        stripe.pack(fill="x", padx=14, pady=(4, 8))
        stripe.bind("<Configure>", lambda e: self._draw_stripe(stripe, e.width))

        # --- controls
        ctl = tk.Frame(self.root, bg=PANEL)
        ctl.pack(fill="x", padx=14)
        inner = tk.Frame(ctl, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=8)
        self._label(inner, "My call").pack(side="left")
        self.call_var = tk.StringVar(value=self.settings["callsign"])
        self._entry(inner, self.call_var, 10).pack(side="left", padx=(4, 14))
        self._label(inner, "Keep (min)").pack(side="left")
        self.keep_var = tk.StringVar(value=str(self.settings["keep"]))
        self._entry(inner, self.keep_var, 4).pack(side="left", padx=(4, 14))
        self._label(inner, "Search call / country").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refilter())
        self._entry(inner, self.search_var, 18).pack(side="left", padx=(4, 14))
        self.connect_btn = self._button(inner, "Connect", self._toggle_connect, "#3dff8c")
        self.connect_btn.pack(side="right")
        self._button(inner, "Clear", self._clear, "#4da3ff").pack(side="right", padx=8)

        # --- band activity bars + mode chips
        self.bars = tk.Canvas(self.root, bg=PANEL, height=112, highlightthickness=0)
        self.bars.pack(fill="x", padx=14, pady=(8, 0))
        self.bars.bind("<Configure>", lambda e: self._draw_bars())
        self.bars.bind("<Button-1>", self._on_bars_click)

        # --- main area: spot list (left) and clusters + log (right)
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=14, pady=8)
        right = tk.Frame(main, bg=PANEL, width=300)
        right.pack(side="right", fill="y", padx=(8, 0))
        right.pack_propagate(False)

        left = tk.Frame(main, bg=PANEL)
        left.pack(side="left", fill="both", expand=True)
        self.header = tk.Canvas(left, bg=PANEL2, height=26, highlightthickness=0)
        self.header.pack(fill="x")
        body = tk.Frame(left, bg=PANEL)
        body.pack(fill="both", expand=True)
        self.sb = ttk.Scrollbar(body, orient="vertical", command=self._on_scrollbar)
        self.sb.pack(side="right", fill="y")
        self.list = tk.Canvas(body, bg=ROW_A, highlightthickness=0)
        self.list.pack(side="left", fill="both", expand=True)
        self.list.bind("<Configure>", lambda e: self._draw_list())
        self.list.bind("<Motion>", self._on_motion)
        self.list.bind("<Leave>", lambda e: self._set_hover(None))
        self.list.bind("<Button-1>", self._on_click)
        self.list.bind("<MouseWheel>", self._on_wheel)
        self.list.bind("<Button-4>", lambda e: self._scroll(-3))
        self.list.bind("<Button-5>", lambda e: self._scroll(3))

        # clusters panel
        tk.Label(right, text="DX CLUSTERS", bg=PANEL, fg=ACCENT,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        self._label(right, "tick to use, click name for info", bg=PANEL).pack(anchor="w", padx=10)
        self.cl_frame = tk.Frame(right, bg=PANEL)
        self.cl_frame.pack(fill="x", padx=6, pady=4)
        addf = tk.Frame(right, bg=PANEL)
        addf.pack(fill="x", padx=10, pady=(2, 6))
        self.add_var = tk.StringVar()
        e = self._entry(addf, self.add_var, 20)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: self._add_cluster())
        self._button(addf, "+ Add", self._add_cluster, "#a77bff").pack(side="left", padx=(6, 0))
        self._label(right, "e.g.  my.cluster.org:7300", bg=PANEL).pack(anchor="w", padx=10)
        self._build_cluster_rows()

        tk.Label(right, text="LOG", bg=PANEL, fg=ACCENT,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        self.logbox = tk.Text(right, bg="#0d1328", fg=DIM, relief="flat",
                              font=(MONO, 8), wrap="word", height=8,
                              highlightthickness=0)
        self.logbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.logbox.tag_configure("ok", foreground="#3dff8c")
        self.logbox.tag_configure("err", foreground="#ff6b81")
        self.logbox.tag_configure("dim", foreground="#5d6690")
        self.logbox.tag_configure("info", foreground="#aab4e0")
        self.logbox.configure(state="disabled")

    def _draw_stripe(self, cv, w):
        cv.delete("all")
        n = len(BANDS)
        for i, b in enumerate(BANDS):
            cv.create_rectangle(w * i / n, 0, w * (i + 1) / n, 4, fill=b[3], width=0)

    # ----- clusters panel --------------------------------------------------

    def _build_cluster_rows(self):
        for w in self.cl_frame.winfo_children():
            w.destroy()
        self.cl_widgets = []
        for i, c in enumerate(self.clusters):
            row = tk.Frame(self.cl_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            var = tk.BooleanVar(value=c.get("on", False))
            cb = tk.Checkbutton(row, variable=var, bg=PANEL, activebackground=PANEL,
                                selectcolor=PANEL2, fg=FG, highlightthickness=0,
                                command=lambda i=i, v=var: self._cluster_toggled(i, v))
            cb.pack(side="left")
            dot = tk.Canvas(row, width=14, height=14, bg=PANEL, highlightthickness=0)
            dot.pack(side="left")
            dot.create_oval(2, 2, 12, 12, fill=self._cluster_color(i), width=0)
            name = tk.Label(row, text=c["name"], bg=PANEL, fg=FG, cursor="hand2",
                            font=(FONT, 10, "bold"), width=8, anchor="w")
            name.pack(side="left", padx=(4, 0))
            name.bind("<Button-1>", lambda e, c=c: self._log(
                "%s = %s:%d" % (c["name"], c["host"], c["port"]), "info"))
            rm = tk.Label(row, text="✕", bg=PANEL, fg="#5d6690", cursor="hand2",
                          font=(FONT, 9))
            rm.pack(side="right", padx=4)
            rm.bind("<Button-1>", lambda e, i=i: self._remove_cluster(i))
            led = tk.Canvas(row, width=12, height=12, bg=PANEL, highlightthickness=0)
            led.pack(side="right")
            st = tk.Label(row, text="", bg=PANEL, fg=DIM, font=(FONT, 8), anchor="e")
            st.pack(side="right", fill="x", expand=True, padx=4)
            self.cl_widgets.append((var, led, st))
            self._update_cluster_row(i)

    def _update_cluster_row(self, i):
        if i >= len(self.cl_widgets):
            return
        _, led, st = self.cl_widgets[i]
        state, text = self.status.get(i, ("off", ""))
        n = self.cluster_count.get(i, 0)
        led.delete("all")
        led.create_oval(1, 1, 11, 11, fill=STATUS_COLOR.get(state, DIM), width=0)
        st.configure(text=("%d spots" % n) if n else text,
                     fg=STATUS_COLOR.get(state, DIM) if not n else FG)

    def _cluster_toggled(self, i, var):
        self.clusters[i]["on"] = bool(var.get())
        self._save_settings()
        if self.connections:
            self._log("Press Disconnect / Connect to apply the change.", "info")

    def _add_cluster(self):
        text = self.add_var.get().strip()
        m = re.match(r"^(?:telnet://)?([A-Za-z0-9.\-]+)[: ]+(\d{1,5})$", text)
        if not m:
            messagebox.showwarning(APP_NAME, "Type the cluster as  host:port\n"
                                   "for example  dxc.ve7cc.net:23")
            return
        host, port = m.group(1), int(m.group(2))
        name = host.split(".")[0].upper()
        if name in ("DXC", "CLUSTER", "TELNET", "WWW", "DX") and "." in host:
            name = host.split(".")[1].upper()
        self.clusters.append({"name": name[:10], "host": host, "port": port, "on": True})
        self.add_var.set("")
        self._build_cluster_rows()
        self._save_settings()
        self._log("Added %s:%d" % (host, port), "ok")

    def _remove_cluster(self, i):
        if self.connections:
            messagebox.showinfo(APP_NAME, "Disconnect first, then remove the cluster.")
            return
        c = self.clusters[i]
        if messagebox.askyesno(APP_NAME, "Remove %s (%s:%d) from the list?"
                               % (c["name"], c["host"], c["port"])):
            del self.clusters[i]
            self.status.clear()
            self.cluster_count.clear()
            self._build_cluster_rows()
            self._save_settings()

    # ----- log -------------------------------------------------------------

    def _log(self, text, level="info"):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", time.strftime("%H:%M:%S ") + text + "\n", level)
        if int(self.logbox.index("end-1c").split(".")[0]) > 400:
            self.logbox.delete("1.0", "100.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    # ----- connect ---------------------------------------------------------

    def _toggle_connect(self):
        if self.connections:
            for c in self.connections:
                c.stop()
            self.connections = []
            self._set_button_color(self.connect_btn, "#3dff8c")
            self.connect_btn.configure(text="Connect")
            self._log("Disconnected.", "info")
            return
        call = self.call_var.get().strip().upper()
        if self.demo:
            src = DemoSource(len(self.clusters), self.q)
            src.start()
            self.connections = [src]
        else:
            if not re.match(r"^[A-Z0-9/]{3,12}$", call) or not re.search(r"\d", call):
                messagebox.showwarning(APP_NAME, "Please enter your callsign first.\n"
                                       "The clusters need it to log you in.")
                return
            chosen = [(i, c) for i, c in enumerate(self.clusters) if c.get("on")]
            if not chosen:
                messagebox.showwarning(APP_NAME, "Tick at least one cluster.")
                return
            for i, c in chosen:
                conn = ClusterConnection(i, c["name"], c["host"], int(c["port"]), call, self.q)
                conn.start()
                self.connections.append(conn)
        self._save_settings()
        self._set_button_color(self.connect_btn, "#ff5e7e")
        self.connect_btn.configure(text="Disconnect")

    def _clear(self):
        self.spots = []
        self.total = 0
        self.cluster_count.clear()
        for i in range(len(self.clusters)):
            self._update_cluster_row(i)
        self._refilter()

    def _on_close(self):
        self._save_settings()
        for c in self.connections:
            c.stop()
        self.root.destroy()

    def _load_cty(self):
        def log(text, level="info"):
            self.q.put(("log", text, level))
        try:
            old = (not os.path.exists(CTY_FILE)
                   or time.time() - os.path.getmtime(CTY_FILE) > 30 * 86400)
            if old and not self.demo:
                log("Downloading cty.dat (country list) ...")
                download(CTY_URLS, CTY_FILE, log)
            if os.path.exists(CTY_FILE):
                db = CtyDatabase()
                n = db.load(CTY_FILE)
                self.q.put(("cty", db))
                log("Country list loaded (%d prefixes)." % n, "ok")
            else:
                log("No cty.dat: countries will not be shown.", "err")
        except Exception as e:  # noqa: BLE001
            log("cty.dat problem: %s" % e, "err")

    # ----- incoming data ---------------------------------------------------

    def _poll(self):
        changed = False
        try:
            for _ in range(500):
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "spot":
                    self._add_spot(msg[1])
                    changed = True
                elif kind == "status":
                    _, idx, state, text = msg
                    self.status[idx] = (state, text)
                    self._update_cluster_row(idx)
                elif kind == "log":
                    self._log(msg[1], msg[2])
                elif kind == "cty":
                    self.cty = msg[1]
                    for s in self.spots:
                        s["country"] = self._country(s["call"])
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self._refilter()
        self.root.after(250, self._poll)

    def _country(self, call):
        ent = self.cty.find(call) if self.cty.prefixes else None
        return ent[0] if ent else ""

    def _add_spot(self, sp):
        now = time.time()
        idx = sp["cluster"]
        self.cluster_count[idx] = self.cluster_count.get(idx, 0) + 1
        self._update_cluster_row(idx)
        self.total += 1
        for s in self.spots:
            if now - s["last"] > DEDUP_SECONDS:
                break
            if s["call"] == sp["call"] and abs(s["freq"] - sp["freq"]) <= 1.0:
                # same DX: update it and move it to the top
                if sp["spotter"] not in s["spotters"]:
                    s["spotters"].append(sp["spotter"])
                s["clusters"].add(idx)
                s["last"] = now
                s["freq"] = sp["freq"]
                s["time"] = sp["time"]
                if sp["comment"] and len(sp["comment"]) > 2:
                    s["comment"] = sp["comment"]
                self.spots.remove(s)
                self.spots.insert(0, s)
                return
        sp.update({"spotters": [sp["spotter"]], "clusters": {idx}, "first": now,
                   "last": now, "country": self._country(sp["call"])})
        self.spots.insert(0, sp)
        del self.spots[MAX_SPOTS:]

    def _tick(self):
        self.clock.configure(text=datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
        limit = time.time() - self._keep_minutes() * 60
        n = len(self.spots)
        self.spots = [s for s in self.spots if s["last"] >= limit]
        if len(self.spots) != n:
            self._refilter()
        else:
            self._draw_list()          # new-spot glow fades with time
        self.root.after(1000, self._tick)

    # ----- filtering -------------------------------------------------------

    def _passes(self, s):
        if s["band"] and s["band"] not in self.band_on:
            return False
        if s["mode"] not in self.mode_on:
            return False
        q = self.search_var.get().strip().upper()
        if q and q not in s["call"] and q not in s["country"].upper():
            return False
        return True

    def _refilter(self):
        self.view = [s for s in self.spots if self._passes(s)]
        self.offset = max(0, min(self.offset, len(self.view) - 1))
        self.counter.configure(text="%d spots shown  ·  %d DX stations  ·  %d received"
                               % (len(self.view), len(self.spots), self.total))
        self._draw_bars()
        self._draw_list()

    # ----- band bars + mode chips -----------------------------------------

    def _draw_bars(self):
        cv = self.bars
        cv.delete("all")
        w = cv.winfo_width()
        if w < 50:
            return
        counts = {b: 0 for b in BAND_NAMES}
        mcounts = {m: 0 for m in MODES}
        for s in self.spots:
            if s["band"] in counts:
                counts[s["band"]] += 1
            mcounts[s["mode"]] = mcounts.get(s["mode"], 0) + 1
        top = max(counts.values()) or 1
        n = len(BANDS)
        chips_w = 330
        bw = (w - chips_w - 20) / n
        self.bar_hits = []
        cv.create_text(10, 10, text="BAND ACTIVITY  (click to show / hide)",
                       anchor="nw", fill=DIM, font=(FONT, 8, "bold"))
        for i, (name, _, _, col) in enumerate(BANDS):
            x1 = 10 + i * bw + 3
            x2 = 10 + (i + 1) * bw - 3
            on = name in self.band_on
            base = 88
            h = 46 * counts[name] / top
            round_rect(cv, x1, 30, x2, base, 6, fill=blend(PANEL, col, 0.08), outline="")
            if counts[name]:
                round_rect(cv, x1, base - max(h, 6), x2, base, 6,
                           fill=col if on else blend(PANEL, col, 0.25), outline="")
                cv.create_text((x1 + x2) / 2, base - max(h, 6) - 8, text=str(counts[name]),
                               fill=FG if on else DIM, font=(FONT, 8, "bold"))
            cv.create_text((x1 + x2) / 2, 100, text=name,
                           fill=col if on else "#4a5275", font=(FONT, 10, "bold"))
            self.bar_hits.append((x1, x2, ("band", name)))
        # mode chips
        x0 = w - chips_w
        cv.create_text(x0, 10, text="MODES", anchor="nw", fill=DIM, font=(FONT, 8, "bold"))
        for i, m in enumerate(MODES):
            cx = x0 + (i % 3) * 106
            cy = 30 + (i // 3) * 38
            on = m in self.mode_on
            col = MODE_COLOR[m]
            round_rect(cv, cx, cy, cx + 98, cy + 30, 14,
                       fill=col if on else PANEL2, outline=col, width=2)
            cv.create_text(cx + 12, cy + 15, text=m, anchor="w",
                           fill="#10131f" if on else col, font=(FONT, 10, "bold"))
            cv.create_text(cx + 88, cy + 15, text=str(mcounts.get(m, 0)), anchor="e",
                           fill="#10131f" if on else DIM, font=(FONT, 9))
            self.bar_hits.append((cx, cx + 98, ("mode", m, cy, cy + 30)))

    def _on_bars_click(self, e):
        for x1, x2, what in getattr(self, "bar_hits", []):
            if not x1 <= e.x <= x2:
                continue
            if what[0] == "band" and 25 <= e.y <= 108:
                self._toggle(self.band_on, what[1], BAND_NAMES, e)
            elif what[0] == "mode" and what[2] <= e.y <= what[3]:
                self._toggle(self.mode_on, what[1], MODES, e)
            else:
                continue
            self._save_settings()
            self._refilter()
            return

    @staticmethod
    def _toggle(on_set, item, all_items, event):
        # Ctrl/Shift-click: show only this one (click again for all)
        if event.state & 0x0005:
            if on_set == {item}:
                on_set.update(all_items)
            else:
                on_set.clear()
                on_set.add(item)
        elif item in on_set:
            on_set.discard(item)
        else:
            on_set.add(item)

    # ----- spot list -------------------------------------------------------

    def _columns(self, w):
        # name, x, anchor
        cols = [("UTC", 10, "w"), ("BAND", 66, "w"), ("FREQ", 182, "e"),
                ("DX", 198, "w"), ("MODE", 330, "w"), ("COUNTRY", 400, "w"),
                ("SPOTTED BY", 580, "w"), ("CLUSTERS", 720, "w"),
                ("COMMENT", 800, "w")]
        if w < 900:      # narrow window: no comment column
            cols = cols[:-1]
        return cols

    def _draw_header(self, w):
        hv = self.header
        hv.delete("all")
        for name, x, anchor in self._columns(w):
            hv.create_text(x, 13, text=name, anchor=anchor, fill=ACCENT,
                           font=(FONT, 8, "bold"))

    def _visible_rows(self):
        return max(1, self.list.winfo_height() // ROW_H)

    def _draw_list(self):
        cv = self.list
        w = cv.winfo_width()
        h = cv.winfo_height()
        if w < 50:
            return
        self._draw_header(w)
        cv.delete("all")
        rows = self._visible_rows()
        self.offset = max(0, min(self.offset, max(0, len(self.view) - rows)))
        now = time.time()
        keep = self._keep_minutes() * 60
        cols = dict((c[0], c[1]) for c in self._columns(w))
        if not self.view:
            msg = ("Press Connect to receive spots" if not self.connections
                   else "Waiting for spots ..." if not self.spots
                   else "No spot matches the filters")
            cv.create_text(w / 2, h / 2 - 10, text="📡", fill=DIM, font=(FONT, 28))
            cv.create_text(w / 2, h / 2 + 30, text=msg, fill=DIM, font=(FONT, 13))
        for r in range(rows + 1):
            i = self.offset + r
            if i >= len(self.view):
                break
            s = self.view[i]
            y = r * ROW_H
            yc = y + ROW_H / 2
            bg = ROW_HOVER if self.hover is s else (ROW_A if i % 2 == 0 else ROW_B)
            cv.create_rectangle(0, y, w, y + ROW_H, fill=bg, width=0)
            bcol = BAND_COLOR.get(s["band"], "#888888")
            mcol = MODE_COLOR.get(s["mode"], "#888888")
            age = now - s["last"]
            fresh = max(0.0, 1 - (now - s["first"]) / NEW_SECONDS)
            fade = min(1.0, age / keep) * 0.55          # older = dimmer
            # left colour edge = band colour
            cv.create_rectangle(0, y + 2, 4, y + ROW_H - 2, fill=bcol, width=0)
            if fresh > 0:
                cv.create_rectangle(4, y, w, y + ROW_H, width=0,
                                    fill=blend(bg, "#3a3410", fresh))
            txt = blend(FG, bg, fade)
            dim = blend(DIM, bg, fade)
            cv.create_text(cols["UTC"], yc, text=s["time"] + "z", anchor="w",
                           fill=dim, font=(MONO, 10))
            round_rect(cv, cols["BAND"], y + 6, cols["BAND"] + 50, y + ROW_H - 6, 9,
                       fill=blend(bcol, bg, fade), outline="")
            cv.create_text(cols["BAND"] + 25, yc, text=s["band"] or "?",
                           fill="#10131f", font=(FONT, 9, "bold"))
            cv.create_text(cols["FREQ"], yc, text="%.1f" % s["freq"], anchor="e",
                           fill=blend(bcol, bg, fade), font=(MONO, 11, "bold"))
            call_col = blend(FG, NEW_GLOW, fresh) if fresh > 0 else txt
            cv.create_text(cols["DX"], yc, text=s["call"], anchor="w",
                           fill=call_col, font=(FONT, 12, "bold"))
            round_rect(cv, cols["MODE"], y + 6, cols["MODE"] + 54, y + ROW_H - 6, 9,
                       fill=bg, outline=blend(mcol, bg, fade), width=2)
            cv.create_text(cols["MODE"] + 27, yc, text=s["mode"],
                           fill=blend(mcol, bg, fade), font=(FONT, 9, "bold"))
            cv.create_text(cols["COUNTRY"], yc, text=s["country"][:24], anchor="w",
                           fill=txt, font=(FONT, 10))
            sp = s["spotters"]
            who = sp[-1] + ("  +%d" % (len(sp) - 1) if len(sp) > 1 else "")
            cv.create_text(cols["SPOTTED BY"], yc, text=who, anchor="w",
                           fill=dim, font=(FONT, 10))
            for k, ci in enumerate(sorted(s["clusters"])[:6]):
                x = cols["CLUSTERS"] + k * 12
                cv.create_oval(x, yc - 5, x + 10, yc + 5, width=0,
                               fill=blend(self._cluster_color(ci), bg, fade))
            if "COMMENT" in cols:
                cv.create_text(cols["COMMENT"], yc, text=s["comment"][:60], anchor="w",
                               fill=dim, font=(FONT, 9, "italic"))
        # scrollbar
        if self.view:
            first = self.offset / len(self.view)
            last = min(1.0, (self.offset + rows) / len(self.view))
            self.sb.set(first, last)
        else:
            self.sb.set(0, 1)

    def _scroll(self, n):
        self.offset += n
        self._draw_list()

    def _on_wheel(self, e):
        self._scroll(-3 if e.delta > 0 else 3)

    def _on_scrollbar(self, *args):
        rows = self._visible_rows()
        if args[0] == "moveto":
            self.offset = int(float(args[1]) * len(self.view))
        elif args[0] == "scroll":
            step = rows if args[2] == "pages" else 1
            self.offset += int(args[1]) * step
        self._draw_list()

    def _spot_at(self, y):
        i = self.offset + int(y // ROW_H)
        return self.view[i] if 0 <= i < len(self.view) else None

    def _set_hover(self, s):
        if s is not self.hover:
            self.hover = s
            self.list.configure(cursor="hand2" if s else "")
            self._draw_list()

    def _on_motion(self, e):
        s = self._spot_at(e.y)
        self._set_hover(s)
        if s:
            names = ", ".join(self.clusters[i]["name"] for i in sorted(s["clusters"])
                              if i < len(self.clusters))
            self.root.title("%s  -  %s %.1f %s  ·  spotted by %s  ·  via %s" % (
                APP_NAME, s["call"], s["freq"], s["mode"],
                ", ".join(s["spotters"][-6:]), names))

    def _on_click(self, e):
        s = self._spot_at(e.y)
        if s:
            webbrowser.open("https://www.qrz.com/db/%s" % home_call(s["call"]))


def main():
    root = tk.Tk()
    DxClusterBoard(root, demo="--demo" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
