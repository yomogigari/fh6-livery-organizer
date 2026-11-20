from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from stat import S_ISDIR
from typing import Any


CAR_CLIP_RE = re.compile(r"(?:^|/)carclips_(\d+)\.clipd$", re.IGNORECASE)
PROJECTION_PREFIX = "LiveryMasks/"


class VehicleAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class VehicleAsset:
    car_id: int
    model_code: str
    archive_path: str
    archive_name: str
    archive_size: int
    archive_mtime_ns: int
    clip_entry: str

    def public_metadata(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("archive_path", None)
        return data


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """ファイルの SHA-256。

    同じプロセスで同じファイル（場所・大きさ・更新日時が同じ）は覚えて使い回す（ペイントを開くたびに、車の ZIP
    （約 20 MB）の SHA を準備の前半と後半で計算し直していた。1 回 約 0.02〜0.04 秒。2026-11-20）。
    """
    from .process_file_memo import remembered
    target = Path(path)
    return remembered("sha256-file", [target], None, lambda: _sha256_file_uncached(target, chunk_size),
                      copy="none", limit=32)


def _sha256_file_uncached(path: Path, chunk_size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _car_clip_in_archive(archive: Path) -> tuple[int, str] | None:
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            match = CAR_CLIP_RE.search(name.replace("\\", "/"))
            if match:
                return int(match.group(1)), name
    return None


# 同じプロセスの中で、ゲームのフォルダーごとに見つけた車のフォルダーを覚える（2026-11-20）。
# 差し替えの準備で数回ずつ、約 700 個の ZIP がある場所を一覧にし、ZIP を 1 つ開いて、場所を解決していた。
_CARS_DIR_MEMO: dict[str, tuple[tuple, int, tuple, Path, tuple, Path]] = {}
_CARS_DIR_LOCK = threading.Lock()


def _directory_state(path: Path) -> tuple | None:
    """フォルダーの識別（機器・番号・更新日時。中の項目が増減すると更新日時が変わる）。無ければ None。"""
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    if not S_ISDIR(stat.st_mode):
        return ("not-directory",)
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns)


def _archive_state(path: Path) -> tuple | None:
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _remembered_cars_dir(key: str, candidates: list[Path]) -> Path | None:
    """覚えた車のフォルダー。前に確かめた候補のフォルダー（見つけた物より前の物）・見つけたフォルダー・車の ZIP だと
    分かった ZIP の識別が同じときだけ返す（変わっていれば None で、もう一度探す）。"""
    with _CARS_DIR_LOCK:
        remembered = _CARS_DIR_MEMO.get(key)
    if remembered is None:
        return None
    earlier, index, found_state, archive, archive_state, result = remembered
    if any(_directory_state(candidate) != state for candidate, state in zip(candidates[:index], earlier)):
        return None
    state = _directory_state(candidates[index])
    if state is None or state[:2] != found_state[:2] or _archive_state(archive) != archive_state:
        return None
    return result


def resolve_fh6_cars_dir(game_folder: Path | str) -> Path:
    root = Path(game_folder).expanduser()
    # A ZIP beside the game executable is not evidence of a car directory.
    candidates = [
        root / "media" / "cars",
        root / "Content" / "media" / "cars",
        root,
    ]
    memo_key = str(root)
    remembered = _remembered_cars_dir(memo_key, candidates)
    if remembered is not None:
        return remembered
    earlier_states = [_directory_state(candidate) for candidate in candidates]
    read_errors: list[str] = []
    for index, candidate in enumerate(candidates):
        try:
            if not candidate.is_dir():
                continue
            for archive in candidate.glob("*.zip"):
                try:
                    if _car_clip_in_archive(archive) is not None:
                        result = candidate.resolve()
                        found_state = _directory_state(candidate)
                        archive_state = _archive_state(archive)
                        if found_state is not None and archive_state is not None and found_state[0] != "not-directory":
                            with _CARS_DIR_LOCK:
                                _CARS_DIR_MEMO[memo_key] = (tuple(earlier_states[:index]), index, found_state,
                                                            archive, archive_state, result)
                        return result
                except (OSError, zipfile.BadZipFile) as exc:
                    if len(read_errors) < 3:
                        read_errors.append(f"{archive}: {exc}")
        except OSError as exc:
            if len(read_errors) < 3:
                read_errors.append(f"{candidate}: {exc}")
    detail = " Archive read errors: " + "; ".join(read_errors) if read_errors else ""
    raise VehicleAssetError(
        f"No readable FH6 car archives were found below {root}. "
        f"Choose the game folder or its Content folder containing media/Cars.{detail}"
    )


def normalize_fh6_game_folder(game_folder: Path | str) -> Path:
    """Return a stable install root after proving that it contains FH6 car data."""

    cars_dir = resolve_fh6_cars_dir(game_folder)
    if cars_dir.name.casefold() == "cars" and cars_dir.parent.name.casefold() == "media":
        return cars_dir.parent.parent.resolve()
    return cars_dir.resolve()


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve()).casefold() if path.exists() else str(path.absolute()).casefold()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _windows_drive_roots() -> list[Path]:
    candidates: list[Path] = []
    system_drive = str(os.environ.get("SystemDrive") or "C:").rstrip("\\/")
    if system_drive:
        candidates.append(Path(system_drive + "/"))
    try:
        import psutil

        candidates.extend(Path(item.mountpoint) for item in psutil.disk_partitions(all=False))
    except Exception:
        pass
    return [path for path in _unique_paths(candidates) if path.is_dir()]


