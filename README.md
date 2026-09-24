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
