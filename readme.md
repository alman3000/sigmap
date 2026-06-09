# GraffMap

interactive web map for visualizing large collections of geotagged photos with clustering, time filtering, tag-based moderation, gallery, admin panel and a Docker-based backend.

---

## Features

### Map (`map.html`)

| Feature | Description |
|---------|-------------|
| Interactive map | Leaflet + OpenStreetMap, pan/zoom/click |
| Marker clustering | Handles 100k+ photos (150 px cluster radius, canvas renderer) |
| Cluster gallery | Click a cluster → horizontal scrollable thumbnail gallery |
| Lightbox | Click thumbnail → full-quality image viewer with arrow-key navigation |
| Time slider | Filter by month via slider or hierarchical year/month selector |
| Multi-select months | Ctrl+Click to select multiple months simultaneously |
| Heatmap view | Toggle between marker and density heatmap |
| Tag filter | Filter visible markers by admin-assigned tags |
| Server tags | Admin-assigned tags shown as amber badges below each photo |
| Personal tags | Browser-local tags (localStorage) for personal annotations |
| Random navigator | Jump to a random visible marker at zoom 18 |
| URL sharing | Encodes lat/lng/zoom/month/view/file in URL for sharing |
| Deep-link from gallery | `?file=FILENAME` auto-opens that marker's popup on page load |
| Dark theme | Dark background (#1a1a1a) with amber accents (#f59e0b) |
| Responsive | Works on desktop and mobile |

### Gallery (`gallery.html`)

| Feature | Description |
|---------|-------------|
| Paginated infinite scroll | Loads 100 photos at a time via `GET /api/photos`, more on scroll |
| Month grouping | Photos grouped by capture month, headers update incrementally |
| Tag filter | Filter by tag (OR logic) — re-fetches from backend, no client-side filtering |
| Sort order | Toggle newest / oldest first — server-side sort by `datetime_original` |
| Lightbox | GLightbox with dark theme; shows filename, date, tags, and map links |
| Capture date | Shown below each thumbnail in the tile footer |
| Map links | Each tile and lightbox caption links to the graffmap map and Google Maps |
| Deep-link to map | "Karte" link opens the map with the correct month selected and the marker popup open |
| Event-delegated lightbox | Single click handler on the container — no `reload()` on every render |
| Abort on filter change | In-flight requests cancelled via `AbortController` on sort/filter change |

### Upload page (`upload.html`)

| Feature | Description |
|---------|-------------|
| Password gate | Single shared password, stored in `sessionStorage` until tab is closed |
| Drag & drop | Drop multiple files at once onto the upload zone |
| File picker | Click to open a file dialog (multiple selection) |
| Progress bars | Per-file XHR progress, up to 3 concurrent uploads |
| GPS detection | Files with GPS are processed automatically in the background |
| Location picker | Files without GPS show an interactive Leaflet map to set coordinates manually |
| Wrong-password handling | 401 response clears the password and returns to the login gate |

### Admin panel (`admin.html`)

| Feature | Description |
|---------|-------------|
| Magic link login | Passwordless login via email link (configurable expiry) |
| Email whitelist | Only pre-configured addresses can request a login link |
| Photo moderation | Approve / reject uploaded photos before they appear on the map |
| Tag management | Assign global tags (graffiti / sticker / tag / streetart) per photo |
| Auto-regeneration | GeoJSON is atomically regenerated whenever tags or status change |
| Stats dashboard | Live counts: total / pending / approved / rejected |
| Pagination | Load photos in pages of 48 |

### Backend (FastAPI)

| Endpoint | Description |
|----------|-------------|
| `POST /api/upload` | Upload photos (HTTP Basic Auth, max 50 MB per file) |
| `POST /api/upload/locate` | Set manual GPS coordinates for a GPS-less uploaded photo |
| `GET /api/photos` | Paginated public photo list (approved only; filter by tags, sort by date) |
| `POST /api/auth/request` | Request a magic-link login email |
| `GET /api/auth/verify` | Validate token, issue session cookie, redirect to admin |
| `GET /api/auth/me` | Return authenticated admin email |
| `POST /api/auth/logout` | Clear session cookie |
| `GET /api/admin/stats` | Photo counts by status |
| `GET /api/admin/photos` | Paginated photo list (filterable by status) |
| `PATCH /api/admin/photos/{id}/tags` | Update tags for a photo |
| `PATCH /api/admin/photos/{id}/status` | Approve or reject a photo |
| `PATCH /api/admin/photos/{id}/location` | Correct GPS coordinates for a photo |
| `POST /api/admin/regenerate` | Manually trigger GeoJSON regeneration |
| `POST /api/admin/regenerate-thumbnails` | Recreate all thumbnails with correct EXIF orientation |
| `GET /api/health` | Health check |

### Upload workflow

**With GPS data:**

1. Upload a JPEG/HEIC via `POST /api/upload`
2. `exiftool` extracts GPS coordinates from EXIF
3. A FastAPI background task moves the file to `photos/`, creates a thumbnail with correct orientation, and registers the photo in PostgreSQL as **pending**
4. Admin email notification is sent to all configured `ADMIN_EMAILS`
5. Admin approves in the admin panel → GeoJSON regenerated → photo appears on the map

**Without GPS data:**

1. Upload returns `needs_location: true` and a `photo_id`
2. Frontend shows an interactive Leaflet map to pick the location
3. User clicks "Standort bestätigen" → `POST /api/upload/locate` saves the coordinates
4. Admin notification is sent; admin approves → photo appears on the map

**Startup cleanup:** Pending photos with no coordinates older than 7 days are automatically deleted on backend startup.

---

## Project Structure

```
graffmap/
├── map.html                    # Map application (static, no build step)
├── gallery.html                # Paginated photo gallery with infinite scroll
├── admin.html                  # Admin moderation panel (magic link login)
├── upload.html                 # Password-protected photo upload page
├── photos.geojson     # Active GeoJSON served to the map
│
├── photos/                     # Original full-resolution photos
├── thumbnails/                 # Generated thumbnails (EXIF-corrected)
├── uploads/                    # Temporary landing zone for incoming uploads
├── pending_location/           # Uploaded photos awaiting manual GPS coordinates
│
├── tools/
│   ├── prepare_data.py         # Parallel GPS extraction + thumbnail pipeline
│   ├── convert_heic_to_jpg.py  # HEIC → JPEG converter (preserves EXIF)
│   └── compress_geojson.py     # GeoJSON size optimizer
│
├── backend/                    # FastAPI backend
│   ├── main.py                 # App entrypoint + startup tasks
│   ├── config.py               # Settings (loaded from .env)
│   ├── database.py             # SQLAlchemy + PostgreSQL
│   ├── models.py               # Photo, MagicLinkToken ORM models
│   ├── deps.py                 # JWT session dependency
│   ├── routers/
│   │   ├── auth.py             # Magic link auth
│   │   ├── upload.py           # Photo upload + location assignment
│   │   ├── photos.py           # Public paginated photo API (gallery)
│   │   └── admin.py            # Admin CRUD + thumbnail regeneration
│   ├── services/
│   │   ├── mail.py             # SMTP service (3 modes) + admin notifications
│   │   └── processing.py       # GPS extraction, thumbnails, GeoJSON, cleanup
│   ├── requirements.txt
│   └── Dockerfile
│
├── docker-compose.yml          # Orchestrates app + db + nginx (+ optional services)
├── nginx.conf                  # Reverse proxy + static file serving + gzip
├── .env.example                # All configuration variables with comments
└── .env                        # Local config (not committed)
```

---

## Quick Start

### Option A — Static only (no backend)

Requires pre-generated `photos.geojson`. No upload, no admin panel.

```bash
python -m http.server 8000
# → http://localhost:8000/map.html
```

### Option B — Full stack with Docker

```bash
# 1. Copy and edit the environment file
cp .env.example .env
# edit .env — at minimum set POSTGRES_PASSWORD, SECRET_KEY, ADMIN_EMAILS, UPLOAD_PASSWORD

# 2. Start (production mode)
docker compose up -d

# 3. Start with MailHog for local email testing
docker compose --profile dev up -d

# 4. Start with Postfix relay container (Option B SMTP)
docker compose --profile smtp-relay up -d
```

Services:

| URL | Service |
|-----|---------|
| http://localhost | Map |
| http://localhost/gallery.html | Photo gallery |
| http://localhost/upload.html | Photo upload (password protected) |
| http://localhost/admin.html | Admin panel (magic link login) |
| http://localhost/api/health | Backend health check |
| http://localhost:8025 | MailHog Web UI (dev profile only) |

On first start the backend automatically imports all features from any existing `photos.geojson` into PostgreSQL with status **approved**, so the map continues to work immediately.

---

## Data Preparation (offline batch)

Use `tools/prepare_data.py` to process an existing photo collection (runs outside Docker, uses all CPU cores):

```bash
# Full pipeline: GPS extraction + thumbnails + GeoJSON
python tools/prepare_data.py ./photos

# Custom thumbnail size
python tools/prepare_data.py ./photos --thumb-size 500 500

# Specific number of workers
python tools/prepare_data.py ./photos --workers 8

# All options
python tools/prepare_data.py --help
```

**Requirements:** Python 3.7+, `pip install pillow`, `exiftool` in PATH.

The script outputs `photos.json` (GPS data) and `photos.geojson`. Copy / rename to `photos.geojson` to serve it on the map.

> **Note:** After running `prepare_data.py`, trigger thumbnail regeneration via the admin panel (`POST /api/admin/regenerate-thumbnails`) to ensure all thumbnails have correct EXIF orientation.

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in the values.

```
# Database
POSTGRES_PASSWORD=...      # required

# Auth
SECRET_KEY=...             # generate: openssl rand -hex 32
ADMIN_EMAILS=a@b.com       # comma-separated; only these may log in
MAGIC_LINK_EXPIRE_MINUTES=15
SESSION_EXPIRE_HOURS=24

# Upload
UPLOAD_PASSWORD=...        # HTTP Basic Auth password for POST /api/upload

# App
APP_URL=https://yourdomain.com   # used in magic-link and admin notification emails

# SMTP (see below)
SMTP_MODE=host
SMTP_FROM=noreply@yourdomain.com
```

---

## SMTP Configuration

Three modes, switched by `SMTP_MODE` in `.env`. SMTP is used for two things: **magic link login** and **admin notifications** when new photos are uploaded for review.

### `host` — VPS postfix / exim4 (recommended for production)

The app container sends to the host machine's mail daemon via Docker `host-gateway`. No extra container needed; the host's postfix/exim4 must accept relay from the Docker bridge network.

```env
SMTP_MODE=host
SMTP_HOST_GATEWAY=host-gateway
SMTP_HOST_PORT=25
```

### `relay` — Docker Postfix relay container

A lightweight Postfix relay runs as a sidecar container. Activate with `--profile smtp-relay`.

```env
SMTP_MODE=relay
SMTP_RELAY_HOST=smtp-relay
SMTP_RELAY_PORT=25
SMTP_RELAY_DOMAIN=yourdomain.com
```

```bash
docker compose --profile smtp-relay up -d
```

### `external` — External SMTP server

Any SMTP server with optional STARTTLS (port 587) or implicit TLS (port 465).

```env
SMTP_MODE=external
SMTP_EXTERNAL_HOST=mail.yourdomain.com
SMTP_EXTERNAL_PORT=587
SMTP_EXTERNAL_USER=noreply@yourdomain.com
SMTP_EXTERNAL_PASSWORD=...
SMTP_EXTERNAL_TLS=true    # STARTTLS
SMTP_EXTERNAL_SSL=false   # set true for port 465
```

### Local development — MailHog

Catches all outgoing mail and displays it in a web UI. No real emails are sent.

```env
SMTP_MODE=relay
SMTP_RELAY_HOST=mailhog
SMTP_RELAY_PORT=1025
```

```bash
docker compose --profile dev up -d
# Web UI → http://localhost:8025
```

> **Note:** SMTP failure is non-fatal. If sending fails, the magic link is logged to the app container's stdout (`docker logs graffmap-app-1 | grep "Magic link"`) and the login request still succeeds.

---

## Uploading Photos

The upload password is set in `.env`:

```env
UPLOAD_PASSWORD=dein_passwort_hier
```

### Via browser (`upload.html`)

Open `http://yourdomain.com/upload.html`, enter the password, then drag-and-drop files or click to select them. The password is remembered for the browser session (cleared when the tab closes).

Photos without GPS metadata are not discarded — instead a location picker appears so coordinates can be set manually before the photo is submitted for review.

### Via curl / scripts

```bash
curl -u upload:UPLOAD_PASSWORD \
     -F "file=@/path/to/photo.jpg" \
     http://yourdomain.com/api/upload
```

Supported formats: `.jpg`, `.jpeg`, `.heic`, `.heif` — max 50 MB per file.

---

## Thumbnail Orientation

Thumbnails are stored without EXIF metadata. On creation, Pillow applies `ImageOps.exif_transpose()` to physically rotate the pixels, so thumbnails always display correctly regardless of the original EXIF orientation tag.

If you imported photos via `prepare_data.py` or an older version of the backend, existing thumbnails may have incorrect orientation. Fix them via:

```bash
# Via admin panel button, or:
curl -X POST -b "session=..." http://yourdomain.com/api/admin/regenerate-thumbnails
```

---

## HTTPS on a VPS

1. Point your domain's DNS A record to the VPS IP
2. Start the stack: `docker compose up -d`
3. Issue a certificate with Certbot (runs on the host, not in Docker):
   ```bash
   certbot certonly --webroot -w /path/to/graffmap --email you@domain.com -d yourdomain.com
   ```
4. Uncomment the `server { listen 443 ssl ... }` block in `nginx.conf` and fill in your domain
5. Reload nginx: `docker compose exec nginx nginx -s reload`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No photos on map | Check browser console; verify `photos.geojson` is readable |
| Gallery shows 0 photos | Photos may still be `pending`; approve them in the admin panel |
| Admin panel shows "Not authenticated" | Session cookie expired (24 h default) — request a new magic link |
| Magic link email not arriving | Check `docker logs graffmap-app-1` — the link is always logged as INFO |
| Upload returns 401 | Wrong `UPLOAD_PASSWORD` in `.env` |
| Photos uploaded but no admin email | `ADMIN_EMAILS` not set in `.env`, or SMTP misconfigured |
| GeoJSON not updating after approve | Check `docker logs graffmap-app-1` for regeneration errors |
| Thumbnails with wrong rotation | Run `POST /api/admin/regenerate-thumbnails` to rebuild all thumbnails |
| `exiftool` not found | The Dockerfile installs `libimage-exiftool-perl`; rebuild the image |

---

## Credits

Built with:

- [Leaflet](https://leafletjs.com/) — interactive maps
- [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) — marker clustering
- [Leaflet.heat](https://github.com/Leaflet/Leaflet.heat) — heatmap layer
- [Lightbox2](https://lokeshdhakar.com/projects/lightbox2/) — image lightbox on the map
- [GLightbox](https://biati-digital.github.io/glightbox/) — image lightbox in the gallery
- [FastAPI](https://fastapi.tiangolo.com/) — backend API
- [SQLAlchemy](https://www.sqlalchemy.org/) — ORM / PostgreSQL
- [ExifTool](https://exiftool.org/) — GPS/EXIF extraction
- [Pillow](https://python-pillow.org/) — thumbnail generation
- [MailHog](https://github.com/mailhog/MailHog) — local email testing

---

## License

Copyleft.
