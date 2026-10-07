# DX Spot Map

A single Python file (`dx_spot_map.py`) that shows live DX spots from the
**Reverse Beacon Network** and a **DX cluster** of your choice as coloured dots
on a world map. It only uses the Python standard library, so it runs as-is in
**Thonny on Windows**. Open the file and press **F5**.

## Features
- RBN CW/RTTY (`telnet.reversebeacon.net:7000`) and RBN FT8/FT4 (`:7001`)
- Any telnet DX cluster (list included, or type `host:port`)
- Optional **QRZ.com** cross-check of every spotted call (XML API)
  - results are stored in an **SQLite cache** (`dxspotmap_cache.sqlite`),
    so each call is looked up only once per *cache days* (calls that aren't found are re-checked after 3 days)
  - dot outline: white = found on QRZ, red = not found, black = not checked
  - "QRZ-confirmed only" filter
- Station location: QRZ lat/lon or grid when available, otherwise the DXCC
  entity from `cty.dat` (portable calls like `EA8/ON4XX` are placed in EA8)
- Filters: band, mode, DX call and spotter call (comma-separated, `*` / `?`
  wildcards; `EA8` means "starts with EA8")
- Spots older than *Keep (min)* are removed automatically
- Hover over a dot: DX call, frequency, mode, QRZ name/country, all spotters
  with SNR/speed, and great-circle paths from each spotter
- Click a dot (or double-click a list row) to open the call's QRZ.com page
- Colour by band or by mode, day/night shading, sun position
- Settings are saved in the same SQLite file

## First start
1. Enter **your callsign** (used to log in to RBN and the cluster).
2. Optional: QRZ.com user name and password, then press **Test QRZ**.
   Full lat/lon data needs a QRZ XML subscription; without it, the DXCC centre is used.
3. Pick the feeds and press **Connect**.

On the first start the program downloads `cty.dat` (country-files.com) and a
Natural Earth country map next to the script. If that is blocked, download
them yourself and put them in the same folder:
- https://www.country-files.com/cty/cty.dat
- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
  (save it as `world_countries.geojson`)

Note: the QRZ password is stored unencrypted in the local SQLite file.

---

# DX Cluster Board

`dx_cluster_board.py` is a second single-file app (standard library only, it
runs in Thonny too). It shows a colourful live **list** of DX spots that it
collects from several well-known DX clusters at the same time.

- Built-in list of clusters: VE7CC, W3LPL, NC7J, GB7DJK, DL9GTB, ON0DXK,
  DXFun, HamQTH, RBN CW and RBN FT8. Tick the ones you want, or add your own
  as `host:port` (the list is saved).
- Spots from all clusters are merged. The same DX within 1 kHz is shown once,
  with every spotter and a coloured dot for each cluster that reported it.
- Every band and every mode has its own colour.
- Band activity bars: click a bar to show or hide that band. Ctrl+click shows
  only that band, and a second Ctrl+click shows all bands again.
- Mode chips (CW, SSB, FT8, FT4, RTTY, DIGI) work the same way.
- Search box for a DX call or a country (the country comes from `cty.dat`).
- New spots glow, older spots fade, and spots are removed after *Keep (min)*.
- Click a spot to open its QRZ.com page.
- Each cluster has a status light (green = receiving, yellow = connecting,
  red = error) and a spot counter.

Enter your callsign, tick the clusters and press **Connect**. Settings are
saved in `dx_cluster_board.json`. To try the screen without internet, start it
with `python dx_cluster_board.py --demo`, which shows made-up spots.

---

# DX Cluster Board for Android

The `android/` folder holds an Android version of the DX Cluster Board, written
in Kotlin with Jetpack Compose. It needs Android 8.0 or newer.

## Install on your phone
1. On the phone, open the repository on GitHub, go to **Releases**, then open
   **DX Cluster Board for Android (latest build)**.
2. Tap **DXClusterBoard.apk** to download it.
3. Open the downloaded file. Android will ask you to allow installs from your
   browser or file manager ("Install unknown apps"). Allow it, then tap **Install**.

GitHub Actions (`.github/workflows/android.yml`) builds a new APK every time
something in `android/` changes, and it replaces the file in that release.
Newer builds install over the old one, and your settings are kept.

## Use
- **Clusters** tab: enter your callsign, switch the clusters you want on or
  off, add your own (`host:port`), and set how many minutes spots are kept.
  It also has *Keep screen on* and a *Demo mode* with made-up spots.
- Press **Connect** at the top.
- **Spots** tab: colourful cards with the band, frequency, DX call, mode,
  country, spotters, a coloured dot for each cluster that reported the spot,
  and the age of the spot. New spots glow.
  - Tap a band or mode chip to show or hide it. Long-press a chip to show only
    that one, and long-press it again to show all.
  - Search by DX call or country.
  - Tap a spot to open its QRZ.com page.
- **Log** tab: connection messages.

Spots arrive while the app is open. Android may stop the connections when the
app has been in the background for a long time. *Keep screen on* helps when
you use the phone as a DX display.

## Build it yourself
Open the `android/` folder in Android Studio, or run `./gradlew assembleRelease`.
`app/debug.keystore` is a debug signing key, not a secret. It is in the repo so
that every CI build can be installed over the previous one.