def _running_fh6_executables() -> list[Path]:
    executables: list[Path] = []
    wanted = {"forzahorizon6.exe", "forzahorizon6-win64-shipping.exe"}
    try:
        import psutil

        for process in psutil.process_iter(["name", "exe"]):
            try:
                if str(process.info.get("name") or "").casefold() not in wanted:
                    continue
                executable = str(process.info.get("exe") or "").strip()
                if executable:
                    executables.append(Path(executable))
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
    except Exception:
        pass
    return _unique_paths(executables)


def _steam_install_roots(drive_roots: Iterable[Path]) -> list[Path]:
    candidates: list[Path] = []
    try:
        import winreg

        registry_locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam", "InstallPath"),
        )
        for hive, key_name, value_name in registry_locations:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, value_name)
                if value:
                    candidates.append(Path(str(value)))
            except OSError:
                continue
    except Exception:
        pass

    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value) / "Steam")
    for drive in drive_roots:
        candidates.extend((drive / "Steam", drive / "SteamLibrary", drive / "Games" / "Steam"))

    steam_roots = _unique_paths(candidates)
    libraries = list(steam_roots)
    path_pattern = re.compile(r'"path"\s+"([^"]+)"', re.IGNORECASE)
    for steam_root in steam_roots:
        manifest = steam_root / "steamapps" / "libraryfolders.vdf"
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in path_pattern.finditer(text):
            libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return [path for path in _unique_paths(libraries) if path.is_dir()]


def discover_fh6_game_folder(
    preferred: Path | str | None = None,
    *,
    drive_roots: Iterable[Path] | None = None,
    process_executables: Iterable[Path] | None = None,
    steam_roots: Iterable[Path] | None = None,
) -> Path | None:
    """Find an FH6 install without recursively crawling arbitrary user folders."""

    drives = list(drive_roots) if drive_roots is not None else _windows_drive_roots()
    executables = (
        list(process_executables)
        if process_executables is not None
        else _running_fh6_executables()
    )
    libraries = list(steam_roots) if steam_roots is not None else _steam_install_roots(drives)
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(preferred).expanduser())

    for executable in executables:
        current = Path(executable).parent
        candidates.extend((current, current / "Content"))
        candidates.extend(parent for parent in list(current.parents)[:3])

    folder_names = ("Forza Horizon 6", "ForzaHorizon6")
    for drive in drives:
        xbox_root = drive / "XboxGames"
        for name in folder_names:
            candidates.extend((xbox_root / name / "Content", xbox_root / name))
        try:
            xbox_children = list(xbox_root.iterdir()) if xbox_root.is_dir() else []
        except OSError:
            xbox_children = []
        for child in xbox_children:
            normalized = re.sub(r"[^a-z0-9]", "", child.name.casefold())
            if child.is_dir() and "forzahorizon6" in normalized:
                candidates.extend((child / "Content", child))

        windows_apps = drive / "Program Files" / "WindowsApps"
        for pattern in ("Microsoft.ForteBaseGame_*", "Microsoft.ForzaHorizon6_*"):
            try:
                candidates.extend(windows_apps.glob(pattern))
            except OSError:
                pass

    for library in libraries:
        common = library / "steamapps" / "common"
        for name in folder_names:
            candidates.extend((common / name, common / name / "Content"))

    for candidate in _unique_paths(candidates):
        try:
            return normalize_fh6_game_folder(candidate)
        except (OSError, VehicleAssetError):
            continue
    return None


