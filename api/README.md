# Golf Plaque GaaS API

**Geometry-as-a-Service** – generate 3-D golf plaque models via REST.

Submit an SVG file and design parameters; receive per-layer STL files (zipped) or a full `.blend` project file.

---

## Content negotiation

Set the `Accept` header to control the output format:

| Accept header | Response |
|---|---|
| `model/stl` *(default)* | ZIP archive of per-layer STL files |
| `application/x-blender` | `.blend` project file (openable in Desktop Blender) |

---

## Generation modes

### `POST /generate/engrave`

Generates a **carved / engraved** golf-course plaque using the `carve_plaque` pipeline.

SVG layers are mapped to golf-course elements (`Water`, `Sand`, `Green`, `Tee`, `Fairway`, `Rough`, `Text`) and Boolean-cut into a solid plaque base.

All settings have defaults – you can omit any or all of them.

```bash
# STL output (default) with custom dimensions
curl -X POST http://localhost:8000/generate/engrave \
     -F "file=@course.svg" \
     -F "plaque_width=120" \
     -F "plaque_height=160" \
     -F "text_mode=ENGRAVE" \
     -H "Accept: model/stl" \
     -o plaque.zip

# .blend project file (all defaults)
curl -X POST http://localhost:8000/generate/engrave \
     -F "file=@course.svg" \
     -H "Accept: application/x-blender" \
     -o plaque.blend
```

### `POST /generate/insert`

Generates a **colour-insert set** using the `build_inserts` pipeline.

Each colour layer is built as a press-fit insert piece; the receiving base plaque has matching cavities.

```bash
# STL output with custom clearance
curl -X POST http://localhost:8000/generate/insert \
     -F "file=@course.svg" \
     -F "plaque_width=120" \
     -F "insert_clearance=0.2" \
     -H "Accept: model/stl" \
     -o inserts.zip

# .blend project file
curl -X POST http://localhost:8000/generate/insert \
     -F "file=@course.svg" \
     -H "Accept: application/x-blender" \
     -o inserts.blend
```

---

## STL layer grouping

When exporting to STL, objects are grouped by golf-course layer into separate files:

| File | Contents |
|---|---|
| `base_and_text.stl` | Plaque base + all `Text.*` objects (single-filament piece) |
| `water.stl` | All `Water.*` objects |
| `sand.stl` | All `Sand.*` objects |
| `green.stl` | All `Green.*` objects |
| `tee.stl` | All `Tee.*` objects |
| `fairway.stl` | All `Fairway.*` objects |
| `rough.stl` | All `Rough.*` objects |
| `misc.stl` | Any objects that don't match a known prefix |

---

## Health check

```bash
curl http://localhost:8000/health
```

Returns:

```json
{
  "status": "ok",
  "blender_bin": "/usr/local/bin/blender",
  "blender_available": true
}
```

---

## Concurrency

Each request is handled in an isolated `/tmp/plaque_<uuid>/` directory.  
Temp files are deleted automatically after the response is sent.
