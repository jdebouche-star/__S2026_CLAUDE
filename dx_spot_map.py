#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DX Spot Map
===========
Live DX spots from the Reverse Beacon Network (RBN) and a DX cluster you pick,
shown as coloured dots on a world map.

  * RBN CW/RTTY (port 7000) and RBN FT8/FT4 (port 7001) telnet feeds
  * Any telnet DX cluster (DXSpider, AR-Cluster, CC-Cluster, ...)
  * Optional QRZ.com XML lookup of every spotted call, with an SQLite cache
    so the same call is not looked up over and over
  * Filters: band, mode, DX call, spotter call
  * Spots older than N minutes are removed automatically
  * Hover over a dot: DX call, spotters, frequency, mode, QRZ data, and
    great-circle paths from every spotter
  * Click a dot (or double-click a row in the list) to open the QRZ.com page

Only the Python standard library is used (tkinter, sqlite3, socket, urllib),
so it runs as-is in Thonny on Windows: open the file and press F5.

On first start two data files are downloaded next to this script:
  * cty.dat                 (country / prefix file from country-files.com)
  * world_countries.geojson (Natural Earth country outlines)
If your PC has no internet access for those, download them manually and
place them in the same folder as this script.
"""

import fnmatch
import json
import math
import os
import queue
import re
import socket
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone

import tkinter as tk
from tkinter import messagebox, ttk

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_NAME = "DX Spot Map"
APP_VERSION = "1.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "dxspotmap_cache.sqlite")
CTY_FILE = os.path.join(APP_DIR, "cty.dat")
MAP_FILE = os.path.join(APP_DIR, "world_countries.geojson")

CTY_URLS = [
    "https://www.country-files.com/cty/cty.dat",
    "https://www.country-files.com/bigcty/cty.dat",
]
MAP_URLS = [
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson",
]
QRZ_URL = "https://xmldata.qrz.com/xml/current/"
HTTP_AGENT = "Mozilla/5.0 (DXSpotMap %s)" % APP_VERSION
QRZ_AGENT = "DXSpotMap%s" % APP_VERSION

RBN_HOST = "telnet.reversebeacon.net"
RBN_PORT_CW = 7000      # CW + RTTY skimmers
RBN_PORT_DIGI = 7001    # FT8 + FT4

# A few well known public DX clusters (the box is editable: host:port)
DX_CLUSTERS = [
    "dxc.ve7cc.net:23",
    "w3lpl.net:7373",
    "dxc.nc7j.com:7373",
    "gb7djk.dxcluster.net:7300",
    "cluster.dl9gtb.de:8000",
    "dxfun.com:8000",
]

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
# Only used when a cluster spot does not say which mode it is.
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

# Map look
OCEAN = "#0a1a33"
GRID = "#1f3558"
COUNTRY_COLORS = ["#2f6b4f", "#6b5a35", "#435a8c", "#7a4661", "#56793a",
                  "#3b6f7c", "#674c8a"]
LAT_MAX, LAT_MIN = 84.0, -60.0   # Antarctica is not interesting for DX maps

MAX_SPOTS = 6000        # safety limit for the in-memory spot table
MAX_TREE_ROWS = 800     # rows kept in the list below the map

CALL_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "QRPP", "A", "B", "R", "LH",
                 "J", "E", "PM", "LGT", "BCN", "N", "T", "X"}
CALL_RE = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9/]{3,15}$")

SPOT_RE = re.compile(
    r"^DX de\s+([^\s:]+):?\s+(\d+(?:\.\d+)?)\s+([A-Za-z0-9/]+)\s+(.*)\s(\d{4})Z")


# ---------------------------------------------------------------------------
# Small helpers
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


def rbn_mode(word):
    word = (word or "").upper()
    if word in ("CW", "RTTY", "FT8", "FT4"):
        return word
    return "DIGI"


def grid_to_latlon(grid):
    """Maidenhead locator (4 or 6 chars) -> centre lat, lon."""
    g = (grid or "").strip().upper()
    if len(g) < 4 or not re.match(r"^[A-R]{2}\d{2}([A-X]{2})?", g):
        return None
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) >= 6 and re.match(r"^[A-X]{2}$", g[4:6]):
        lon += (ord(g[4]) - 65) * (2.0 / 24) + 1.0 / 24
        lat += (ord(g[5]) - 65) * (1.0 / 24) + 0.5 / 24
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def clean_spotter(raw):
    """'KM3T-2-#' -> 'KM3T', 'DL1ABC-7' -> 'DL1ABC'."""
    s = raw.upper().rstrip(":")
    s = s.replace("-#", "")
    s = re.sub(r"-\d+$", "", s)
    return s


def _looks_like_call(p):
    return bool(re.match(r"^[A-Z0-9]{1,3}\d[A-Z]{1,5}$", p))


def home_call(call):
    """The station's own call: 'EA8/ON4XX/P' -> 'ON4XX'."""
    parts = [p for p in call.upper().split("/") if p]
    if not parts:
        return call.upper()
    if len(parts) == 1:
        return parts[0]
    cands = [p for p in parts
             if p not in CALL_SUFFIXES and not (len(p) == 1 and p.isdigit())]
    if not cands:
        return parts[0]
    return max(cands, key=lambda p: (_looks_like_call(p), len(p)))


def location_prefix(call):
    """The part that tells where the station is: 'EA8/ON4XX' -> 'EA8'.
    Returns None for maritime / aeronautical mobile (no fixed location)."""
    parts = [p for p in call.upper().split("/") if p]
    if "MM" in parts or "AM" in parts:
        return None
    hc = home_call(call)
    others = [p for p in parts if p != hc and p not in CALL_SUFFIXES]
    if not others:
        return hc
    o = others[0]
    if len(o) == 1 and o.isdigit():
        return hc                       # K1ABC/4: same country
    return o


def utc_now():
    return datetime.now(timezone.utc)