def _index_signature(cars_dir: Path) -> dict[str, Any]:
    """車の ZIP（cars_dir の直下の *.zip。Path.glob("*.zip") と同じもの）の数・最新の更新日時・名前の長さの合計。

    os.scandir の項目の情報を使う（Windows ではフォルダーの一覧から更新日時が得られ、ファイルごとに開き直さない。
    車の ZIP 約 700 個で glob＋stat の約 0.04 秒を、ペイントを開くたびに使っていた。2026-11-20）。
    名前の比べ方は glob と同じく OS の大文字・小文字の扱いに従う。
    """
    count = 0
    newest = 0
    name_bytes = 0
    with os.scandir(cars_dir) as entries:
        for entry in entries:
            if not os.path.normcase(entry.name).endswith(".zip"):
                continue
            count += 1
            newest = max(newest, entry.stat().st_mtime_ns)
            name_bytes += len(entry.name)
    return {
        "cars_dir": str(cars_dir.resolve()),
        "archive_count": count,
        "newest_mtime_ns": newest,
        "total_name_bytes": name_bytes,
    }


def build_vehicle_asset_index(cars_dir: Path | str) -> dict[int, VehicleAsset]:
    cars = resolve_fh6_cars_dir(cars_dir)
    index: dict[int, VehicleAsset] = {}
    for archive in sorted(cars.glob("*.zip"), key=lambda p: p.name.casefold()):
        try:
            clip = _car_clip_in_archive(archive)
            if clip is None:
                continue
            car_id, name = clip
            stat = archive.stat()
            index.setdefault(
                car_id,
                VehicleAsset(
                    car_id=car_id,
                    model_code=archive.stem,
                    archive_path=str(archive.resolve()),
                    archive_name=archive.name,
                    archive_size=stat.st_size,
                    archive_mtime_ns=stat.st_mtime_ns,
                    clip_entry=name,
                ),
            )
        except (OSError, zipfile.BadZipFile):
            continue
    if not index:
        raise VehicleAssetError(f"No readable FH6 car identifiers were found in {cars}. Relink the FH6 folder.")
    return index


