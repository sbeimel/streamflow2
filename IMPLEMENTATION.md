# StreamFlow 2.5.5.1 — Custom Feature Implementation

**Datum:** 2026-04-23  
**Basis:** StreamFlow 2.5.5.1 (upstream)  
**Status:** Implementiert, auditiert

---

## Geänderte Dateien

| Datei | Art |
|-------|-----|
| `backend/apps/stream/quality_scoring.py` | NEU |
| `backend/apps/stream/stream_checker_components.py` | GEÄNDERT |
| `backend/apps/stream/stream_checker_service.py` | GEÄNDERT |
| `backend/apps/stream/stream_check_utils.py` | GEÄNDERT |
| `backend/apps/core/api_utils.py` | GEÄNDERT |
| `backend/apps/api/web_api.py` | GEÄNDERT |
| `frontend/src/pages/StreamChecker.jsx` | GEÄNDERT |
| `docker-compose.yml` | GEÄNDERT |

---

## Features

### 1. Enhanced Quality Scoring (Codec-aware Sigmoid)

**Datei:** `backend/apps/stream/quality_scoring.py` (neu)

MACstrom-inspiriertes Scoring-Modul mit:
- Codec-aware Reference Bitrates (H.264, HEVC, AV1 je Auflösungsstufe)
- Sigmoid-Kurve: `1 / (1 + exp(-3.5 × (ratio - 0.7)))`
- Resolution Ceilings: 4K=100, 1080p=90, 720p=75, SD=55
- FPS-Faktor: ≥48fps +8%, <20fps -15%
- Off-Air-Detection: <200 kbps → Score 0

**Config:** `scoring.method` = `'legacy'` | `'enhanced'`  
**Default:** `'legacy'` (abwärtskompatibel)

---

### 2. Avoid / Prefer H.265 mit Mutual Exclusion

**Config:**
- `scoring.prefer_h265` (bool, default: True) — Legacy only
- `scoring.avoid_h265` (bool, default: False) — beide Methoden

Enhanced: 30% Penalty auf finalen Score bei HEVC.  
Legacy: Codec-Score 0.5 (HEVC) / 1.0 (H.264) bei avoid.  
Mutual Exclusion: Aktivieren eines Switches deaktiviert den anderen.

---

### 3. Provider Diversification

**Config:**
- `stream_ordering.provider_diversification` (bool, default: False)
- `stream_ordering.diversification_mode` = `'round_robin'` | `'priority_weighted'`

Streams verschiedener M3U-Accounts werden nach dem Scoring interleaved.  
Round Robin: alphabetisch. Priority Weighted: nach M3U-Account-Priorität.  
Temporäre Keys `_provider_priority` / `_provider_name` werden nach Interleaving entfernt.  
Eingehängt an beiden Check-Pfaden (concurrent + sequential) nach Sort, vor Stream-Limit.

---

### 4. Quality Check Exclusions (Priority-Only)

**Config:**
- `quality_check_exclusions.enabled` (bool, default: False)
- `quality_check_exclusions.excluded_accounts` (list[int], default: [])

Excluded Streams:
- Überspringen FFmpeg-Analyse
- Score = M3U-Account-Priority / 100 (normalisiert 0–1)
- `_priority_only: True` Flag verhindert Batch-Stats-Write und Loop-Probing
- Werden nie als tot markiert, nie entfernt
- Beim Rescore & Resort (cached path): behalten Priority-Score korrekt

---

### 5. Stream Check Immunity (konfigurierbar)

**Config:**
- `stream_check_immunity.enabled` (bool, default: True)
- `stream_check_immunity.duration_hours` (int, 0–720, default: 2)

Ersetzt hardcodierte 7200s an beiden Check-Pfaden.  
`enabled=False` oder `duration_hours=0` → immer alle Streams prüfen.

---

### 6. Account Stream Limits

**Config:**
- `account_stream_limits.enabled` (bool, default: False)
- `account_stream_limits.global_limit` (int, default: 0 = unlimited)
- `account_stream_limits.account_limits` (dict, default: {})

Begrenzt Streams pro M3U-Account pro Channel nach Quality Check.  
Priorität: Per-Account-Override > Global Limit > Unlimited.  
Custom Streams (kein M3U-Account) nie betroffen.  
Angewendet nach Provider Diversification, vor `update_channel_streams()`.

