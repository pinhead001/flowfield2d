#!/usr/bin/env python3
"""rasprobe - interrogate an HEC-RAS 2025 build and its project files (Phase 0).

Subcommands
  inventory    --ras-dir DIR --out FILE           files, hashes, Windows-executable/.NET info, deps, URLs
  dotnet       --ras-dir DIR --out FILE           public types + command-like strings (static)
  h5schema     PATH... --out FILE                 HDF5 structure, string padding, fingerprints
  h5diff       A.json B.json [--out FILE]         schema differences
  snapshot     DIR --out FILE [--max-hash-mb N]   file tree with hashes
  snapdiff     A.json B.json [--out FILE]         added / removed / modified files
  smoke        --spec FILE.toml --out DIR [--only ID ...] [--non-interactive]
  report       --dir PROBE_DIR --out FILE.md      capability matrix + suggested tier
  make-terrain --out FILE.tif (--like TILE.tif | --epsg N) [--size 256]

Reads only; nothing here edits RAS files. Python 3.11+. h5py for the h5* and
smoke-compare commands; pefile/dnfile add Windows-executable and .NET details when installed;
rasterio is needed for make-terrain only. See docs/PROBE_PROCEDURE.md.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import fnmatch
import hashlib
import json
import re
import shutil
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cliprobe  # noqa: E402

try:
    import h5py  # type: ignore
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover
    h5py = None
    np = None
try:
    import pefile  # type: ignore
except ImportError:  # pragma: no cover
    pefile = None
try:
    import dnfile  # type: ignore
except ImportError:  # pragma: no cover
    dnfile = None

H5_EXTS = {".h5", ".hdf", ".hdf5"}
PE_EXTS = {".exe", ".dll"}
CONFIG_EXTS = {".json", ".xml", ".config", ".ini", ".yaml", ".yml", ".toml", ".txt", ".md"}
CLI_FRAMEWORKS = {
    "system.commandline": "System.CommandLine", "spectre.console.cli": "Spectre.Console.Cli",
    "commandlineparser": "CommandLineParser", "mcmaster.extensions.commandlineutils": "McMaster",
    "cocona": "Cocona", "clifx": "CliFx", "consoleappframework": "ConsoleAppFramework",
    "powerargs": "PowerArgs", "oakton": "Oakton",
}
NATIVE_PATTERNS = {
    "hdf5": r"hdf5", "gdal": r"gdal", "proj": r"(^|[^a-z])proj", "sqlite": r"sqlite",
    "cuda": r"cud(a|art|nn)|nvrtc|cublas|cusparse", "opencl": r"opencl", "netcdf": r"netcdf",
    "mkl": r"mkl_", "tbb": r"tbb", "onnx": r"onnx", "skia": r"skia", "avalonia": r"avalonia",
    "dss": r"(^|[^a-z])(hec)?dss|javaheclib",
}
NOISE_HOSTS = ("w3.org", "schemas.microsoft.com", "schemas.openxmlformats.org", "xmlsoap.org",
               "purl.org", "ns.adobe.com", "json-schema.org", "microsoft.com/winfx", "apache.org",
               "github.com/dotnet", "aka.ms/dotnet", "go.microsoft.com/fwlink")
SUBSYSTEMS = {1: "native", 2: "windows_gui", 3: "windows_console"}
URL_RE = re.compile(rb"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{4,200}")
URL16_RE = re.compile(rb"h\x00t\x00t\x00p\x00(?:s\x00)?:\x00/\x00/\x00(?:[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]\x00){4,200}")
API_NS_RE = re.compile(r"(?i)(^|\.)(api|public|scripting|automation|sdk|client|headless|cli|console)(\.|$)")
CMD_TYPE_RE = re.compile(r"(?i)(command|verb|cli|handler|subcommand)s?$")
DOMAIN_WORDS = {
    "terrain", "terrains", "mesh", "geometry", "geometries", "plan", "plans", "compute", "run",
    "simulate", "simulation", "export", "import", "bc", "boundary", "boundaries", "result",
    "results", "project", "model", "layer", "landcover", "roughness", "map", "raster",
    "validate", "convert", "migrate", "info", "add", "create", "new", "open", "list",
}
CMD_STR_RE = re.compile(r"^[a-z][a-z0-9-]{1,24}(?: [a-z][a-z0-9-]{1,24}){0,2}$")
OPT_STR_RE = re.compile(r"^--?[a-z][a-z0-9-]{1,30}$")


# --------------------------------------------------------------------------- helpers


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def sha256(path: Path, max_mb: float | None = None) -> str | None:
    if max_mb is not None and path.stat().st_size > max_mb * 2**20:
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(2**20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _host(url: str) -> str:
    m = re.match(r"https?://([^/:?#]+)", url)
    return m.group(1).lower() if m else ""


def _is_noise(url: str) -> bool:
    return any(n in url.lower() for n in NOISE_HOSTS)


# --------------------------------------------------------------------------- inventory


def pe_info(path: Path) -> dict[str, Any]:
    if pefile is None:
        return {}
    try:
        pe = pefile.PE(str(path), fast_load=True)
    except Exception:  # not a Windows executable, or unreadable
        return {"pe": False}
    try:
        dirs = pe.OPTIONAL_HEADER.DATA_DIRECTORY
        info: dict[str, Any] = {
            "pe": True,
            "machine": hex(pe.FILE_HEADER.Machine),
            "subsystem": SUBSYSTEMS.get(pe.OPTIONAL_HEADER.Subsystem, str(pe.OPTIONAL_HEADER.Subsystem)),
            "is_dotnet": len(dirs) > 14 and dirs[14].VirtualAddress != 0,
        }
        try:
            pe.parse_data_directories(
                directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
            strings: dict[str, str] = {}
            for fi in getattr(pe, "FileInfo", None) or []:
                for entry in fi if isinstance(fi, list) else [fi]:
                    if getattr(entry, "Key", b"") == b"StringFileInfo":
                        for table in entry.StringTable:
                            for k, v in table.entries.items():
                                strings[k.decode(errors="replace")] = v.decode(errors="replace")
            info["version_strings"] = strings
        except Exception as exc:  # resource parsing is best effort
            info["version_error"] = str(exc)
        return info
    finally:
        pe.close()


def scan_urls(data: bytes) -> set[str]:
    urls = {m.group(0).decode("ascii", "replace") for m in URL_RE.finditer(data)}
    urls |= {m.group(0).decode("utf-16-le", "replace") for m in URL16_RE.finditer(data)}
    return {u.rstrip(".,;)'\"") for u in urls}


def inventory(ras_dir: Path, scan_binaries: bool = True, max_scan_mb: float = 256) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    urls: dict[str, set[str]] = {}
    runtimeconfigs: list[dict[str, Any]] = []
    deps_libs: dict[str, str] = {}
    native: dict[str, list[str]] = {}
    configs: list[str] = []
    total = 0
    for p in sorted(ras_dir.rglob("*")):
        if not p.is_file():
            continue
        r = rel(p, ras_dir)
        size = p.stat().st_size
        total += size
        rec: dict[str, Any] = {"path": r, "size": size, "sha256": sha256(p)}
        ext = p.suffix.lower()
        name = p.name.lower()
        if ext in PE_EXTS:
            rec.update(pe_info(p))
            for kind, pat in NATIVE_PATTERNS.items():
                if re.search(pat, name) and not rec.get("is_dotnet"):
                    native.setdefault(kind, []).append(r)
        if name.endswith(".runtimeconfig.json"):
            try:
                opts = read_json(p).get("runtimeOptions", {})
                fws = opts.get("frameworks") or ([opts["framework"]] if "framework" in opts else [])
                runtimeconfigs.append({"file": r, "tfm": opts.get("tfm"),
                                       "frameworks": fws,
                                       "included_frameworks": opts.get("includedFrameworks", [])})
            except (ValueError, OSError) as exc:
                runtimeconfigs.append({"file": r, "error": str(exc)})
        if name.endswith(".deps.json"):
            try:
                for key, val in (read_json(p).get("libraries") or {}).items():
                    deps_libs[key] = val.get("type", "")
            except (ValueError, OSError):
                pass
        if ext in CONFIG_EXTS and size < 5 * 2**20:
            configs.append(r)
        scan = (ext in CONFIG_EXTS and size < 5 * 2**20) or (
            scan_binaries and ext in PE_EXTS and size <= max_scan_mb * 2**20)
        if scan:
            data = p.read_bytes()
            for u in scan_urls(data):
                urls.setdefault(u, set()).add(r)
            if ext == ".exe":
                rec["dotnet_apphost_hint"] = b"hostfxr" in data or b"DOTNET_ROOT" in data
        files.append(rec)
    cli_libs = sorted({label for key in deps_libs for lib, label in CLI_FRAMEWORKS.items()
                       if key.lower().split("/")[0] == lib})
    exes = [{k: f.get(k) for k in ("path", "subsystem", "is_dotnet", "dotnet_apphost_hint")}
            | {"file_version": (f.get("version_strings") or {}).get("FileVersion"),
               "product_version": (f.get("version_strings") or {}).get("ProductVersion")}
            for f in files if f["path"].lower().endswith(".exe")]
    url_list = [{"url": u, "host": _host(u), "noise": _is_noise(u), "files": sorted(v)}
                for u, v in sorted(urls.items())]
    return {
        "tool": "rasprobe.inventory", "taken": now(), "ras_dir": str(ras_dir),
        "summary": {
            "files": len(files), "total_mb": round(total / 2**20, 1), "executables": exes,
            "dotnet_runtimeconfigs": runtimeconfigs, "cli_frameworks": cli_libs,
            "native_libs": native,
            "hosts": sorted({u["host"] for u in url_list if not u["noise"]}),
            "pefile": pefile is not None,
        },
        "deps_libraries": deps_libs, "config_files": configs, "urls": url_list, "files": files,
    }


# --------------------------------------------------------------------------- .NET metadata


def _user_strings(dn: Any, limit: int = 200_000) -> list[str]:
    us = getattr(dn.net, "user_strings", None)
    data = getattr(us, "__data__", None) if us is not None else None
    if not data:
        return []
    out: list[str] = []
    off, n = 1, 0
    while off < len(data) and n < limit:
        res = us.get_with_size(off)
        if not res:
            break
        raw, size = res
        if size <= 0:
            break
        try:
            item = us.get(off)
            text = getattr(item, "value", None)
            if text is None:
                text = raw[: len(raw) - (len(raw) % 2)].decode("utf-16-le", "replace")
        except Exception:
            text = raw[: len(raw) - (len(raw) % 2)].decode("utf-16-le", "replace")
        if text:
            out.append(text)
        off += size
        n += 1
    return out


def dotnet_scan(ras_dir: Path, max_types: int = 300) -> dict[str, Any]:
    if dnfile is None:
        raise SystemExit("dnfile is not installed (uv add dnfile)")
    assemblies = []
    seeds: Counter[str] = Counter()
    options: Counter[str] = Counter()
    for p in sorted(ras_dir.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in PE_EXTS):
            continue
        try:
            dn = dnfile.dnPE(str(p))
        except Exception:
            continue
        try:
            md = getattr(getattr(dn, "net", None), "mdtables", None)
            if not md or not md.TypeDef:
                continue
            asm_rows = md.Assembly.rows if md.Assembly else []
            name = str(asm_rows[0].Name) if asm_rows else p.stem
            types = [(str(r.TypeNamespace or ""), str(r.TypeName or ""),
                      bool(getattr(r.Flags, "tdPublic", False))) for r in md.TypeDef.rows]
            public = sorted(f"{ns}.{nm}" if ns else nm for ns, nm, pub in types
                            if pub and nm != "<Module>")
            namespaces = Counter(ns for ns, _nm, pub in types if pub and ns)
            strings = _user_strings(dn)
            cmd_strings = sorted({s for s in strings if CMD_STR_RE.match(s)
                                  and s.split()[0] in DOMAIN_WORDS})
            opt_strings = sorted({s for s in strings if OPT_STR_RE.match(s)})
            for s in cmd_strings:
                seeds[s] += 1
            for s in opt_strings:
                options[s] += 1
            assemblies.append({
                "file": rel(p, ras_dir), "assembly": name,
                "types": len(types), "public_types": len(public),
                "api_like_namespaces": sorted(ns for ns in namespaces if API_NS_RE.search(ns)),
                "command_like_types": sorted(f"{ns}.{nm}" if ns else nm
                                             for ns, nm, _pub in types if CMD_TYPE_RE.search(nm)),
                "command_like_strings": cmd_strings[:200], "option_strings": opt_strings[:200],
                "public_type_sample": public[:max_types],
            })
        finally:
            dn.close()
    return {"tool": "rasprobe.dotnet", "taken": now(), "ras_dir": str(ras_dir),
            "assemblies": assemblies,
            "seed_names": [s for s, _ in seeds.most_common(60)],
            "option_strings": [s for s, _ in options.most_common(100)]}


# --------------------------------------------------------------------------- HDF5 schema


def h5_type(tid: Any) -> dict[str, Any]:
    t = h5py.h5t
    cls = tid.get_class()
    if cls == t.STRING:
        d: dict[str, Any] = {"class": "string", "variable": bool(tid.is_variable_str())}
        if not d["variable"]:
            d["size"] = tid.get_size()
        d["strpad"] = {t.STR_NULLTERM: "NULLTERM", t.STR_NULLPAD: "NULLPAD",
                       t.STR_SPACEPAD: "SPACEPAD"}.get(tid.get_strpad(), str(tid.get_strpad()))
        d["cset"] = {t.CSET_ASCII: "ASCII", t.CSET_UTF8: "UTF8"}.get(tid.get_cset(), str(tid.get_cset()))
        return d
    if cls == t.INTEGER:
        return {"class": "int", "size": tid.get_size(), "signed": tid.get_sign() == t.SGN_2,
                "order": "LE" if tid.get_order() == t.ORDER_LE else "BE"}
    if cls == t.FLOAT:
        return {"class": "float", "size": tid.get_size(),
                "order": "LE" if tid.get_order() == t.ORDER_LE else "BE"}
    if cls == t.COMPOUND:
        return {"class": "compound", "size": tid.get_size(), "members": [
            {"name": tid.get_member_name(i).decode("utf-8", "replace"),
             "offset": tid.get_member_offset(i), "type": h5_type(tid.get_member_type(i))}
            for i in range(tid.get_nmembers())]}
    if cls == t.ENUM:
        return {"class": "enum", "base": h5_type(tid.get_super()), "members": {
            tid.get_member_name(i).decode("utf-8", "replace"): int(tid.get_member_value(i))
            for i in range(tid.get_nmembers())}}
    if cls == t.ARRAY:
        return {"class": "array", "dims": list(tid.get_array_dims()), "base": h5_type(tid.get_super())}
    if cls == t.VLEN:
        return {"class": "vlen", "base": h5_type(tid.get_super())}
    if cls == t.OPAQUE:
        return {"class": "opaque", "size": tid.get_size()}
    if cls == t.REFERENCE:
        return {"class": "reference", "size": tid.get_size()}
    if cls == t.BITFIELD:
        return {"class": "bitfield", "size": tid.get_size()}
    return {"class": f"other:{cls}", "size": tid.get_size()}


def _short(value: Any) -> Any:
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
        return text if len(text) <= 200 else text[:200] + "…"
    if np is not None and isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _short(value.item())
        if value.size <= 8:
            return [_short(v) for v in value.reshape(-1).tolist()]
        return f"<array shape={list(value.shape)} dtype={value.dtype}>"
    if np is not None and isinstance(value, np.generic):
        return _short(value.item())
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…"
    return value


def _attrs(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in obj.attrs.keys():
        rec: dict[str, Any] = {}
        try:
            aid = h5py.h5a.open(obj.id, name.encode("utf-8"))
            ftype = aid.get_type()
            rec["type"] = h5_type(ftype)
            shape = aid.get_space().shape
            rec["shape"] = list(shape) if shape is not None else None
            if rec["type"]["class"] == "string" and not rec["type"]["variable"]:
                # Read with memory type == file type so full-width NULLTERM values survive.
                buf = np.empty(shape if shape is not None else (), dtype=f"S{rec['type']['size']}")
                aid.read(buf, mtype=ftype)
                rec["value"] = _short(buf)
                vals = buf.reshape(-1).tolist() if buf.shape else [buf.item()]
                rec["full_width"] = any(len(v.rstrip(b"\x00")) == rec["type"]["size"] for v in vals)
            else:
                rec["value"] = _short(obj.attrs[name])
        except Exception as exc:  # record, never fail the walk
            rec["error"] = str(exc)
        out[name] = rec
    return out


def _dataset(ds: Any) -> dict[str, Any]:
    plist = ds.id.get_create_plist()
    filters = []
    for i in range(plist.get_nfilters()):
        code, _flags, values, name = plist.get_filter(i)
        filters.append({"code": int(code), "name": name.decode("utf-8", "replace"),
                        "values": [int(v) for v in values]})
    return {"kind": "dataset", "shape": list(ds.shape) if ds.shape is not None else None,
            "maxshape": [(-1 if m is None else m) for m in (ds.maxshape or [])],
            "chunks": list(ds.chunks) if ds.chunks else None, "filters": filters,
            "type": h5_type(ds.id.get_type()), "attrs": _attrs(ds)}


def h5_walk(path: Path) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    seen: dict[tuple[int, int], str] = {}
    with h5py.File(path, "r", locking=False) as f:
        def visit(group: Any, gpath: str) -> None:
            objects[gpath] = {"kind": "group", "attrs": _attrs(group)}
            for name in group.keys():
                cpath = f"{gpath.rstrip('/')}/{name}"
                link = group.get(name, getlink=True)
                if isinstance(link, h5py.SoftLink):
                    objects[cpath] = {"kind": "softlink", "target": link.path}
                    continue
                if isinstance(link, h5py.ExternalLink):
                    objects[cpath] = {"kind": "extlink", "file": link.filename, "target": link.path}
                    continue
                obj = group[name]
                info = h5py.h5o.get_info(obj.id)
                key = (info.fileno, info.addr)
                if key in seen:
                    objects[cpath] = {"kind": "hardlink", "of": seen[key]}
                    continue
                seen[key] = cpath
                if isinstance(obj, h5py.Group):
                    visit(obj, cpath)
                else:
                    objects[cpath] = _dataset(obj)
        visit(f, "/")
    return objects


def fingerprint(objects: dict[str, Any]) -> str:
    items = []
    for path, info in sorted(objects.items()):
        sig: dict[str, Any] = {"p": path, "k": info["kind"]}
        if info["kind"] == "dataset":
            sig.update(t=info["type"], r=len(info["shape"] or []),
                       f=[x["name"] for x in info["filters"]])
        if "attrs" in info:
            sig["a"] = sorted([n, json.dumps(a.get("type"), sort_keys=True)]
                              for n, a in info["attrs"].items())
        if info["kind"] in ("softlink", "extlink", "hardlink"):
            sig["x"] = info.get("target") or info.get("of")
        items.append(sig)
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()[:16]


def h5schema(paths: list[Path]) -> dict[str, Any]:
    if h5py is None:
        raise SystemExit("h5py is not installed")
    files: dict[str, Any] = {}
    for root in paths:
        targets = ([root] if root.is_file() else
                   sorted(p for p in root.rglob("*") if p.suffix.lower() in H5_EXTS and p.is_file()))
        for p in targets:
            key = p.name if root.is_file() else rel(p, root)
            try:
                objs = h5_walk(p)
                full_width = sorted(f"{op}@{an}" for op, info in objs.items()
                                    for an, a in (info.get("attrs") or {}).items() if a.get("full_width"))
                files[key] = {"path": str(p), "fingerprint": fingerprint(objs),
                              "groups": sum(1 for o in objs.values() if o["kind"] == "group"),
                              "datasets": sum(1 for o in objs.values() if o["kind"] == "dataset"),
                              "full_width_strings": full_width, "objects": objs}
            except Exception as exc:
                files[key] = {"path": str(p), "error": str(exc)}
    return {"tool": "rasprobe.h5schema", "taken": now(), "roots": [str(p) for p in paths],
            "files": files}


def _diff_objects(a: dict[str, Any], b: dict[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {k: [] for k in (
        "added", "removed", "kind_changed", "type_changed", "rank_changed", "shape_changed",
        "filters_changed", "attrs_added", "attrs_removed", "attr_type_changed",
        "attr_value_changed")}
    out["added"] = sorted(set(b) - set(a))
    out["removed"] = sorted(set(a) - set(b))
    for path in sorted(set(a) & set(b)):
        x, y = a[path], b[path]
        if x["kind"] != y["kind"]:
            out["kind_changed"].append([path, x["kind"], y["kind"]])
            continue
        if x["kind"] == "dataset":
            if x["type"] != y["type"]:
                out["type_changed"].append(path)
            if len(x["shape"] or []) != len(y["shape"] or []):
                out["rank_changed"].append(path)
            elif x["shape"] != y["shape"]:
                out["shape_changed"].append([path, x["shape"], y["shape"]])
            if [f["name"] for f in x["filters"]] != [f["name"] for f in y["filters"]]:
                out["filters_changed"].append(path)
        xa, ya = x.get("attrs") or {}, y.get("attrs") or {}
        out["attrs_added"] += [f"{path}@{n}" for n in sorted(set(ya) - set(xa))]
        out["attrs_removed"] += [f"{path}@{n}" for n in sorted(set(xa) - set(ya))]
        for n in sorted(set(xa) & set(ya)):
            if xa[n].get("type") != ya[n].get("type"):
                out["attr_type_changed"].append(f"{path}@{n}")
            elif xa[n].get("value") != ya[n].get("value"):
                out["attr_value_changed"].append([f"{path}@{n}", xa[n].get("value"), ya[n].get("value")])
    return out


def h5diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    fa, fb = a["files"], b["files"]
    pairs = [(k, k) for k in sorted(set(fa) & set(fb))]
    if not pairs and len(fa) == 1 and len(fb) == 1:
        pairs = [(next(iter(fa)), next(iter(fb)))]
    result: dict[str, Any] = {"only_in_a": sorted(set(fa) - {p[0] for p in pairs}),
                              "only_in_b": sorted(set(fb) - {p[1] for p in pairs}), "files": {}}
    for ka, kb in pairs:
        if "objects" not in fa[ka] or "objects" not in fb[kb]:
            result["files"][ka] = {"error": fa[ka].get("error") or fb[kb].get("error")}
            continue
        d = _diff_objects(fa[ka]["objects"], fb[kb]["objects"])
        d["fingerprint_equal"] = fa[ka]["fingerprint"] == fb[kb]["fingerprint"]
        result["files"][ka if ka == kb else f"{ka} -> {kb}"] = d
    return result


# --------------------------------------------------------------------------- snapshots


def snapshot(root: Path, max_hash_mb: float = 512) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        st = p.stat()
        rec: dict[str, Any] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        try:
            rec["sha256"] = sha256(p, max_hash_mb)
        except OSError as exc:  # locked by RAS
            rec["sha256"], rec["error"] = None, str(exc)
        files[rel(p, root)] = rec
    return {"tool": "rasprobe.snapshot", "taken": now(), "root": str(root), "files": files}


def snapdiff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, list[str]]:
    fa, fb = a["files"], b["files"]
    modified = []
    for k in sorted(set(fa) & set(fb)):
        x, y = fa[k], fb[k]
        if x.get("sha256") and y.get("sha256"):
            changed = x["sha256"] != y["sha256"]
        else:
            changed = x["size"] != y["size"] or x["mtime_ns"] != y["mtime_ns"]
        if changed:
            modified.append(k)
    return {"added": sorted(set(fb) - set(fa)), "removed": sorted(set(fa) - set(fb)),
            "modified": modified}


# --------------------------------------------------------------------------- smoke runner


class _Vars(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(f"unknown variable {{{key}}} in smoke spec")


def _fmt(value: Any, v: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format_map(_Vars(v))
    if isinstance(value, list):
        return [_fmt(x, v) for x in value]
    return value


def compare_numeric(a_root: Path, b_root: Path, pattern: str, max_report: int = 20) -> dict[str, Any]:
    """Max |a-b| over numeric HDF5 datasets present in both trees (determinism, GPU parity)."""
    if h5py is None:
        return {"error": "h5py not installed"}
    report: dict[str, Any] = {"files": {}, "max_abs_diff": 0.0, "nan_mismatch": 0,
                              "identical_files": [], "compared": 0}
    for pa in sorted(a_root.rglob("*")):
        r = rel(pa, a_root)
        pb = b_root / r
        if not (pa.is_file() and pb.is_file() and fnmatch.fnmatch(r, pattern)):
            continue
        if sha256(pa) == sha256(pb):
            report["identical_files"].append(r)
            continue
        if pa.suffix.lower() not in H5_EXTS:
            report["files"][r] = {"binary_differs": True}
            continue
        diffs: list[tuple[str, float, int]] = []
        with h5py.File(pa, "r", locking=False) as fa, h5py.File(pb, "r", locking=False) as fb:
            def visit(name: str, obj: Any, fb: Any = fb,
                      diffs: list[tuple[str, float, int]] = diffs) -> None:
                if not isinstance(obj, h5py.Dataset) or name not in fb:
                    return
                other = fb[name]
                if (not isinstance(other, h5py.Dataset) or obj.dtype.kind not in "fiu"
                        or obj.shape != other.shape or obj.size > 50_000_000 or obj.size == 0):
                    return
                x = obj[()].astype("float64")
                y = other[()].astype("float64")
                nan_mis = int(np.count_nonzero(np.isnan(x) != np.isnan(y)))
                d = np.abs(x - y)
                mx = float(np.nanmax(d)) if np.any(~np.isnan(d)) else 0.0
                if mx > 0 or nan_mis:
                    diffs.append((name, mx, nan_mis))
                report["compared"] += 1
            fa.visititems(visit)
        diffs.sort(key=lambda t: -t[1])
        report["files"][r] = {"top": [{"dataset": n, "max_abs_diff": m, "nan_mismatch": k}
                                      for n, m, k in diffs[:max_report]]}
        for _n, m, k in diffs:
            report["max_abs_diff"] = max(report["max_abs_diff"], m)
            report["nan_mismatch"] += k
    report["identical"] = report["max_abs_diff"] == 0 and report["nan_mismatch"] == 0 and not any(
        f.get("binary_differs") for f in report["files"].values())
    return report


def _check_expect(expect: dict[str, Any], res: cliprobe.CallResult | None,
                  diff: dict[str, list[str]], duration: float) -> list[dict[str, Any]]:
    checks = []
    out = ((res.stdout + "\n" + res.stderr) if res else "").lower()

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    if "exit_code" in expect:
        add("exit_code", res is not None and res.exit_code == expect["exit_code"],
            res.exit_code if res else None)
    if expect.get("exit_code_nonzero"):
        add("exit_code_nonzero", res is not None and res.exit_code not in (0, None),
            res.exit_code if res else None)
    if expect.get("no_window"):
        add("no_window", res is None or res.window_seen is not True, res.window_seen if res else None)
    for key, field in (("stdout_contains", "stdout"), ("stderr_contains", "stderr")):
        if key in expect:
            text = (getattr(res, field) if res else "").lower()
            add(key, expect[key].lower() in text)
    if "output_contains" in expect:
        add("output_contains", expect["output_contains"].lower() in out)
    for key in ("created", "modified"):
        names = diff.get("added" if key == "created" else "modified", [])
        for pattern in expect.get(key, []):
            add(f"{key}:{pattern}", any(fnmatch.fnmatch(n, pattern) for n in names))
    for pattern in expect.get("not_created", []):
        add(f"not_created:{pattern}", not any(fnmatch.fnmatch(n, pattern) for n in diff.get("added", [])))
    if "max_duration_s" in expect:
        add("max_duration_s", duration <= expect["max_duration_s"], duration)
    return checks


def _copy_seed(seed: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(seed, dest)


def run_op(op: dict[str, Any], base_vars: dict[str, str], out_dir: Path,
           interactive: bool, projects: dict[str, str]) -> dict[str, Any]:
    op_id = op["id"]
    v = dict(base_vars)
    v["op"] = op_id
    record: dict[str, Any] = {"id": op_id, "capability": op.get("capability"),
                              "method": op.get("method", "cli"), "notes": op.get("notes"),
                              "started": now()}
    try:
        scratch = Path(_fmt(v["scratch"], v)) / op_id
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        v["opdir"] = str(scratch)
        if op.get("fresh_copy", True) and "seed" in v:
            _copy_seed(_fmt(v["seed"], v), scratch / "project")
            v["project"] = str(scratch / "project")
            projects[op_id] = v["project"]
        snap_dirs = [Path(d) for d in _fmt(op.get("snapshot", ["{project}"] if "project" in v else []), v)]
        before = {d: snapshot(d) for d in snap_dirs}
        for step in op.get("pre", []):
            pre = cliprobe.run(_fmt(step, v), float(op.get("pre_timeout_s", 300)),
                               cwd=_fmt(op.get("pre_cwd", "{opdir}"), v))
            record.setdefault("pre", []).append({"argv": pre.argv, "exit_code": pre.exit_code,
                                                 "timed_out": pre.timed_out})
        if op.get("manual"):
            if not interactive:
                record.update(status="skipped-manual", reason="non-interactive run")
                return record
            print(f"\n[{op_id}] MANUAL STEP:\n  {_fmt(op['manual'], v)}")
            input("  Press Enter when finished... ")
        results: list[cliprobe.CallResult] = []
        parallel = int(op.get("parallel", 1))
        if op.get("argv"):
            cwd = _fmt(op.get("cwd", "{project}" if "project" in v else "{opdir}"), v)
            timeout = float(op.get("timeout_s", 600))
            if parallel > 1:
                copies = []
                for i in range(1, parallel + 1):
                    vi = dict(v)
                    if "project" in v:
                        dest = scratch / f"project_{i}"
                        _copy_seed(_fmt(v["seed"], v), dest)
                        vi["project"] = str(dest)
                    copies.append(vi)
                with cf.ThreadPoolExecutor(max_workers=parallel) as pool:
                    futs = [pool.submit(cliprobe.run, _fmt(op["argv"], vi), timeout,
                                        _fmt(op.get("cwd", "{project}"), vi)) for vi in copies]
                    results = [f.result() for f in futs]
            else:
                results = [cliprobe.run(_fmt(op["argv"], v), timeout, cwd=cwd)]
        res = results[0] if results else None
        after = {d: snapshot(d) for d in snap_dirs}
        diff: dict[str, list[str]] = {"added": [], "removed": [], "modified": []}
        h5changes: dict[str, Any] = {}
        for d in snap_dirs:
            dd = snapdiff(before[d], after[d])
            for k in diff:
                diff[k] += dd[k]
            if h5py is not None:
                in_project = "project" in v and Path(d) == Path(v["project"]) and v.get("seed")
                for name in dd["added"] + dd["modified"]:
                    if Path(name).suffix.lower() in H5_EXTS:
                        new = h5schema([d / name])
                        entry = {"after_fingerprint": next(iter(new["files"].values())).get("fingerprint")}
                        seed_file = Path(_fmt(v["seed"], v)) / name if in_project else None
                        if seed_file is not None and seed_file.is_file():
                            entry["diff"] = h5diff(h5schema([seed_file]), new)
                        h5changes[name] = entry
        if int(op.get("repeat", 1)) > 1 and op.get("argv") and "project" in v:
            second = scratch / "project_r2"
            _copy_seed(_fmt(v["seed"], v), second)
            v2 = dict(v)
            v2["project"] = str(second)
            r2 = cliprobe.run(_fmt(op["argv"], v2), float(op.get("timeout_s", 600)),
                              cwd=_fmt(op.get("cwd", "{project}"), v2))
            record["repeat_run"] = {"exit_code": r2.exit_code, "duration_s": r2.duration_s}
            record["determinism"] = compare_numeric(Path(v["project"]), second,
                                                    op.get("compare_glob", "*"))
        if op.get("compare_with") and op["compare_with"] in projects and "project" in v:
            record["comparison"] = compare_numeric(Path(projects[op["compare_with"]]),
                                                   Path(v["project"]), op.get("compare_glob", "*"))
        duration = max((r.duration_s for r in results), default=0.0)
        checks = _check_expect(op.get("expect", {}), res, diff, duration)
        for i, r in enumerate(results):
            suffix = "" if len(results) == 1 else f".{i + 1}"
            (out_dir / f"{op_id}{suffix}.stdout.txt").write_text(r.stdout, encoding="utf-8")
            (out_dir / f"{op_id}{suffix}.stderr.txt").write_text(r.stderr, encoding="utf-8")
        timed_out = any(r.timed_out for r in results)
        launch_failed = any(r.exit_code is None and not r.timed_out for r in results)
        status = ("error" if launch_failed else
                  "timeout" if timed_out and not op.get("expect", {}).get("timeout") else
                  "pass" if all(c["ok"] for c in checks) else "fail")
        record.update({
            "status": status,
            "runs": [{"argv": r.argv, "exit_code": r.exit_code, "duration_s": r.duration_s,
                      "timed_out": r.timed_out, "window_seen": r.window_seen,
                      "stdout_tail": r.stdout[-2000:], "stderr_tail": r.stderr[-2000:]}
                     for r in results],
            "window_seen": any(r.window_seen for r in results) if results else None,
            "files": diff, "h5_changes": h5changes, "checks": checks,
        })
    except Exception as exc:  # spec or environment problem - recorded, not raised
        record.update(status="error", error=f"{type(exc).__name__}: {exc}")
    record["finished"] = now()
    return record


def smoke(spec_path: Path, out_dir: Path, only: list[str], interactive: bool) -> list[dict[str, Any]]:
    spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
    base_vars = {k: str(v) for k, v in (spec.get("vars") or {}).items()}
    base_vars.setdefault("probe_dir", str(Path(__file__).resolve().parent))
    base_vars.setdefault("out", str(out_dir))
    base_vars.setdefault("scratch", str(out_dir / "_scratch"))
    out_dir.mkdir(parents=True, exist_ok=True)
    projects: dict[str, str] = {}
    records = []
    for op in spec.get("op", []):
        if only and op["id"] not in only:
            continue
        rec = run_op(op, base_vars, out_dir, interactive, projects)
        write_json(out_dir / f"{op['id']}.json", rec)
        print(f"{op['id']:<24} {rec['status']}")
        records.append(rec)
    return records


# --------------------------------------------------------------------------- report

CORE_CAPS = ["terrain", "mesh", "plan", "compute", "export"]


def suggest_tier(records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    def passed(cap: str, methods: set[str]) -> bool:
        return any(r.get("capability") == cap and r.get("method", "cli") in methods
                   and r.get("status") == "pass" and r.get("window_seen") is not True
                   for r in records)

    trace = [f"{cap}: headless CLI pass = {passed(cap, {'cli'})}" for cap in CORE_CAPS]
    bc_ok = passed("bc", {"cli", "h5edit"})
    err_ok = passed("compute_error", {"cli"})
    trace += [f"bc: CLI or template edit pass = {bc_ok}",
              f"compute_error: fails cleanly with a named error = {err_ok}"]
    if all(passed(c, {"cli"}) for c in CORE_CAPS) and bc_ok and err_ok:
        return "A", trace
    if passed("compute", {"cli"}) and err_ok:
        return "B", trace
    return "C", trace


def report(probe_dir: Path) -> str:
    lines = [f"# Probe report — `{probe_dir.name}`", "", f"Generated {now()} by rasprobe.", ""]
    inv_p = probe_dir / "inventory.json"
    if inv_p.exists():
        inv = read_json(inv_p)["summary"]
        lines += ["## Inventory", "", f"- files: {inv['files']} ({inv['total_mb']} MB)",
                  f"- CLI frameworks in deps: {', '.join(inv['cli_frameworks']) or 'none found'}",
                  f"- .NET runtimeconfigs: {json.dumps(inv['dotnet_runtimeconfigs'])}",
                  f"- native libraries: {json.dumps(inv['native_libs'])}",
                  f"- non-noise hosts embedded: {', '.join(inv['hosts']) or 'none'}", "",
                  "| executable | subsystem | .NET | apphost | file version |", "|---|---|---|---|---|"]
        lines += [f"| `{e['path']}` | {e.get('subsystem')} | {e.get('is_dotnet')} | "
                  f"{e.get('dotnet_apphost_hint')} | {e.get('file_version')} |"
                  for e in inv["executables"]]
        lines.append("")
    for cli_json in sorted(probe_dir.glob("cli*/cli_tree.json")):
        tree = read_json(cli_json)
        helped = [n for n in tree["nodes"] if n["status"] == "help"]
        lines += [f"## CLI surface ({cli_json.parent.name})", "",
                  f"- version: `{(tree.get('version') or {}).get('text', 'unknown')}`",
                  f"- {len(helped)} of {len(tree['nodes'])} paths returned help; "
                  f"{tree['calls']} calls; {len(tree['skipped'])} skipped",
                  f"- windows seen: {sum(1 for n in tree['nodes'] if n.get('window_seen'))}; "
                  f"timeouts: {sum(1 for n in tree['nodes'] if n['status'] == 'timeout')}",
                  f"- detail: `{cli_json.parent.name}/cli_tree.md`", ""]
        root = next((n for n in tree["nodes"] if not n["path"]), None)
        if root and root.get("help"):
            lines += [f"- `{c['name']}` — {c['description']}" for c in root["help"]["commands"]]
            lines.append("")
    dn_p = probe_dir / "dotnet.json"
    if dn_p.exists():
        dn = read_json(dn_p)
        api = sorted({ns for a in dn["assemblies"] for ns in a["api_like_namespaces"]})
        cmd_types = sorted({t for a in dn["assemblies"] for t in a["command_like_types"]})
        lines += ["## .NET metadata", "", f"- API-like namespaces: {', '.join(api[:40]) or 'none'}",
                  f"- command-like types: {', '.join(cmd_types[:40]) or 'none'}",
                  f"- seed names: {', '.join(dn['seed_names'][:40]) or 'none'}", ""]
    for h5_json in sorted((probe_dir / "h5").glob("*.json")) if (probe_dir / "h5").exists() else []:
        sch = read_json(h5_json)
        lines += [f"## HDF5 baseline ({h5_json.name})", "",
                  "| file | fingerprint | groups | datasets | full-width NULLTERM strings |",
                  "|---|---|---|---|---|"]
        lines += [f"| `{k}` | {v.get('fingerprint', 'error')} | {v.get('groups')} | {v.get('datasets')} | "
                  f"{len(v.get('full_width_strings', []))} |" for k, v in sch["files"].items()]
        lines.append("")
    smoke_dir = probe_dir / "smoke"
    records = [read_json(p) for p in sorted(smoke_dir.glob("*.json"))] if smoke_dir.exists() else []
    if records:
        lines += ["## Smoke results", "",
                  "| op | capability | method | status | exit | dur s | window | +/~/- files | h5 files changed |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in records:
            run0 = (r.get("runs") or [{}])[0]
            f = r.get("files") or {}
            lines.append(
                f"| {r['id']} | {r.get('capability')} | {r.get('method')} | **{r.get('status')}** | "
                f"{run0.get('exit_code')} | {run0.get('duration_s')} | {r.get('window_seen')} | "
                f"{len(f.get('added', []))}/{len(f.get('modified', []))}/{len(f.get('removed', []))} | "
                f"{len(r.get('h5_changes') or {})} |")
        caps = sorted({r.get("capability") for r in records if r.get("capability")})
        lines += ["", "## Capability matrix", "", "| capability | cli | h5edit | api | gui |",
                  "|---|---|---|---|---|"]
        for cap in caps:
            cells = []
            for m in ("cli", "h5edit", "api", "gui"):
                st = [r["status"] for r in records if r.get("capability") == cap and r.get("method", "cli") == m]
                cells.append(", ".join(st) if st else "—")
            lines.append(f"| {cap} | " + " | ".join(cells) + " |")
        for r in records:
            if r.get("determinism"):
                d = r["determinism"]
                lines.append(f"\n- determinism ({r['id']}): identical={d.get('identical')}, "
                             f"max |Δ|={d.get('max_abs_diff')}, NaN mismatches={d.get('nan_mismatch')}")
            if r.get("comparison"):
                d = r["comparison"]
                lines.append(f"- comparison ({r['id']}): max |Δ|={d.get('max_abs_diff')}, "
                             f"NaN mismatches={d.get('nan_mismatch')}")
        tier, trace = suggest_tier(records)
        lines += ["", f"## Suggested tier: **{tier}**", ""] + [f"- {t}" for t in trace]
        lines += ["", "Rules: REQUIREMENTS §3.2 and PROBE_PROCEDURE §F. The lead confirms or overrides "
                  "in ADR-0001; the project owner approves."]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- make-terrain


def make_terrain(out: Path, like: Path | None, epsg: int | None, size: int, cell: float) -> None:
    import numpy as _np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import Window

    nodata = -9999.0
    if like:
        with rasterio.open(like) as src:
            h, w = min(size, src.height), min(size, src.width)
            win = Window((src.width - w) // 2, (src.height - h) // 2, w, h)
            data = src.read(1, window=win).astype("float32")
            nd = src.nodata if src.nodata is not None else nodata
            data[~_np.isfinite(data)] = nd
            profile = {"crs": src.crs, "transform": src.window_transform(win), "nodata": nd}
    else:
        if not epsg:
            raise SystemExit("give --like TILE.tif or --epsg N")
        y, x = _np.mgrid[0:size, 0:size].astype("float32")
        z = 400 + 0.002 * y * cell + 0.05 * _np.abs(x - size / 2) * cell
        z -= 1.5 * _np.exp(-(((x - size / 2) / (size * 0.03)) ** 2))
        data = z.astype("float32")
        data[:4, :] = data[-4:, :] = nodata
        data[:, :4] = data[:, -4:] = nodata
        profile = {"crs": f"EPSG:{epsg}", "transform": from_origin(715000, 5370000, cell, cell),
                   "nodata": nodata}
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
                       dtype="float32", compress="deflate", **profile) as dst:
        dst.write(data, 1)


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HEC-RAS 2025 probe tools (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inventory")
    s.add_argument("--ras-dir", required=True, type=Path)
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--no-binary-scan", action="store_true")
    s = sub.add_parser("dotnet")
    s.add_argument("--ras-dir", required=True, type=Path)
    s.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("h5schema")
    s.add_argument("paths", nargs="+", type=Path)
    s.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("h5diff")
    s.add_argument("a", type=Path)
    s.add_argument("b", type=Path)
    s.add_argument("--out", type=Path)
    s = sub.add_parser("snapshot")
    s.add_argument("dir", type=Path)
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--max-hash-mb", type=float, default=512)
    s = sub.add_parser("snapdiff")
    s.add_argument("a", type=Path)
    s.add_argument("b", type=Path)
    s.add_argument("--out", type=Path)
    s = sub.add_parser("smoke")
    s.add_argument("--spec", required=True, type=Path)
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--only", action="append", default=[])
    s.add_argument("--non-interactive", action="store_true")
    s = sub.add_parser("report")
    s.add_argument("--dir", required=True, type=Path)
    s.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("make-terrain")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--like", type=Path)
    s.add_argument("--epsg", type=int)
    s.add_argument("--size", type=int, default=256)
    s.add_argument("--cell", type=float, default=1.0)
    a = ap.parse_args(argv)

    if a.cmd == "inventory":
        inv = inventory(a.ras_dir, scan_binaries=not a.no_binary_scan)
        write_json(a.out, inv)
        print(json.dumps(inv["summary"], indent=2, default=str))
    elif a.cmd == "dotnet":
        res = dotnet_scan(a.ras_dir)
        write_json(a.out, res)
        print(f"{len(res['assemblies'])} assemblies; seeds: {', '.join(res['seed_names'][:20])}")
    elif a.cmd == "h5schema":
        res = h5schema(a.paths)
        write_json(a.out, res)
        for k, v in res["files"].items():
            print(f"{k}: {v.get('fingerprint', v.get('error'))}")
    elif a.cmd == "h5diff":
        res = h5diff(read_json(a.a), read_json(a.b))
        if a.out:
            write_json(a.out, res)
        print(json.dumps(res, indent=2, default=str))
    elif a.cmd == "snapshot":
        write_json(a.out, snapshot(a.dir, a.max_hash_mb))
    elif a.cmd == "snapdiff":
        res = snapdiff(read_json(a.a), read_json(a.b))
        if a.out:
            write_json(a.out, res)
        print(json.dumps(res, indent=2))
    elif a.cmd == "smoke":
        recs = smoke(a.spec, a.out, a.only, interactive=not a.non_interactive)
        bad = [r["id"] for r in recs if r["status"] not in ("pass", "skipped-manual")]
        print(f"{len(recs)} ops; not passing: {', '.join(bad) or 'none'}")
    elif a.cmd == "report":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(report(a.dir), encoding="utf-8")
        print(f"wrote {a.out}")
    elif a.cmd == "make-terrain":
        make_terrain(a.out, a.like, a.epsg, a.size, a.cell)
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