def load_or_build_vehicle_asset_index(
    game_folder: Path | str,
    cache_path: Path | str | None = None,
) -> dict[int, VehicleAsset]:
    cars_dir = resolve_fh6_cars_dir(game_folder)
    signature = _index_signature(cars_dir)
    cache = Path(cache_path) if cache_path else None
    if cache and cache.is_file():
        def load() -> dict[int, VehicleAsset] | None:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if (
                isinstance(payload, dict)
                and payload.get("format") == "lo4fh6_vehicle_asset_index_v1"
                and payload.get("signature") == signature
                and isinstance(payload.get("vehicles"), dict)
                and payload["vehicles"]
            ):
                return {
                    int(key): VehicleAsset(**value)
                    for key, value in payload.get("vehicles", {}).items()
                }
            return None

        try:
            # 同じプロセスの中で、同じ目録のファイル（場所・機器と番号・大きさ・更新日時）と同じ署名の読み取りは
            # 覚える（2026-11-20。準備の前半・後半で、約 700 台の JSON を読んで VehicleAsset を作り直していた）。
            # 署名はこれまでどおり毎回求める。覚えた辞書は渡さず、浅い写しを返す（VehicleAsset は変えられない）。
            from .process_file_memo import remembered
            loaded = remembered("vehicle-asset-index", [cache], tuple(sorted(signature.items())), load, copy="none",
                                limit=4, keep=lambda value: value is not None)
            if loaded is not None:
                return dict(loaded)
        except (OSError, ValueError, TypeError):
            pass

    result = build_vehicle_asset_index(cars_dir)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(cache.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "format": "lo4fh6_vehicle_asset_index_v1",
                    "signature": signature,
                    "vehicles": {str(key): asdict(value) for key, value in sorted(result.items())},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(cache)
    return result


def inspect_vehicle_archive(asset: VehicleAsset) -> dict[str, Any]:
    archive = Path(asset.archive_path)
    carbin_entries: list[str] = []
    model_entries: list[str] = []
    projection_entries: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = info.filename.replace("\\", "/")
            lower = name.casefold()
            if lower.endswith(".carbin"):
                carbin_entries.append(name)
            elif lower.endswith(".modelbin"):
                model_entries.append(name)
            if lower.startswith(PROJECTION_PREFIX.casefold()) and not name.endswith("/"):
                projection_entries.append(name)
    proxy = next((name for name in model_entries if name.casefold().endswith("scene/proxylod.modelbin")), "")
    return {
        **asset.public_metadata(),
        "archive_sha256": sha256_file(archive),
        "carbin_entries": carbin_entries,
        "model_entry_count": len(model_entries),
        "proxy_model_entry": proxy,
        "projection_entries": projection_entries,
    }


def read_projection_assets(asset: VehicleAsset) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with zipfile.ZipFile(asset.archive_path) as bundle:
        for info in bundle.infolist():
            name = info.filename.replace("\\", "/")
            if name.casefold().startswith(PROJECTION_PREFIX.casefold()) and not name.endswith("/"):
                result[name] = bundle.read(info)
    return result


def read_projection_metadata(asset: VehicleAsset) -> dict[str, Any]:
    """Derive a portable projection contract without copying game assets."""
    inventory: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    with zipfile.ZipFile(asset.archive_path) as bundle:
        mask_xml = b""
        for info in bundle.infolist():
            name = info.filename.replace("\\", "/")
            if not name.casefold().startswith(PROJECTION_PREFIX.casefold()) or name.endswith("/"):
                continue
            data = bundle.read(info)
            inventory.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            if name.casefold() == "liverymasks/masks.xml":
                mask_xml = data
        if mask_xml:
            root = ET.fromstring(mask_xml)
            for element in root:
                record: dict[str, Any] = {"section": element.tag, "valid": element.attrib.get("valid", "false").lower() == "true"}
                for key in ("xorigin", "yorigin", "top", "bottom", "left", "right", "xScale", "yScale", "rotation"):
                    if key in element.attrib:
                        record[key] = float(element.attrib[key])
                for key in ("xAxis", "yAxis"):
                    if key in element.attrib:
                        record[key] = element.attrib[key]
                sections.append(record)
    return {
        "format": "lo4_vehicle_projection_map_v1",
        "model_code": asset.model_code,
        "source_inventory": sorted(inventory, key=lambda item: item["path"].casefold()),
        "sections": sections,
    }


def read_vehicle_assembly_metadata(asset: VehicleAsset) -> dict[str, Any]:
    """Read local-only inspection placement data from the car archive."""

    try:
        with zipfile.ZipFile(asset.archive_path) as bundle:
            available = {name.casefold(): name for name in bundle.namelist()}
            locator_name = available.get("locators.xml")
            if not locator_name:
                return {}
            locator_xml = bundle.read(locator_name).replace(
                b'BoneName="<root>"',
                b'BoneName="&lt;root&gt;"',
            )
            root = ET.fromstring(locator_xml)
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return {}

    wanted_wheels = {
        "carlocator_wheellf": "front_left",
        "carlocator_wheelrf": "front_right",
        "carlocator_wheellr": "rear_left",
        "carlocator_wheelrr": "rear_right",
    }
    wanted_locators = {
        **wanted_wheels,
        "carlocator_bumperf": "bumper_front",
        "carlocator_bumperr": "bumper_rear",
    }
    centers: dict[str, list[float]] = {}
    locators: dict[str, list[float]] = {}
    for locator in root.findall(".//Locator"):
        name_element = locator.find("Name")
        transform = locator.find("SceneTransform")
        identity = str(name_element.attrib.get("value") if name_element is not None else "").casefold()
        label = wanted_locators.get(identity)
        if not label or transform is None:
            continue
        try:
            position = [
                float(transform.attrib[f"value._{component}"])
                for component in (41, 42, 43)
            ]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in position):
            locators[label] = position
            if identity in wanted_wheels:
                centers[label] = position
    if len(centers) != len(wanted_wheels):
        return {}

    front_z = (centers["front_left"][2] + centers["front_right"][2]) * 0.5
    rear_z = (centers["rear_left"][2] + centers["rear_right"][2]) * 0.5
    wheelbase = abs(front_z - rear_z)
    if wheelbase < 1.0 or wheelbase > 6.0:
        return {}

    # These dimensions are intentionally neutral inspection geometry. The car's
    # local locators provide exact placement; wheelbase-relative dimensions keep
    # the stand-ins proportionate without redistributing game tuning data.
    tire_radius = min(0.48, max(0.24, wheelbase * 0.12))
    tire_width = min(0.42, max(0.18, wheelbase * 0.095))
    return {
        "format": "lo4fh6_local_vehicle_assembly_v1",
        "wheel_centers": centers,
        "locators": locators,
        "wheelbase": wheelbase,
        "tire_radius": tire_radius,
        "tire_width": tire_width,
        "rim_radius": tire_radius * 0.70,
        "source": "local-car-locators",
        "style": "neutral-inspection-stand-in",
    }


