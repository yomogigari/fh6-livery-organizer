"""Read FH6 GameDB values needed for game-derived vehicle assembly truth.

This module intentionally stays read-only and narrowly scoped.  It does not
attempt to reproduce upgrade/save-state selection.  It exposes exact local
GameDB dimensions for one Car ID / CarBodyID so callers can stop using neutral
wheel/tire sizing once the user supplies a decrypted GameDB SQLite snapshot.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any


class Fh6GameDbError(RuntimeError):
    pass


def _qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _tables(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]).casefold(): str(row[0]) for row in rows if row and row[0]}


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = connection.execute(f"PRAGMA table_info({_qident(table)})").fetchall()
    return {str(row[1]).casefold(): str(row[1]) for row in rows if len(row) > 1 and row[1]}


def _required(mapping: dict[str, str], name: str, label: str) -> str:
    value = mapping.get(name.casefold())
    if not value:
        raise Fh6GameDbError(f"FH6 GameDB {label} {name!r} was not found.")
    return value


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise Fh6GameDbError(f"FH6 GameDB {label} is not numeric.") from exc
    if not math.isfinite(result):
        raise Fh6GameDbError(f"FH6 GameDB {label} is not finite.")
    return result


def read_stock_wheel_rows(database: Path | str, car_id: int) -> list[dict[str, Any]]:
    """Return exact stock tire/body rows for ``car_id`` from decrypted FH6 GameDB.

    同じプロセスの中で、同じ GameDB のファイル（場所・機器と番号・大きさ・更新日時）と同じ車の結果は覚えて
    写しを返す（2026-11-20。準備のたびに GameDB を開いて結合の問い合わせをしていた。1 回 約 12 ms）。
    例外は覚えない。中身は _read_stock_wheel_rows_uncached。
    """

    path = Path(database)
    try:
        wanted = int(car_id)
    except (TypeError, ValueError):
        return _read_stock_wheel_rows_uncached(path, car_id)
    from .process_file_memo import remembered
    return remembered("gamedb-stock-wheel-rows", [path], wanted,
                      lambda: _read_stock_wheel_rows_uncached(path, car_id), copy="marshal", limit=16)


def _read_stock_wheel_rows_uncached(path: Path, car_id: int) -> list[dict[str, Any]]:
    if not path.is_file():
        raise Fh6GameDbError(f"FH6 GameDB SQLite was not found: {path}")
    # 頭の 16 バイトだけを読む（以前は 16 MB の GameDB を丸ごと読んで頭を見ていた。2026-11-20）。
    with path.open("rb") as handle:
        header = handle.read(16)
    if header != b"SQLite format 3\x00":
        raise Fh6GameDbError("FH6 GameDB input is not a decrypted SQLite database.")

    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise Fh6GameDbError(f"Unable to open FH6 GameDB SQLite: {exc}") from exc
    try:
        connection.row_factory = sqlite3.Row
        tables = _tables(connection)
        data_car = _required(tables, "Data_Car", "table")
        tire = _required(tables, "List_UpgradeTireCompound", "table")
        body_list = _required(tables, "List_UpgradeCarBody", "table")
        body = _required(tables, "Data_CarBody", "table")
        dc = _columns(connection, data_car)
        tc = _columns(connection, tire)
        bc = _columns(connection, body_list)
        cb = _columns(connection, body)

        fields = {
            "media_name": (data_car, _required(dc, "MediaName", f"column {data_car}")),
            "car_id": (data_car, _required(dc, "Id", f"column {data_car}")),
            "car_body_id": (body_list, _required(bc, "CarBodyID", f"column {body_list}")),
            "tire_model_name": (tire, _required(tc, "TireModelName", f"column {tire}")),
            "front_tire_width_mm": (data_car, _required(dc, "FrontTireWidthMM", f"column {data_car}")),
            "front_tire_aspect": (data_car, _required(dc, "FrontTireAspect", f"column {data_car}")),
            "front_wheel_diameter_in": (data_car, _required(dc, "FrontWheelDiameterIN", f"column {data_car}")),
            "rear_tire_width_mm": (data_car, _required(dc, "RearTireWidthMM", f"column {data_car}")),
            "rear_tire_aspect": (data_car, _required(dc, "RearTireAspect", f"column {data_car}")),
            "rear_wheel_diameter_in": (data_car, _required(dc, "RearWheelDiameterIN", f"column {data_car}")),
            "model_wheelbase": (body, _required(cb, "ModelWheelbase", f"column {body}")),
            "model_front_track_outer": (body, _required(cb, "ModelFrontTrackOuter", f"column {body}")),
            "model_rear_track_outer": (body, _required(cb, "ModelRearTrackOuter", f"column {body}")),
            "model_front_stock_ride_height": (body, _required(cb, "ModelFrontStockRideHeight", f"column {body}")),
            "model_rear_stock_ride_height": (body, _required(cb, "ModelRearStockRideHeight", f"column {body}")),
            "bottom_center_wheelbase_pos_x": (body, _required(cb, "BottomCenterWheelbasePosx", f"column {body}")),
            "bottom_center_wheelbase_pos_y": (body, _required(cb, "BottomCenterWheelbasePosy", f"column {body}")),
            "bottom_center_wheelbase_pos_z": (body, _required(cb, "BottomCenterWheelbasePosZ", f"column {body}")),
        }
        stock_col = _required(tc, "IsStock", f"column {tire}")
        tire_ordinal = _required(tc, "Ordinal", f"column {tire}")
        body_ordinal = _required(bc, "Ordinal", f"column {body_list}")
        body_id = _required(cb, "Id", f"column {body}")
        car_id_col = fields["car_id"][1]

        select = ",\n                ".join(
            f"{_qident(table)}.{_qident(column)} AS {_qident(alias)}"
            for alias, (table, column) in fields.items()
        )
        sql = f"""
            SELECT {select}
            FROM {_qident(data_car)}
            INNER JOIN {_qident(tire)}
                ON {_qident(tire)}.{_qident(tire_ordinal)} = {_qident(data_car)}.{_qident(car_id_col)}
            INNER JOIN {_qident(body_list)}
                ON {_qident(body_list)}.{_qident(body_ordinal)} = {_qident(data_car)}.{_qident(car_id_col)}
            INNER JOIN {_qident(body)}
                ON {_qident(body)}.{_qident(body_id)} = {_qident(body_list)}.{_qident(fields['car_body_id'][1])}
            WHERE {_qident(data_car)}.{_qident(car_id_col)} = ?
              AND {_qident(tire)}.{_qident(stock_col)} = 1
            ORDER BY {_qident(body_list)}.{_qident(fields['car_body_id'][1])}
        """
        rows = [dict(row) for row in connection.execute(sql, (int(car_id),)).fetchall()]
    except sqlite3.Error as exc:
        raise Fh6GameDbError(f"Unable to query FH6 GameDB SQLite: {exc}") from exc
    finally:
        connection.close()
    if not rows:
        raise Fh6GameDbError(f"FH6 GameDB returned no stock wheel/tire row for Car ID {car_id}.")
    return rows


def assembly_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Build exact wheel centers and tire/rim dimensions from one GameDB row.

    The center equations follow values independently recovered from the local
    FH6 GameDB and are stored explicitly in the returned contract.  WheelStyle
    mesh morphing is intentionally *not* performed here.
    """

    front_width = _finite(row["front_tire_width_mm"], "front tire width")
    front_aspect = _finite(row["front_tire_aspect"], "front tire aspect")
    front_diameter = _finite(row["front_wheel_diameter_in"], "front wheel diameter")
    rear_width = _finite(row["rear_tire_width_mm"], "rear tire width")
    rear_aspect = _finite(row["rear_tire_aspect"], "rear tire aspect")
    rear_diameter = _finite(row["rear_wheel_diameter_in"], "rear wheel diameter")
    wheelbase = _finite(row["model_wheelbase"], "wheelbase")
    front_track = _finite(row["model_front_track_outer"], "front track")
    rear_track = _finite(row["model_rear_track_outer"], "rear track")
    front_ride = _finite(row["model_front_stock_ride_height"], "front stock ride height")
    rear_ride = _finite(row["model_rear_stock_ride_height"], "rear stock ride height")
    bx = _finite(row["bottom_center_wheelbase_pos_x"], "bottom-center x")
    by = _finite(row["bottom_center_wheelbase_pos_y"], "bottom-center y")
    bz = _finite(row["bottom_center_wheelbase_pos_z"], "bottom-center z")

    def axle(width_mm: float, aspect: float, diameter_in: float, track: float, ride: float, *, front: bool) -> dict[str, Any]:
        tire_radius = (aspect * 0.01) * (width_mm * 0.001) + diameter_in * 0.0254 / 2.0
        rim_radius = diameter_in * 0.0254 / 2.0
        z = (wheelbase / 2.0 if front else -wheelbase / 2.0) - bz
        y = tire_radius - ride + by
        return {
            "tire_radius": tire_radius,
            "tire_width": width_mm / 1000.0,
            "rim_radius": rim_radius,
            "wheel_diameter_in": diameter_in,
            "tire_aspect": aspect,
            "track_outer": track,
            "stock_ride_height": ride,
            "left_center": [-track / 2.0 + bx, y, z],
            "right_center": [track / 2.0 + bx, y, z],
        }

    front = axle(front_width, front_aspect, front_diameter, front_track, front_ride, front=True)
    rear = axle(rear_width, rear_aspect, rear_diameter, rear_track, rear_ride, front=False)
    wheel_dimensions = {
        "front_left": {key: front[key] for key in ("tire_radius", "tire_width", "rim_radius", "wheel_diameter_in", "tire_aspect")},
        "front_right": {key: front[key] for key in ("tire_radius", "tire_width", "rim_radius", "wheel_diameter_in", "tire_aspect")},
        "rear_left": {key: rear[key] for key in ("tire_radius", "tire_width", "rim_radius", "wheel_diameter_in", "tire_aspect")},
        "rear_right": {key: rear[key] for key in ("tire_radius", "tire_width", "rim_radius", "wheel_diameter_in", "tire_aspect")},
    }
    centers = {
        "front_left": front["left_center"],
        "front_right": front["right_center"],
        "rear_left": rear["left_center"],
        "rear_right": rear["right_center"],
    }
    return {
        "format": "lo4fh6_local_vehicle_assembly_v2",
        "car_body_id": int(row["car_body_id"]),
        "tire_model_name": str(row["tire_model_name"]),
        "wheel_centers": centers,
        "wheel_dimensions": wheel_dimensions,
        # Compatibility values for older readers.  New Viewer code must prefer
        # per-wheel values above because FH6 commonly has staggered sizes.
        "tire_radius": max(front["tire_radius"], rear["tire_radius"]),
        "tire_width": max(front["tire_width"], rear["tire_width"]),
        "rim_radius": max(front["rim_radius"], rear["rim_radius"]),
        "wheelbase": wheelbase,
        "bottom_center_wheelbase_position": [bx, by, bz],
        "front_track_outer": front_track,
        "rear_track_outer": rear_track,
        "source": "local-fh6-gamedb",
        "style": "exact-game-data-dimensions-neutral-tire-rendering",
        "wheelstyle_morph_applied": False,
    }


def assembly_variants(database: Path | str, car_id: int) -> dict[str, dict[str, Any]]:
    """Return ``CarBodyID`` keyed exact assembly records for a car."""

    return {str(int(row["car_body_id"])): assembly_from_row(row) for row in read_stock_wheel_rows(database, car_id)}