def gc_segments(lat1, lon1, lat2, lon2, n=48):
    """Great circle between two points as list of (lat, lon) segments,
    split at the date line."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(min(1.0, math.sqrt(
        math.sin((p2 - p1) / 2) ** 2 +
        math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)))
    if d < 1e-4 or abs(math.sin(d)) < 1e-6:
        return []
    pts = []
    for i in range(n + 1):
        f = i / n
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        pts.append((math.degrees(math.atan2(z, math.hypot(x, y))),
                    math.degrees(math.atan2(y, x))))
    segs, cur = [], [pts[0]]
    for p in pts[1:]:
        if abs(p[1] - cur[-1][1]) > 180:
            segs.append(cur)
            cur = []
        cur.append(p)
    segs.append(cur)
    return [s for s in segs if len(s) >= 2]


def download(urls, path, label, log):
    for url in urls:
        try:
            log("Downloading %s from %s ..." % (label, url))
            req = urllib.request.Request(url, headers={"User-Agent": HTTP_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 1000:
                raise ValueError("file too small")
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            log("%s downloaded (%d kB)" % (label, len(data) // 1024))
            return True
        except Exception as e:  # noqa: BLE001 - report and try next URL
            log("Download of %s failed: %s" % (label, e), "err")
    return False


# ---------------------------------------------------------------------------
# cty.dat: prefix -> country, lat/lon
# ---------------------------------------------------------------------------

class CtyDatabase:
    OVERRIDES = re.compile(r"\(.*?\)|\[.*?\]|<.*?>|\{.*?\}|~.*?~")
    LATLON = re.compile(r"<\s*([-\d.]+)\s*/\s*([-\d.]+)\s*>")

    def __init__(self):
        self.prefixes = {}
        self.exact = {}
        self.loaded = False

    def load(self, path):
        with open(path, "r", encoding="latin-1") as f:
            text = f.read()
        for record in text.split(";"):
            fields = record.split(":")
            if len(fields) < 9:
                continue
            try:
                name = fields[0].strip()
                cq = int(fields[1])
                cont = fields[3].strip()
                lat = float(fields[4])
                lon = -float(fields[5])        # cty.dat: west is positive
            except ValueError:
                continue
            for item in ":".join(fields[8:]).split(","):
                item = item.strip()
                if not item:
                    continue
                elat, elon = lat, lon
                m = self.LATLON.search(item)
                if m:
                    elat, elon = float(m.group(1)), -float(m.group(2))
                p = self.OVERRIDES.sub("", item).strip()
                entity = (name, elat, elon, cont, cq)
                if p.startswith("="):
                    self.exact[p[1:]] = entity
                elif p:
                    self.prefixes[p] = entity
        self.loaded = bool(self.prefixes)
        return len(self.prefixes)

    def find(self, call, loc_prefix):
        call = call.upper()
        if call in self.exact:
            return self.exact[call]
        if not loc_prefix:
            return None
        if loc_prefix in self.exact:
            return self.exact[loc_prefix]
        for i in range(len(loc_prefix), 0, -1):
            ent = self.prefixes.get(loc_prefix[:i])
            if ent:
                return ent
        return None


# ---------------------------------------------------------------------------
# SQLite cache for QRZ lookups (+ settings)
# ---------------------------------------------------------------------------

class CallCache:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("""CREATE TABLE IF NOT EXISTS qrz_cache (
                call TEXT PRIMARY KEY, found INTEGER, name TEXT,
                country TEXT, grid TEXT, lat REAL, lon REAL, dxcc TEXT,
                state TEXT, fetched REAL)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT)""")
            self.db.commit()

    def get(self, call, ttl_days, negative_ttl_days=3):
        with self.lock:
            row = self.db.execute(
                "SELECT found, name, country, grid, lat, lon, dxcc, state, "
                "fetched FROM qrz_cache WHERE call=?", (call,)).fetchone()
        if not row:
            return None
        found = bool(row[0])
        ttl = ttl_days if found else min(ttl_days, negative_ttl_days)
        if time.time() - row[8] > ttl * 86400:
            return None
        return {"found": found, "name": row[1], "country": row[2],
                "grid": row[3], "lat": row[4], "lon": row[5],
                "dxcc": row[6], "state": row[7], "fetched": row[8]}

    def put(self, call, info):
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO qrz_cache VALUES (?,?,?,?,?,?,?,?,?,?)",
                (call, int(info["found"]), info.get("name"),
                 info.get("country"), info.get("grid"), info.get("lat"),
                 info.get("lon"), info.get("dxcc"), info.get("state"),
                 time.time()))
            self.db.commit()

    def count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM qrz_cache").fetchone()[0]

    def purge_expired(self, ttl_days):
        with self.lock:
            cur = self.db.execute("DELETE FROM qrz_cache WHERE fetched < ?",
                                  (time.time() - ttl_days * 86400,))
            self.db.commit()
            return cur.rowcount

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM qrz_cache")
            self.db.commit()

    def get_setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?",
                                  (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return default

    def set_setting(self, key, value):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                            (key, json.dumps(value)))
            self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()


# ---------------------------------------------------------------------------
# QRZ.com XML client + background lookup worker
# ---------------------------------------------------------------------------

class QrzError(Exception):
    pass


class QrzLoginError(QrzError):
    pass


class QrzClient:
    def __init__(self, user, password):
        self.user = user
        self.password = password
        self.key = None
        self.session_info = {}

    @staticmethod
    def _request(params):
        url = QRZ_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": HTTP_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        root = ET.fromstring(data)
        out = {"Callsign": {}, "Session": {}}
        for section in root:
            tag = section.tag.split("}")[-1]
            if tag in out:
                for child in section:
                    out[tag][child.tag.split("}")[-1]] = (child.text or "").strip()
        return out

    def login(self):
        res = self._request({"username": self.user, "password": self.password,
                             "agent": QRZ_AGENT})
        sess = res["Session"]
        if not sess.get("Key"):
            raise QrzLoginError(sess.get("Error") or "QRZ login failed")
        self.key = sess["Key"]
        self.session_info = sess
        return sess

    def lookup(self, call, _retry=True):
        if not self.key:
            self.login()
        res = self._request({"s": self.key, "callsign": call})
        sess, cs = res["Session"], res["Callsign"]
        err = sess.get("Error", "")
        if cs.get("call"):
            lat = lon = None
            try:
                lat, lon = float(cs.get("lat")), float(cs.get("lon"))
            except (TypeError, ValueError):
                pass
            name = " ".join(x for x in (cs.get("fname", ""), cs.get("name", ""))
                            if x).strip()
            return {"found": True, "name": name,
                    "country": cs.get("country") or cs.get("land") or "",
                    "grid": cs.get("grid", ""), "lat": lat, "lon": lon,
                    "dxcc": cs.get("dxcc", ""), "state": cs.get("state", "")}
        if err.lower().startswith("not found"):
            return {"found": False, "name": "", "country": "", "grid": "",
                    "lat": None, "lon": None, "dxcc": "", "state": ""}
        if _retry and ("session" in err.lower() or "key" in err.lower()
                       or not sess.get("Key")):
            self.key = None
            return self.lookup(call, _retry=False)
        raise QrzError(err or "unknown QRZ answer")


class QrzWorker(threading.Thread):
    """Looks calls up on QRZ.com one by one (never twice at the same time)
    and stores the result in the SQLite cache."""

    def __init__(self, cache, out_q):
        super().__init__(daemon=True)
        self.cache = cache
        self.out_q = out_q
        self.in_q = queue.Queue()
        self.pending = set()
        self.lock = threading.Lock()
        self.client = None
        self.stop_event = threading.Event()
        self.lookups = 0
        self.errors = 0

    def set_credentials(self, user, password):
        with self.lock:
            self.client = QrzClient(user, password) if user and password else None

    def enabled(self):
        return self.client is not None

    def submit(self, call):
        with self.lock:
            if self.client is None or call in self.pending:
                return
            if len(self.pending) > 3000:      # do not build an endless backlog
                return
            self.pending.add(call)
        self.in_q.put(call)

    def is_pending(self, call):
        with self.lock:
            return call in self.pending

    def backlog(self):
        return self.in_q.qsize()

    def run(self):
        while not self.stop_event.is_set():
            try:
                call = self.in_q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                client = self.client
                if client is None:
                    continue
                try:
                    info = client.lookup(call)
                except QrzLoginError as e:
                    self.out_q.put(("log", "QRZ login refused: %s - QRZ lookups "
                                    "disabled until you connect again" % e, "err"))
                    with self.lock:
                        self.client = None
                        self.pending.clear()
                    continue
                except (QrzError, OSError, ET.ParseError) as e:
                    self.errors += 1
                    self.out_q.put(("log", "QRZ lookup %s failed: %s" % (call, e),
                                    "err"))
                    self.stop_event.wait(5)
                    continue
                self.lookups += 1
                info["fetched"] = time.time()
                self.cache.put(call, info)
                self.out_q.put(("qrz", call, info))
            finally:
                with self.lock:
                    self.pending.discard(call)
            self.stop_event.wait(0.2)     # be polite to QRZ


# ---------------------------------------------------------------------------
# Telnet spot sources (RBN and DX cluster)
# ---------------------------------------------------------------------------

def parse_spot_line(line, source):
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
    comment = comment.strip()
    snr = ""
    if source == "RBN":
        words = comment.split()
        mode = rbn_mode(words[0] if words else "")
        ms = re.search(r"(-?\d+)\s*dB", comment)
        mw = re.search(r"(\d+)\s*(WPM|BPS)", comment)
        snr = (ms.group(1) + " dB" if ms else "") + \
              ("  " + mw.group(1) + " " + mw.group(2).lower() if mw else "")
    else:
        mode = infer_mode(khz, band, comment)
    return {"src": source, "spotter": clean_spotter(spotter), "freq": khz,
            "call": call, "band": band, "mode": mode, "comment": comment,
            "snr": snr.strip(), "time": hhmm}


class TelnetSpotSource(threading.Thread):
    IAC, DONT, DO, WONT, WILL = 255, 254, 253, 252, 251

    def __init__(self, name, host, port, callsign, out_q, source):
        super().__init__(daemon=True)
        self.name_ = name
        self.host = host
        self.port = port
        self.callsign = callsign
        self.out_q = out_q
        self.source = source
        self.stop_event = threading.Event()
        self.sock = None

    def log(self, text, level="info"):
        self.out_q.put(("log", "[%s] %s" % (self.name_, text), level))

    def status(self, text):
        self.out_q.put(("status", self.name_, text))

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
                    opt = data[i + 2]
                    try:
                        if cmd == self.DO:
                            self.sock.sendall(bytes([self.IAC, self.WONT, opt]))
                        elif cmd == self.WILL:
                            self.sock.sendall(bytes([self.IAC, self.DONT, opt]))
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
                self.status("connecting")
                self.log("connecting to %s:%d" % (self.host, self.port))
                self.sock = socket.create_connection((self.host, self.port), timeout=20)
                self.sock.settimeout(1.0)
                self.status("connected")
                self.log("connected", "ok")
                self._session()
                delay = 5
            except OSError as e:
                if not self.stop_event.is_set():
                    self.log("connection problem: %s" % e, "err")
            finally:
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
            if self.stop_event.is_set():
                break
            self.status("reconnect in %ds" % delay)
            self.stop_event.wait(delay)
            delay = min(delay * 2, 120)
        self.status("off")

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
                if line.startswith("DX de"):
                    spot = parse_spot_line(line, self.source)
                    if spot:
                        spots += 1
                        if spots == 1:
                            self.status("receiving spots")
                        self.out_q.put(("spot", spot))
                elif info_lines < 8:
                    info_lines += 1
                    self.log(line[:120], "dim")
            if len(buf) > 65536:       # no newline for a long time: drop it
                buf = b""


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------

class DxSpotMapApp:
    def __init__(self, root):
        self.root = root
        root.title("%s %s" % (APP_NAME, APP_VERSION))
        self.cache = CallCache(DB_FILE)
        self.settings = self.cache.get_setting("settings", {}) or {}
        root.geometry(self.settings.get("geometry", "1400x900"))

        self.gui_q = queue.Queue()
        self.cty = CtyDatabase()
        self.countries = []         # (colour, [ring, ...]) ring = [(lon,lat),..]
        self.map_failed = False
        self.qrz = QrzWorker(self.cache, self.gui_q)
        self.qrz.start()
        self.sources = []
        self.source_status = {}

        self.spots = {}             # (call, band) -> spot dict
        self.id_map = {}            # canvas id -> key
        self.next_id = 1
        self.info = {}              # home call -> QRZ info (from cache/QRZ)
        self.cache_missed = set()   # calls not in the cache (already checked)
        self.spotter_loc = {}
        self.cache_hits = 0
        self.spots_rx = 0
        self.cache_count = self.cache.count()
        self.flt = {}
        self._refresh_job = None
        self._resize_job = None
        self.scale = 0

        self._build_ui()
        self._update_filter()
        threading.Thread(target=self._load_data, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(150, self._poll_queue)
        root.after(10000, self._purge_tick)
        root.after(60000, self._night_tick)
        root.after(1000, self._status_tick)

    # ----- settings --------------------------------------------------------

    def _s(self, key, default):
        return self.settings.get(key, default)

    def _save_settings(self):
        s = {
            "geometry": self.root.geometry(),
            "mycall": self.v_mycall.get().strip().upper(),
            "rbn_cw": self.v_rbn_cw.get(), "rbn_digi": self.v_rbn_digi.get(),
            "use_cluster": self.v_use_cluster.get(),
            "cluster": self.v_cluster.get().strip(),
            "qrz_user": self.v_qrz_user.get().strip(),
            "qrz_pass": self.v_qrz_pass.get(),
            "cache_days": self._int(self.v_cache_days, 30),
            "qrz_rbn": self.v_qrz_rbn.get(),
            "bands": [b for b, v in self.v_bands.items() if v.get()],
            "modes": [m for m, v in self.v_modes.items() if v.get()],
            "dx_filter": self.v_dx_filter.get(),
            "spotter_filter": self.v_spotter_filter.get(),
            "max_age": self._int(self.v_max_age, 15),
            "qrz_only": self.v_qrz_only.get(),
            "color_by": self.v_color_by.get(),
        }
        self.settings = s
        self.cache.set_setting("settings", s)

    @staticmethod
    def _int(var, default):
        try:
            return max(1, int(var.get()))
        except (ValueError, tk.TclError):
            return default

    # ----- UI --------------------------------------------------------------

    def _build_ui(self):
        root = self.root
        root.configure(bg="#101826")
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg, fg = "#101826", "#e6edf7"
        style.configure(".", background=bg, foreground=fg, fieldbackground="#1b2638")
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, foreground="#7fd4ff")
        style.configure("TLabelframe.Label", background=bg, foreground="#7fd4ff",
                        font=("Segoe UI", 9, "bold"))
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", "#1b2638")])
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.map("TRadiobutton", background=[("active", "#1b2638")])
        style.configure("TEntry", fieldbackground="#1b2638", foreground="#ffffff",
                        insertcolor="#ffffff")
        style.configure("TCombobox", fieldbackground="#1b2638", foreground="#ffffff")
        style.configure("Treeview", background="#0e1622", fieldbackground="#0e1622",
                        foreground=fg, rowheight=20, font=("Consolas", 9))
        style.configure("Treeview.Heading", background="#22324a", foreground="#ffd84d",
                        font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#2d4a7a")])
        style.configure("TButton", background="#22324a", foreground=fg)

        # --- connection row ---
        conn = ttk.LabelFrame(root, text=" Connections ")
        conn.pack(fill="x", padx=6, pady=(6, 2))
        self.v_mycall = tk.StringVar(value=self._s("mycall", ""))
        self.v_rbn_cw = tk.BooleanVar(value=self._s("rbn_cw", True))
        self.v_rbn_digi = tk.BooleanVar(value=self._s("rbn_digi", False))
        self.v_use_cluster = tk.BooleanVar(value=self._s("use_cluster", True))
        self.v_cluster = tk.StringVar(value=self._s("cluster", DX_CLUSTERS[0]))
        ttk.Label(conn, text="My call:").pack(side="left", padx=(6, 2))
        ttk.Entry(conn, textvariable=self.v_mycall, width=10).pack(side="left")
        ttk.Checkbutton(conn, text="RBN CW/RTTY", variable=self.v_rbn_cw).pack(side="left", padx=(12, 2))
        ttk.Checkbutton(conn, text="RBN FT8/FT4", variable=self.v_rbn_digi).pack(side="left", padx=2)
        ttk.Checkbutton(conn, text="DX cluster:", variable=self.v_use_cluster).pack(side="left", padx=(12, 2))
        ttk.Combobox(conn, textvariable=self.v_cluster, values=DX_CLUSTERS,
                     width=28).pack(side="left")
        self.btn_connect = tk.Button(conn, text="  Connect  ", command=self._toggle_connect,
                                     bg="#1fa35c", fg="white", activebackground="#27c46f",
                                     font=("Segoe UI", 9, "bold"), relief="flat")
        self.btn_connect.pack(side="left", padx=12, pady=4)

        # QRZ
        qrzf = ttk.LabelFrame(root, text=" QRZ.com cross-check (optional) ")
        qrzf.pack(fill="x", padx=6, pady=2)
        self.v_qrz_user = tk.StringVar(value=self._s("qrz_user", ""))
        self.v_qrz_pass = tk.StringVar(value=self._s("qrz_pass", ""))
        self.v_cache_days = tk.StringVar(value=str(self._s("cache_days", 30)))
        self.v_qrz_rbn = tk.BooleanVar(value=self._s("qrz_rbn", True))
        ttk.Label(qrzf, text="QRZ user:").pack(side="left", padx=(6, 2))
        ttk.Entry(qrzf, textvariable=self.v_qrz_user, width=10).pack(side="left")
        ttk.Label(qrzf, text="password:").pack(side="left", padx=(6, 2))
        ttk.Entry(qrzf, textvariable=self.v_qrz_pass, width=10, show="*").pack(side="left")
        ttk.Label(qrzf, text="cache days:").pack(side="left", padx=(6, 2))
        tk.Spinbox(qrzf, from_=1, to=365, width=4, textvariable=self.v_cache_days,
                   bg="#1b2638", fg="white", buttonbackground="#22324a",
                   insertbackground="white").pack(side="left")
        ttk.Checkbutton(qrzf, text="also check RBN spots (uses more lookups)", variable=self.v_qrz_rbn).pack(side="left", padx=6)
        tk.Button(qrzf, text="Test QRZ", command=self._test_qrz, bg="#3a5fd6", fg="white",
                  activebackground="#4d74f0", relief="flat").pack(side="left", padx=4, pady=3)
        ttk.Label(qrzf, text="dot outline: white = on QRZ, red = not found, "
                  "black = unchecked").pack(side="left", padx=12)

        # --- filter rows ---
        flt = ttk.LabelFrame(root, text=" Filters ")
        flt.pack(fill="x", padx=6, pady=2)
        row1 = ttk.Frame(flt)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Bands:").pack(side="left", padx=(6, 4))
        saved_bands = self._s("bands", [b[0] for b in BANDS])
        self.v_bands = {}
        for name, _, _, color in BANDS:
            v = tk.BooleanVar(value=name in saved_bands)
            v.trace_add("write", self._filter_changed)
            self.v_bands[name] = v
            tk.Checkbutton(row1, text=name, variable=v, bg=color, fg="black",
                           selectcolor="white", activebackground=color,
                           font=("Segoe UI", 9, "bold"), relief="flat",
                           padx=3).pack(side="left", padx=1)
        tk.Button(row1, text="all", command=lambda: self._set_all(self.v_bands, True),
                  bg="#22324a", fg="white", relief="flat").pack(side="left", padx=(6, 1))
        tk.Button(row1, text="none", command=lambda: self._set_all(self.v_bands, False),
                  bg="#22324a", fg="white", relief="flat").pack(side="left", padx=1)

        row2 = ttk.Frame(flt)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Modes:").pack(side="left", padx=(6, 4))
        saved_modes = self._s("modes", MODES)
        self.v_modes = {}
        for m in MODES:
            v = tk.BooleanVar(value=m in saved_modes)
            v.trace_add("write", self._filter_changed)
            self.v_modes[m] = v
            tk.Checkbutton(row2, text=m, variable=v, bg=MODE_COLOR[m], fg="black",
                           selectcolor="white", activebackground=MODE_COLOR[m],
                           font=("Segoe UI", 9, "bold"), relief="flat",
                           padx=3).pack(side="left", padx=1)

        self.v_dx_filter = tk.StringVar(value=self._s("dx_filter", ""))
        self.v_spotter_filter = tk.StringVar(value=self._s("spotter_filter", ""))
        self.v_max_age = tk.StringVar(value=str(self._s("max_age", 15)))
        self.v_qrz_only = tk.BooleanVar(value=self._s("qrz_only", False))
        self.v_color_by = tk.StringVar(value=self._s("color_by", "band"))
        for v in (self.v_dx_filter, self.v_spotter_filter, self.v_qrz_only,
                  self.v_color_by, self.v_max_age):
            v.trace_add("write", self._filter_changed)
        ttk.Label(row2, text="DX call:").pack(side="left", padx=(14, 2))
        ttk.Entry(row2, textvariable=self.v_dx_filter, width=14).pack(side="left")
        ttk.Label(row2, text="Spotter:").pack(side="left", padx=(8, 2))
        ttk.Entry(row2, textvariable=self.v_spotter_filter, width=14).pack(side="left")
        ttk.Label(row2, text="Keep (min):").pack(side="left", padx=(8, 2))
        tk.Spinbox(row2, from_=1, to=240, width=4, textvariable=self.v_max_age,
                   bg="#1b2638", fg="white", buttonbackground="#22324a",
                   insertbackground="white").pack(side="left")
        ttk.Checkbutton(row2, text="QRZ-confirmed only",
                        variable=self.v_qrz_only).pack(side="left", padx=8)
        ttk.Label(row2, text="Colour by:").pack(side="left", padx=(8, 2))
        ttk.Radiobutton(row2, text="band", value="band", variable=self.v_color_by).pack(side="left")
        ttk.Radiobutton(row2, text="mode", value="mode", variable=self.v_color_by).pack(side="left")

        # --- map + list ---
        paned = tk.PanedWindow(root, orient="vertical", bg="#101826", sashwidth=6,
                               sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=6, pady=2)
        self.canvas = tk.Canvas(paned, bg=OCEAN, highlightthickness=0, cursor="crosshair")
        paned.add(self.canvas, minsize=250, stretch="always")
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.tag_bind("spot", "<Enter>", self._on_spot_enter)
        self.canvas.tag_bind("spot", "<Leave>", lambda e: self.canvas.delete("hover"))
        self.canvas.tag_bind("spot", "<Button-1>", self._on_spot_click)

        bottom = tk.Frame(paned, bg="#101826")
        paned.add(bottom, minsize=120, height=220)
        cols = ("time", "dx", "freq", "band", "mode", "spotter", "n", "country",
                "qrz", "src", "comment")
        widths = (50, 90, 75, 45, 50, 90, 30, 150, 45, 60, 220)
        self.tree = ttk.Treeview(bottom, columns=cols, show="headings", height=8)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c.upper() if c != "n" else "#")
            self.tree.column(c, width=w, anchor="w", stretch=(c == "comment"))
        for name, _, _, color in BANDS:
            self.tree.tag_configure("b_" + name, foreground=color)
        for m, color in MODE_COLOR.items():
            self.tree.tag_configure("m_" + m, foreground=color)
        sb = ttk.Scrollbar(bottom, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._on_tree_double)
        self.log_text = tk.Text(bottom, width=58, bg="#0b111b", fg="#9fb3c8",
                                font=("Consolas", 8), relief="flat", wrap="none")
        self.log_text.tag_configure("err", foreground="#ff6b6b")
        self.log_text.tag_configure("ok", foreground="#5dff9d")
        self.log_text.tag_configure("dim", foreground="#5c6f86")
        self.log_text.tag_configure("info", foreground="#9fd8ff")
        self.log_text.pack(side="right", fill="y")
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.status = tk.Label(root, anchor="w", bg="#0b111b", fg="#ffd84d",
                               font=("Consolas", 9))
        self.status.pack(fill="x", side="bottom")

    @staticmethod
    def _set_all(vars_, value):
        for v in vars_.values():
            v.set(value)

    def _log(self, text, level="info"):
        stamp = utc_now().strftime("%H:%M:%S ")
        self.log_text.insert("end", stamp + text + "\n", level)
        if int(self.log_text.index("end-1c").split(".")[0]) > 500:
            self.log_text.delete("1.0", "100.0")
        self.log_text.see("end")

    # ----- data files ------------------------------------------------------

    def _load_data(self):
        def log(text, level="info"):
            self.gui_q.put(("log", text, level))

        def stale(path, days):
            return (not os.path.exists(path)
                    or time.time() - os.path.getmtime(path) > days * 86400)

        if stale(CTY_FILE, 30):
            download(CTY_URLS, CTY_FILE, "cty.dat", log)
        if os.path.exists(CTY_FILE):
            cty = CtyDatabase()
            try:
                n = cty.load(CTY_FILE)
                self.gui_q.put(("cty", cty))
                log("cty.dat loaded: %d prefixes, %d exact calls" % (n, len(cty.exact)), "ok")
            except OSError as e:
                log("cty.dat could not be read: %s" % e, "err")
        else:
            log("No cty.dat - spots can only be placed with QRZ data. Download "
                "it from country-files.com and put it next to this script.", "err")

        if not os.path.exists(MAP_FILE):
            download(MAP_URLS, MAP_FILE, "world map", log)
        countries = []
        try:
            with open(MAP_FILE, "r", encoding="utf-8") as f:
                gj = json.load(f)
            for feat in gj.get("features", []):
                props = {k.upper(): v for k, v in (feat.get("properties") or {}).items()}
                if str(props.get("NAME", "")).startswith("Antarctica"):
                    continue
                geom = feat.get("geometry") or {}
                polys = geom.get("coordinates") or []
                if geom.get("type") == "Polygon":
                    polys = [polys]
                elif geom.get("type") != "MultiPolygon":
                    continue
                try:
                    idx = int(props.get("MAPCOLOR7", 0)) % len(COUNTRY_COLORS)
                except (TypeError, ValueError):
                    idx = zlib.crc32(str(props.get("NAME")).encode()) % len(COUNTRY_COLORS)
                rings = [[(p[0], p[1]) for p in poly[0]] for poly in polys if poly]
                countries.append((COUNTRY_COLORS[idx], rings))
            self.gui_q.put(("map", countries))
        except (OSError, ValueError) as e:
            log("World map not available (%s) - showing grid only" % e, "err")
            self.gui_q.put(("map", []))

    # ----- projection & map drawing ---------------------------------------

    def _on_resize(self, _event):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(150, self._redraw_all)

    def _compute_projection(self):
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        span = LAT_MAX - LAT_MIN
        self.scale = min(w / 360.0, h / span)
        self.ox = (w - 360 * self.scale) / 2
        self.oy = (h - span * self.scale) / 2

    def _xy(self, lat, lon):
        lat = max(LAT_MIN, min(LAT_MAX, lat))
        return (self.ox + (lon + 180) * self.scale,
                self.oy + (LAT_MAX - lat) * self.scale)

    def _redraw_all(self):
        self._resize_job = None
        c = self.canvas
        c.delete("all")
        self._compute_projection()
        x0, y0 = self._xy(LAT_MAX, -180)
        x1, y1 = self._xy(LAT_MIN, 180)
        c.create_rectangle(x0, y0, x1, y1, fill=OCEAN, outline="#2b4a78", tags="map")
        for color, rings in self.countries:
            for ring in rings:
                pts = []
                for lon, lat in ring:
                    pts.extend(self._xy(lat, lon))
                if len(pts) >= 6:
                    c.create_polygon(pts, fill=color, outline="#0d2140", tags="map")
        for lon in range(-180, 181, 30):
            xa, ya = self._xy(LAT_MAX, lon)
            xb, yb = self._xy(LAT_MIN, lon)
            c.create_line(xa, ya, xb, yb, fill=GRID, dash=(2, 4), tags="map")
            c.create_text(xa + 2, ya + 2, text="%d°" % lon, anchor="nw",
                          fill="#4f6d99", font=("Segoe UI", 7), tags="map")
        for lat in range(-60, 90, 30):
            xa, ya = self._xy(lat, -180)
            xb, yb = self._xy(lat, 180)
            c.create_line(xa, ya, xb, yb, fill=GRID if lat else "#2f5487",
                          dash=(2, 4), tags="map")
            c.create_text(xa + 2, ya - 1, text="%d°" % lat, anchor="sw",
                          fill="#4f6d99", font=("Segoe UI", 7), tags="map")
        if not self.countries:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                          text="loading world map ..." if not self.map_failed
                          else "world map not available", fill="#4f6d99",
                          font=("Segoe UI", 14), tags="map")
        self._draw_night()
        self._redraw_spots()

    def _draw_night(self):
        c = self.canvas
        c.delete("night")
        if not self.scale:
            return
        now = utc_now()
        doy = now.timetuple().tm_yday
        hours = now.hour + now.minute / 60.0 + now.second / 3600.0
        decl = -23.44 * math.cos(math.radians(360.0 / 365 * (doy + 10)))
        if abs(decl) < 0.1:
            decl = 0.1
        sun_lon = (12.0 - hours) * 15.0
        sun_lon = (sun_lon + 180) % 360 - 180
        tan_d = math.tan(math.radians(decl))
        line = []
        for lon in range(-180, 181, 2):
            ha = math.radians(lon - sun_lon)
            lat = math.degrees(math.atan(-math.cos(ha) / tan_d))
            line.append((lat, lon))
        pole = LAT_MIN if decl > 0 else LAT_MAX
        poly = []
        for lat, lon in line + [(pole, 180), (pole, -180)]:
            poly.extend(self._xy(lat, lon))
        c.create_polygon(poly, fill="#000000", stipple="gray50", outline="",
                         tags=("night",), state="disabled")
        pts = []
        for lat, lon in line:
            pts.extend(self._xy(lat, lon))
        c.create_line(pts, fill="#ffb347", width=1, dash=(4, 3), tags=("night",),
                      state="disabled")
        sx, sy = self._xy(decl, sun_lon)
        c.create_oval(sx - 9, sy - 9, sx + 9, sy + 9, fill="#ffdd33",
                      outline="#ff9900", width=2, tags=("night",), state="disabled")
        c.tag_raise("spot")

    def _night_tick(self):
        self._draw_night()
        self.root.after(60000, self._night_tick)

    # ----- spots -----------------------------------------------------------

    def _color(self, sp):
        if self.flt.get("color_by") == "mode":
            return MODE_COLOR.get(sp["mode"], "#ffffff")
        return BAND_COLOR.get(sp["band"], "#ffffff")

    def _qrz_state(self, sp):
        info = self.info.get(sp["hc"])
        if info is not None:
            return "yes" if info["found"] else "no"
        if self.qrz.is_pending(sp["hc"]):
            return "pending"
        return "-"

    def _on_spot(self, s):
        self.spots_rx += 1
        if s["band"] is None:
            return
        key = (s["call"], s["band"])
        now = time.time()
        sp = self.spots.get(key)
        if sp is None:
            sp = {"id": self.next_id, "call": s["call"], "hc": home_call(s["call"]),
                  "band": s["band"], "first": now, "spotters": {}, "srcs": set(),
                  "lat": None, "lon": None, "loc": "", "country": ""}
            self.next_id += 1
            self.spots[key] = sp
            self.id_map[sp["id"]] = key
        sp.update(freq=s["freq"], mode=s["mode"], last=now, time=s["time"],
                  comment=s["comment"], src=s["src"], spotter=s["spotter"])
        sp["srcs"].add(s["src"])
        sp["spotters"][s["spotter"]] = {"snr": s["snr"] or s["comment"][:18],
                                        "time": s["time"], "src": s["src"],
                                        "t": now}
        self._ensure_info(sp["hc"], s["src"])
        if sp["lat"] is None or sp["loc"] == "":
            self._locate(sp)
        self._draw_spot(sp)
        self._tree_upsert(sp, new_on_top=True)
        if len(self.spots) > MAX_SPOTS:
            oldest = sorted(self.spots.values(), key=lambda x: x["last"])
            for old in oldest[:len(self.spots) - MAX_SPOTS]:
                self._remove_spot(old)

    def _ensure_info(self, hc, src):
        if hc in self.info:
            return
        if hc not in self.cache_missed:
            info = self.cache.get(hc, self._int(self.v_cache_days, 30))
            if info:
                self.cache_hits += 1
                self.info[hc] = info
                return
            self.cache_missed.add(hc)
        if self.qrz.enabled() and (src != "RBN" or self.v_qrz_rbn.get()):
            self.qrz.submit(hc)

    def _locate(self, sp):
        call, hc = sp["call"], sp["hc"]
        lp = location_prefix(call)
        info = self.info.get(hc)
        away = lp != hc
        sp["lat"] = sp["lon"] = None
        if info and info["found"] and not away:
            ll = None
            if info.get("lat") is not None and info.get("lon") is not None:
                ll = (info["lat"], info["lon"])
            elif info.get("grid"):
                ll = grid_to_latlon(info["grid"])
            if ll:
                sp["lat"], sp["lon"] = ll
                sp["loc"] = "QRZ" + (" " + info["grid"] if info.get("grid") else "")
                sp["country"] = info.get("country") or ""
                return
        ent = self.cty.find(call, lp) if self.cty.loaded else None
        if ent:
            # spread calls of the same country a little so dots do not stack
            h = zlib.crc32(call.encode())
            sp["lat"] = ent[1] + ((h & 0xFFFF) / 65535.0 - 0.5) * 2.5
            sp["lon"] = ent[2] + (((h >> 16) & 0xFFFF) / 65535.0 - 0.5) * 3.5
            sp["loc"] = "DXCC centre"
            sp["country"] = ent[0]
        else:
            sp["loc"] = ""
        if info and info["found"] and info.get("country") and not away:
            sp["country"] = info["country"]

    def _spotter_latlon(self, spotter):
        if spotter in self.spotter_loc:
            return self.spotter_loc[spotter]
        ll = None
        info = self.info.get(home_call(spotter))
        if info and info["found"]:
            if info.get("lat") is not None:
                ll = (info["lat"], info["lon"])
            elif info.get("grid"):
                ll = grid_to_latlon(info["grid"])
        if ll is None and self.cty.loaded:
            ent = self.cty.find(spotter, location_prefix(spotter))
            if ent:
                ll = (ent[1], ent[2])
        if ll is not None or self.cty.loaded:
            self.spotter_loc[spotter] = ll
        return ll

    def _passes(self, sp):
        f = self.flt
        if sp["band"] not in f["bands"] or sp["mode"] not in f["modes"]:
            return False
        if f["dx"] and not any(fnmatch.fnmatchcase(sp["call"], p) for p in f["dx"]):
            return False
        if f["spotter"] and not any(fnmatch.fnmatchcase(s, p)
                                    for s in sp["spotters"] for p in f["spotter"]):
            return False
        if f["qrz_only"]:
            info = self.info.get(sp["hc"])
            if not (info and info["found"]):
                return False
        return True

    @staticmethod
    def _patterns(text):
        pats = []
        for t in re.split(r"[,;\s]+", text.upper()):
            if t:
                pats.append(t if any(ch in t for ch in "*?[") else t + "*")
        return pats

    def _update_filter(self):
        self.flt = {
            "bands": {b for b, v in self.v_bands.items() if v.get()},
            "modes": {m for m, v in self.v_modes.items() if v.get()},
            "dx": self._patterns(self.v_dx_filter.get()),
            "spotter": self._patterns(self.v_spotter_filter.get()),
            "qrz_only": self.v_qrz_only.get(),
            "color_by": self.v_color_by.get(),
        }

    def _filter_changed(self, *_):
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(300, self._apply_filter)

    def _apply_filter(self):
        self._refresh_job = None
        self._update_filter()
        self._redraw_spots()
        self._rebuild_tree()

    def _draw_spot(self, sp):
        c = self.canvas
        tag = "s%d" % sp["id"]
        c.delete(tag)
        if not self.scale or sp["lat"] is None or not self._passes(sp):
            return
        x, y = self._xy(sp["lat"], sp["lon"])
        age = time.time() - sp["last"]
        r = 6 if age < 120 else 5 if age < 600 else 4
        color = self._color(sp)
        if age < 90:          # fresh spot: halo
            c.create_oval(x - r - 4, y - r - 4, x + r + 4, y + r + 4,
                          outline=color, width=2, tags=("spot", tag))
        state = self._qrz_state(sp)
        outline, width = {"yes": ("#ffffff", 2), "no": ("#ff2020", 2)}.get(
            state, ("#000000", 1))
        c.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=outline,
                      width=width, tags=("spot", tag))

    def _redraw_spots(self):
        self.canvas.delete("spot")
        self.canvas.delete("hover")
        for sp in list(self.spots.values()):
            self._draw_spot(sp)

    def _remove_spot(self, sp):
        key = (sp["call"], sp["band"])
        self.spots.pop(key, None)
        self.id_map.pop(sp["id"], None)
        self.canvas.delete("s%d" % sp["id"])
        iid = str(sp["id"])
        if self.tree.exists(iid):
            self.tree.delete(iid)

    def _purge_tick(self):
        cutoff = time.time() - self._int(self.v_max_age, 15) * 60
        old = [sp for sp in self.spots.values() if sp["last"] < cutoff]
        for sp in old:
            self._remove_spot(sp)
        # forget spotter reports that are too old, too
        for sp in self.spots.values():
            for name in [n for n, d in sp["spotters"].items() if d["t"] < cutoff]:
                del sp["spotters"][name]
        if old:
            self._log("removed %d old spots" % len(old), "dim")
        self._redraw_spots()          # also updates dot size / halo by age
        self.root.after(10000, self._purge_tick)

    # ----- hover tooltip ---------------------------------------------------

    def _spot_at_cursor(self):
        items = self.canvas.find_withtag("current")
        if not items:
            return None
        for t in self.canvas.gettags(items[0]):
            if t.startswith("s") and t[1:].isdigit():
                key = self.id_map.get(int(t[1:]))
                return self.spots.get(key) if key else None
        return None

    def _on_spot_enter(self, event):
        sp = self._spot_at_cursor()
        c = self.canvas
        c.delete("hover")
        if not sp:
            return
        color = self._color(sp)
        dx_x, dx_y = self._xy(sp["lat"], sp["lon"])
        # great circle paths from every spotter to the DX station
        for name in sp["spotters"]:
            ll = self._spotter_latlon(name)
            if not ll:
                continue
            for seg in gc_segments(ll[0], ll[1], sp["lat"], sp["lon"]):
                pts = []
                for lat, lon in seg:
                    pts.extend(self._xy(lat, lon))
                c.create_line(pts, fill=color, width=2, tags=("hover",),
                              state="disabled", smooth=True)
            sx, sy = self._xy(*ll)
            c.create_rectangle(sx - 3, sy - 3, sx + 3, sy + 3, fill="#ffffff",
                               outline=color, tags=("hover",), state="disabled")
            c.create_text(sx + 5, sy, text=name, anchor="w", fill="#ffffff",
                          font=("Consolas", 7), tags=("hover",), state="disabled")
        c.tag_raise("hover")
        c.tag_raise("spot")

        info = self.info.get(sp["hc"])
        qs = {"yes": "confirmed on QRZ.com", "no": "NOT FOUND on QRZ.com",
              "pending": "QRZ lookup pending ...", "-": "not checked on QRZ"}[
            self._qrz_state(sp)]
        lines = ["%s   %.1f kHz   %s  %s" % (sp["call"], sp["freq"], sp["band"], sp["mode"])]
        if info and info["found"] and info.get("name"):
            lines.append(info["name"])
        lines.append("%s   (%s)" % (sp["country"] or "?", sp["loc"] or "no location"))
        lines.append("QRZ: " + qs)
        spotters = sorted(sp["spotters"].items(), key=lambda kv: -kv[1]["t"])
        lines.append("Spotted by %d station(s):" % len(spotters))
        for name, d in spotters[:10]:
            lines.append("  %-10s %-18s %sZ %s" % (name, d["snr"][:18], d["time"], d["src"]))
        if len(spotters) > 10:
            lines.append("  ... and %d more" % (len(spotters) - 10))
        if sp.get("src") == "Cluster" and sp.get("comment"):
            lines.append("Comment: " + sp["comment"][:40])
        lines.append("(click = open QRZ.com page)")

        tx, ty = event.x + 16, event.y + 16
        tid = c.create_text(tx, ty, text="\n".join(lines), anchor="nw", fill="#ffffff",
                            font=("Consolas", 9), tags=("hover",), state="disabled")
        x0, y0, x1, y1 = c.bbox(tid)
        w, h = c.winfo_width(), c.winfo_height()
        dx = -(x1 - x0) - 32 if x1 + 8 > w else 0
        dy = -(y1 - y0) - 32 if y1 + 8 > h else 0
        c.move(tid, dx, dy)
        x0, y0, x1, y1 = c.bbox(tid)
        rid = c.create_rectangle(x0 - 6, y0 - 4, x1 + 6, y1 + 4, fill="#111a2b",
                                 outline=color, width=2, tags=("hover",), state="disabled")
        c.create_rectangle(x0 - 6, y0 - 4, x0 - 2, y1 + 4, fill=color, outline="",
                           tags=("hover",), state="disabled")
        c.tag_raise(rid)
        c.tag_raise(tid)
        c.create_oval(dx_x - 10, dx_y - 10, dx_x + 10, dx_y + 10, outline="#ffffff",
                      width=1, dash=(2, 2), tags=("hover",), state="disabled")

    def _on_spot_click(self, _event):
        sp = self._spot_at_cursor()
        if sp:
            webbrowser.open("https://www.qrz.com/db/%s" % sp["hc"])

    # ----- spot list -------------------------------------------------------

    def _tree_values(self, sp):
        state = self._qrz_state(sp)
        return (sp["time"] + "Z", sp["call"], "%.1f" % sp["freq"], sp["band"],
                sp["mode"], sp["spotter"], len(sp["spotters"]), sp["country"],
                {"yes": "✔", "no": "✘", "pending": "…"}.get(state, ""),
                "+".join(sorted(sp["srcs"])),
                sp["comment"] if sp["src"] != "RBN"
                else sp["spotters"].get(sp["spotter"], {}).get("snr", ""))

    def _tree_upsert(self, sp, new_on_top=False):
        iid = str(sp["id"])
        tree = self.tree
        if not self._passes(sp):
            if tree.exists(iid):
                tree.delete(iid)
            return
        tag = ("m_" + sp["mode"]) if self.flt.get("color_by") == "mode" else ("b_" + sp["band"])
        if tree.exists(iid):
            tree.item(iid, values=self._tree_values(sp), tags=(tag,))
            if new_on_top:
                tree.move(iid, "", 0)
        else:
            tree.insert("", 0, iid=iid, values=self._tree_values(sp), tags=(tag,))
            kids = tree.get_children()
            if len(kids) > MAX_TREE_ROWS:
                tree.delete(*kids[MAX_TREE_ROWS:])

    def _rebuild_tree(self):
        self.tree.delete(*self.tree.get_children())
        shown = [sp for sp in self.spots.values() if self._passes(sp)]
        shown.sort(key=lambda s: s["last"])
        for sp in shown[-MAX_TREE_ROWS:]:
            self._tree_upsert(sp)

    def _on_tree_double(self, _event):
        sel = self.tree.selection()
        if sel:
            key = self.id_map.get(int(sel[0]))
            sp = self.spots.get(key) if key else None
            if sp:
                webbrowser.open("https://www.qrz.com/db/%s" % sp["hc"])

    # ----- queue from the worker threads -----------------------------------

    def _poll_queue(self):
        try:
            for _ in range(3000):
                msg = self.gui_q.get_nowait()
                kind = msg[0]
                if kind == "spot":
                    self._on_spot(msg[1])
                elif kind == "qrz":
                    self._on_qrz(msg[1], msg[2])
                elif kind == "log":
                    self._log(msg[1], msg[2] if len(msg) > 2 else "info")
                elif kind == "status":
                    self.source_status[msg[1]] = msg[2]
                elif kind == "cty":
                    self.cty = msg[1]
                    self.spotter_loc.clear()
                    for sp in self.spots.values():
                        self._locate(sp)
                    self._redraw_spots()
                elif kind == "map":
                    self.countries = msg[1]
                    self.map_failed = not msg[1]
                    self._redraw_all()
                elif kind == "qrztest":
                    ok, text = msg[1], msg[2]
                    self._log(text, "ok" if ok else "err")
                    (messagebox.showinfo if ok else messagebox.showerror)("QRZ.com", text)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def _on_qrz(self, call, info):
        self.info[call] = info
        self.cache_missed.discard(call)
        self.cache_count += 1
        self.spotter_loc.pop(call, None)
        for sp in list(self.spots.values()):
            if sp["hc"] == call:
                self._locate(sp)
                self._draw_spot(sp)
                self._tree_upsert(sp)

    def _status_tick(self):
        parts = []
        for name in sorted(self.source_status):
            parts.append("%s: %s" % (name, self.source_status[name]))
        shown = sum(1 for sp in self.spots.values() if self._passes(sp))
        qrz = "QRZ %s" % ("on" if self.qrz.enabled() else "off")
        self.status.config(text="  %s   |  spots shown %d / %d  (received %d)  |  %s: "
                                "cache %d calls, hits %d, online lookups %d, queue %d%s"
                           % ("   ".join(parts) or "not connected", shown, len(self.spots),
                              self.spots_rx, qrz, self.cache_count, self.cache_hits,
                              self.qrz.lookups, self.qrz.backlog(),
                              ", errors %d" % self.qrz.errors if self.qrz.errors else ""))
        self.root.after(1000, self._status_tick)

    # ----- actions ---------------------------------------------------------

    def _toggle_connect(self):
        if self.sources:
            for s in self.sources:
                s.stop()
            self.sources = []
            self.btn_connect.config(text="  Connect  ", bg="#1fa35c",
                                    activebackground="#27c46f")
            self._log("disconnected")
            return
        mycall = self.v_mycall.get().strip().upper()
        if not CALL_RE.match(mycall):
            messagebox.showwarning(APP_NAME, "Please enter your own callsign first "
                                   "(it is used to log in to RBN and the cluster).")
            return
        self._save_settings()
        user, pw = self.v_qrz_user.get().strip(), self.v_qrz_pass.get()
        self.qrz.set_credentials(user, pw)
        if user and pw:
            self._log("QRZ lookups enabled for %s" % user, "ok")
            n = self.cache.purge_expired(max(365, self._int(self.v_cache_days, 30)))
            if n:
                self._log("removed %d very old cache entries" % n, "dim")
        else:
            self._log("no QRZ credentials: using cache + cty.dat only", "dim")
        self.cache_missed.clear()
        if self.v_rbn_cw.get():
            self.sources.append(TelnetSpotSource("RBN CW", RBN_HOST, RBN_PORT_CW,
                                                 mycall, self.gui_q, "RBN"))
        if self.v_rbn_digi.get():
            self.sources.append(TelnetSpotSource("RBN FT8", RBN_HOST, RBN_PORT_DIGI,
                                                 mycall, self.gui_q, "RBN"))
        if self.v_use_cluster.get():
            host, _, port = self.v_cluster.get().strip().rpartition(":")
            try:
                port = int(port)
            except ValueError:
                messagebox.showwarning(APP_NAME, "Cluster must be written as host:port")
                self.sources = []
                return
            self.sources.append(TelnetSpotSource("Cluster", host, port, mycall,
                                                 self.gui_q, "Cluster"))
        if not self.sources:
            messagebox.showinfo(APP_NAME, "Select RBN and/or a DX cluster.")
            return
        self.source_status = {}
        for s in self.sources:
            s.start()
        self.btn_connect.config(text="Disconnect", bg="#d63a3a", activebackground="#f04d4d")

    def _test_qrz(self):
        user, pw = self.v_qrz_user.get().strip(), self.v_qrz_pass.get()
        if not user or not pw:
            messagebox.showinfo("QRZ.com", "Enter your QRZ.com user name and password.")
            return

        def run():
            try:
                sess = QrzClient(user, pw).login()
                text = "QRZ login OK. Subscription: %s. Lookups today: %s" % (
                    sess.get("SubExp", "?"), sess.get("Count", "?"))
                if "non-subscriber" in sess.get("SubExp", "").lower():
                    text += ("\nWithout an XML subscription QRZ returns limited "
                             "data (often no lat/lon); the DXCC centre is used then.")
                self.gui_q.put(("qrztest", True, text))
            except Exception as e:  # noqa: BLE001 - show any problem to the user
                self.gui_q.put(("qrztest", False, "QRZ login failed: %s" % e))
        threading.Thread(target=run, daemon=True).start()

    def _on_close(self):
        try:
            self._save_settings()
        except Exception:  # noqa: BLE001 - never block closing the window
            pass
        for s in self.sources:
            s.stop()
        self.qrz.stop_event.set()
        self.root.destroy()
        self.cache.close()


def main():
    root = tk.Tk()
    DxSpotMapApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