# ---- ボディキットの選び方・一覧・重ねの計画は、同じプロセスの中で覚える（2026-11-20）----
# どれも車の ZIP の Manifest.xml と引数だけで決まる。準備 1 件で、ボディキットの種類ごとに Manifest.xml を
# 2 回ずつ読んで解析していた（はじめてのペイントの準備の約 10%）。車の ZIP の識別（場所・機器と番号・大きさ・
# 更新日時）と引数を鍵に、最後まで終わった結果だけを覚えて写しを返す（例外は覚えない）。
_BODY_KIT_MEMORY_LIMIT = 64


def _body_kit_memory_key(asset: VehicleAsset, *values: int) -> tuple:
    return (str(asset.archive_path), str(asset.archive_name), str(asset.model_code), *values)


def resolve_body_kit_part_selection(asset: VehicleAsset, body_kit_part_id: int) -> dict[str, int]:
    """_resolve_body_kit_part_selection_uncached と同じ結果（同じプロセスの中で覚えた写し）。"""
    from .process_file_memo import remembered
    wanted = int(body_kit_part_id)
    return remembered("body-kit-part-selection", [asset.archive_path], _body_kit_memory_key(asset, wanted),
                      lambda: _resolve_body_kit_part_selection_uncached(asset, wanted), copy="marshal",
                      limit=_BODY_KIT_MEMORY_LIMIT)


def list_body_kit_part_ids(asset: VehicleAsset) -> list[int]:
    """_list_body_kit_part_ids_uncached と同じ結果（同じプロセスの中で覚えた写し）。"""
    from .process_file_memo import remembered
    return remembered("body-kit-part-ids", [asset.archive_path], _body_kit_memory_key(asset),
                      lambda: _list_body_kit_part_ids_uncached(asset), copy="marshal",
                      limit=_BODY_KIT_MEMORY_LIMIT)


def resolve_body_kit_overlay_plan(asset: VehicleAsset, body_kit_part_id: int) -> dict[str, Any]:
    """_resolve_body_kit_overlay_plan_uncached と同じ結果（同じプロセスの中で覚えた写し）。"""
    from .process_file_memo import remembered
    wanted = int(body_kit_part_id)
    return remembered("body-kit-overlay-plan", [asset.archive_path], _body_kit_memory_key(asset, wanted),
                      lambda: _resolve_body_kit_overlay_plan_uncached(asset, wanted), copy="marshal",
                      limit=_BODY_KIT_MEMORY_LIMIT)