---

### 7. Resolution Preference

**Config:**
- `resolution_preference.mode` = `'default'` | `'prefer_4k'` | `'avoid_4k'` | `'max_1080p'` | `'max_720p'`

Bonus/Penalty nach Score-Berechnung, wirkt auf beide Scoring-Methoden:
- `prefer_4k`: +0.5 für ≥2160p
- `avoid_4k`: -0.5 für ≥2160p
- `max_1080p`: -10.0 für >1080p (effektiv ausgeschlossen)
- `max_720p`: -10.0 für >720p (effektiv ausgeschlossen)

---

### 8. Profile Failover

**Config:**
- `profile_failover.enabled` (bool, default: False)

Bei Error/Timeout: automatisch alternative M3U-Account-Profile versuchen.  
Vor jedem Retry: `AccountStreamLimiter.acquire(timeout=30)`.  
Nach Retry (Erfolg oder Fehler): `AccountStreamLimiter.release()` im `finally`.  
Deaktiviert: verhält sich exakt wie vorher.  
Implementiert in: concurrent wrapper + 2× sequential path.

---

### 9. HTTP Proxy Support

**Datei:** `backend/apps/core/api_utils.py` — `get_stream_proxy(stream_id)`

Liest Proxy-URL aus M3U-Account via UDI (`account.get('proxy')`).  
Concurrent path: `analyze_stream_with_proxy` Wrapper injiziert Proxy per Stream.  
Sequential path: direkt als `proxy=get_stream_proxy(stream['id'])` übergeben.  
FFmpeg: `-http_proxy` Parameter.

---

### 10. Resolution Parsing Fix

**Datei:** `backend/apps/stream/stream_check_utils.py`

`(\d{2,5})x(\d{2,5})` → `(\d{2,5})\s*[x*×]\s*(\d{2,5})`  
Unterstützt jetzt: `1920x1080`, `1920 x 1080`, `1920×1080`, `1920*1080`

---

### 11. Quick Actions (Global Action, Rescore & Resort, Test Missing Stats)

**Neue API-Endpoints:**
- `POST /api/stream-checker/global-action`
- `POST /api/stream-checker/rescore-resort`
- `POST /api/stream-checker/test-streams-without-stats`

**Neue Service-Methoden:**
- `trigger_global_action()` — `_queue_all_channels(force_check=True)`
- `rescore_and_resort()` — alle Channels ohne force_check, kein FFmpeg
- `test_streams_without_stats()` — findet Streams mit fehlenden/unvollständigen Stats

Alle nutzen den bestehenden Queue-Worker → Fortschritt live im UI sichtbar.  
Frontend: 3 neue Buttons (Zap, RotateCcw, TestTube) mit Loading-States.

---

### 12. Basic Authentication

**Datei:** `backend/apps/api/web_api.py`, `docker-compose.yml`

Env-Variablen: `BASIC_AUTH_USER`, `BASIC_AUTH_PASS`  
`before_request` Hook schützt alle Routen inkl. Frontend.  
`/api/health` immer exempt (Docker Healthcheck).  
Deaktiviert wenn beide Variablen leer sind.

---

## Behobene Bugs

| Bug | Schwere | Fix |
|-----|---------|-----|
| Priority-Only Score `50.0` statt `0.5` | Kritisch | `priority / 100.0` normalisiert |
| Priority-Only Streams schrieben N/A Stats in Dispatcharr | Kritisch | `_priority_only` Flag + Batch-Skip |
| Priority-Only Streams wurden für Loop-Probing kandidiert | Mittel | `not s.get('_priority_only')` Filter |
| `_apply_provider_diversification` mutierte Stream-Dicts | Niedrig | `pop()` nach Interleaving |
| Priority-Only Streams beim Rescore & Resort (cached path) Score 0.0 | Mittel | Exclusion-Check im cached-stream-Block |
| BOM-Zeichen in `stream_checker_service.py` | Niedrig | Entfernt |
| Syntax-Fehler in `stream_checker_components.py` (doppelte Zeile) | Kritisch | Behoben |

---

## Audit-Ergebnis

Siehe Abschnitt unten.