def _resolve_body_kit_part_selection_uncached(asset: VehicleAsset, body_kit_part_id: int) -> dict[str, int]:
    """Map one explicit CarBody PartId onto matching exterior upgrade families.

    FH6 vehicle manifests commonly reuse the same PartId for the CarBody and
    companion exterior families that belong to one body-kit profile.  Only
    families whose matching variant references exterior geometry are promoted;
    unrelated interior/performance families keep their deterministic baseline.
    The result is a manual research selection, not save-state evidence.
    """

    wanted = int(body_kit_part_id)
    with zipfile.ZipFile(asset.archive_path) as bundle:
        try:
            manifest = ET.fromstring(bundle.read("Manifest.xml"))
        except KeyError as exc:
            raise VehicleAssetError(f"{asset.archive_name} has no Manifest.xml.") from exc

    families: dict[str, list[tuple[int, ET.Element]]] = {}
    canonical_names: dict[str, str] = {}
    for part in manifest.findall(".//UpgradeablePart"):
        canonical = str(part.attrib.get("PartEnum") or "").strip()
        family = canonical.casefold()
        if not family:
            continue
        try:
            part_id = int(part.attrib.get("PartId", ""))
        except ValueError:
            continue
        canonical_names.setdefault(family, canonical)
        families.setdefault(family, []).append((part_id, part))

    car_body = families.get("carbody") or []
    if car_body and not any(part_id == wanted for part_id, _ in car_body):
        available = ", ".join(str(part_id) for part_id, _ in sorted(car_body))
        raise VehicleAssetError(
            f"{asset.archive_name} has no CarBody PartId {wanted}; available: {available}."
        )

    # 原本にCarBody Partがない車種では、同一PartIdを持つ実外装モデルを
    # 源泉とするFrontBumper/RearWing等の選択を許可する。車種別分岐なし。
    # CarBodyを持つ既存車種の標準選択は変えない。
    selection: dict[str, int] = (
        {canonical_names.get("carbody", "CarBody"): wanted} if car_body else {}
    )
    for family, variants in families.items():
        if family == "carbody":
            continue
        match = next((part for part_id, part in variants if part_id == wanted), None)
        if match is None:
            continue
        family_has_exterior_model = any(
            "/scene/exterior/" in str(model.attrib.get("path") or "").replace("\\", "/").casefold()
            for _part_id, variant in variants
            for model in variant.findall(".//Model")
        )
        if family_has_exterior_model:
            # 明示的に空の選択も基準外装を抑止できる元Manifest指定として保持。
            # PartIdが一致しない任意パーツは変更しない。
            selection[canonical_names.get(family, family)] = wanted
    if not selection:
        raise VehicleAssetError(
            f"{asset.archive_name} has no CarBody or source-backed exterior PartId {wanted}."
        )
    return selection



def _list_body_kit_part_ids_uncached(asset: VehicleAsset) -> list[int]:
    """Return sorted Manifest CarBody PartIds available for manual Viewer selection.

    This enumerates available local vehicle variants only. It is not garage/save
    state evidence and does not claim which body kit the painted vehicle used.
    """

    with zipfile.ZipFile(asset.archive_path) as bundle:
        try:
            manifest = ET.fromstring(bundle.read("Manifest.xml"))
        except KeyError as exc:
            raise VehicleAssetError(f"{asset.archive_name} has no Manifest.xml.") from exc
    values: set[int] = set()
    parts = manifest.findall(".//UpgradeablePart")
    for part in parts:
        if str(part.attrib.get("PartEnum") or "").strip().casefold() != "carbody":
            continue
        try:
            values.add(int(part.attrib.get("PartId", "")))
        except ValueError:
            continue
    if values:
        return sorted(values)
    # FH6原本にCarBodyが無く、外装アップグレードだけある車種の
    # Viewer選択肢。ModelBinを持つ複数option群に限り、車種IDで補正しない。
    exterior_families: dict[str, list[ET.Element]] = {}
    for part in parts:
        family = str(part.attrib.get("PartEnum") or "").strip().casefold()
        if family and family != "carbody":
            exterior_families.setdefault(family, []).append(part)
    for variants in exterior_families.values():
        if len(variants) < 2 or not any(
            "/scene/exterior/" in str(model.attrib.get("path") or "").replace("\\", "/").casefold()
            for part in variants for model in part.findall(".//Model")
        ):
            continue
        for part in variants:
            try:
                values.add(int(part.attrib.get("PartId", "")))
            except ValueError:
                continue
    return sorted(values)


def _resolve_body_kit_overlay_plan_uncached(asset: VehicleAsset, body_kit_part_id: int) -> dict[str, Any]:
    """Resolve an explicit Manifest body-kit profile as baseline removals + loose additions.

    The bundled chassis converter currently assembles only the carbin scene's
    deterministic stock/default upgrade choices.  For research variants we keep
    that exact scene as the transform-safe baseline, remove baseline-only model
    entries in Viewer, and convert only selected-only Manifest entries through
    the converter's loose-entry path.  The result is still a manual selection;
    no garage/save-state claim is made here.
    """

    selection = resolve_body_kit_part_selection(asset, int(body_kit_part_id))
    normalized_selection = {str(key).casefold(): int(value) for key, value in selection.items()}
    with zipfile.ZipFile(asset.archive_path) as bundle:
        available = {
            info.filename.replace("\\", "/").casefold(): info.filename.replace("\\", "/")
            for info in bundle.infolist()
            if info.filename.casefold().endswith(".modelbin")
        }
        try:
            manifest = ET.fromstring(bundle.read("Manifest.xml"))
        except KeyError as exc:
            raise VehicleAssetError(f"{asset.archive_name} has no Manifest.xml.") from exc

    prefix = f"game:/media/cars/{asset.model_code}/".casefold()

    def model_entries(part: ET.Element) -> set[str]:
        result: set[str] = set()
        for model in part.findall(".//Model"):
            source = str(model.attrib.get("path") or "").replace("\\", "/")
            folded = source.casefold()
            start = folded.find(prefix)
            if start < 0:
                continue
            relative = source[start + len(prefix) :].lstrip("/")
            actual = available.get(relative.casefold())
            if not actual or "__slod" in actual.casefold():
                continue
            identity = actual.casefold()
            if (
                "/exterior/" in identity
                or "/scene/undercarriage/" in identity
                or "/interior/interiorlod/" in identity
            ):
                result.add(actual)
        return result

    families: dict[str, list[tuple[int, ET.Element]]] = {}
    canonical: dict[str, str] = {}
    for part in manifest.findall(".//UpgradeablePart"):
        name = str(part.attrib.get("PartEnum") or "").strip()
        family = name.casefold()
        if not family:
            continue
        try:
            part_id = int(part.attrib.get("PartId", ""))
        except ValueError:
            continue
        canonical.setdefault(family, name)
        families.setdefault(family, []).append((part_id, part))

    family_plans: list[dict[str, Any]] = []
    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    for family, selected_id in normalized_selection.items():
        variants = sorted(families.get(family) or [], key=lambda item: item[0])
        if not variants:
            continue
        baseline_id, baseline_part = variants[0]
        selected = next((part for part_id, part in variants if part_id == selected_id), None)
        if selected is None:
            raise VehicleAssetError(
                f"{asset.archive_name} has no {canonical.get(family, family)} PartId {selected_id}."
            )
        baseline_entries = model_entries(baseline_part)
        selected_entries = model_entries(selected)
        family_removed = sorted(
            (entry for entry in baseline_entries if entry.casefold() not in {value.casefold() for value in selected_entries}),
            key=str.casefold,
        )
        family_added = sorted(
            (entry for entry in selected_entries if entry.casefold() not in {value.casefold() for value in baseline_entries}),
            key=str.casefold,
        )
        for entry in family_removed:
            removed.setdefault(entry.casefold(), entry)
        for entry in family_added:
            added.setdefault(entry.casefold(), entry)
        family_plans.append(
            {
                "part_enum": canonical.get(family, family),
                "baseline_part_id": baseline_id,
                "selected_part_id": selected_id,
                "removed_entries": family_removed,
                "added_entries": family_added,
            }
        )

    return {
        "format": "lo4fh6_body_kit_overlay_plan_v1",
        "body_kit_part_id": int(body_kit_part_id),
        "part_selection": selection,
        "families": family_plans,
        "removed_entries": sorted(removed.values(), key=str.casefold),
        "added_entries": sorted(added.values(), key=str.casefold),
        "player_save_state_resolved": False,
        "baseline_scene_policy": "exact-carbin-stock-scene",
        "selected_addition_policy": "manifest-delta-loose-models-experimental",
    }

def inspection_model_entries(
    asset: VehicleAsset,
    *,
    part_selection: dict[str, int] | None = None,
) -> list[str]:
    """Resolve locally owned model parts needed by the inspector.

    ``part_selection`` is a research-only explicit manifest selection keyed by
    ``PartEnum``.  Unspecified families retain the deterministic lowest-PartId
    baseline.  This never claims to represent the player's garage/save state.
    """

    with zipfile.ZipFile(asset.archive_path) as bundle:
        available = {
            info.filename.replace("\\", "/").casefold(): info.filename.replace("\\", "/")
            for info in bundle.infolist()
            if info.filename.casefold().endswith(".modelbin")
        }
        try:
            manifest = ET.fromstring(bundle.read("Manifest.xml"))
        except KeyError as exc:
            raise VehicleAssetError(f"{asset.archive_name} has no Manifest.xml.") from exc

    prefix = f"game:/media/cars/{asset.model_code}/".casefold()
    entries: dict[str, str] = {}

    def add_model(model: ET.Element) -> None:
        source = str(model.attrib.get("path") or "").replace("\\", "/")
        folded = source.casefold()
        start = folded.find(prefix)
        if start < 0:
            return
        relative = source[start + len(prefix) :].lstrip("/")
        actual = available.get(relative.casefold())
        if not actual or "__slod" in actual.casefold():
            return
        identity = actual.casefold()
        include = (
            "/exterior/" in identity
            or "/scene/undercarriage/" in identity
            or "/interior/interiorlod/" in identity
        )
        if include:
            entries.setdefault(identity, actual)

    for model in manifest.findall(".//NonUpgradeablePart/Model"):
        add_model(model)

    # Upgrade parts default to the first/lowest PartId option in each family.
    # r206 can override individual families explicitly for body-kit research.
    normalized_selection = {
        str(key).casefold(): int(value)
        for key, value in (part_selection or {}).items()
    }
    upgrade_families: dict[str, list[tuple[int, ET.Element]]] = {}
    for part in manifest.findall(".//UpgradeablePart"):
        family = str(part.attrib.get("PartEnum") or "").strip().casefold()
        if not family:
            continue
        try:
            part_id = int(part.attrib.get("PartId", ""))
        except ValueError:
            continue
        upgrade_families.setdefault(family, []).append((part_id, part))

    for family, variants in upgrade_families.items():
        variants.sort(key=lambda item: item[0])
        wanted = normalized_selection.get(family)
        if wanted is None:
            chosen_id, chosen = variants[0]
        else:
            match = next((item for item in variants if item[0] == wanted), None)
            if match is None:
                available_ids = ", ".join(str(item[0]) for item in variants)
                raise VehicleAssetError(
                    f"{asset.archive_name} has no {family} PartId {wanted}; available: {available_ids}."
                )
            chosen_id, chosen = match
        for model in chosen.findall(".//Model"):
            add_model(model)
    if not entries:
        raise VehicleAssetError(
            f"{asset.archive_name} does not expose stock inspection model parts in Manifest.xml."
        )

    def priority(name: str) -> tuple[int, str]:
        folded = name.casefold()
        if folded.endswith("/platform/body_a.modelbin"):
            return 0, folded
        if "/windows/" in folded:
            return 1, folded
        if any(token in folded for token in ("/hood/", "/doors/", "/trunk/", "/fenders/", "/bumper")):
            return 2, folded
        return 3, folded

    return sorted(entries.values(), key=priority)


def inspection_carbin_entry(asset: VehicleAsset) -> str:
    """Resolve the car scene that assembles the local chassis model instances."""

    with zipfile.ZipFile(asset.archive_path) as bundle:
        entries = [
            info.filename.replace("\\", "/")
            for info in bundle.infolist()
            if info.filename.casefold().endswith(".carbin") and not info.is_dir()
        ]
    if not entries:
        raise VehicleAssetError(f"{asset.archive_name} has no car scene.")
    expected = f"{asset.model_code}.carbin".casefold()
    exact = [entry for entry in entries if Path(entry).name.casefold() == expected]
    if len(exact) == 1:
        return exact[0]
    if len(entries) == 1:
        return entries[0]
    raise VehicleAssetError(f"{asset.archive_name} has an ambiguous car scene inventory.")
