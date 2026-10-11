"""Typed interface to deterministic compiled routing and independent connection scan."""

from __future__ import annotations

import ctypes
import json
import struct
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .common import ROOT


def compile_engine(build: Path | None = None) -> Path:
    build = build or ROOT / "build"
    build.mkdir(parents=True, exist_ok=True)
    lib = build / "libnetwork.dylib"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-O3",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            "-fPIC",
            str(ROOT / "src/network_lab/native.cpp"),
            "-o",
            str(lib),
        ],
        check=True,
    )
    return lib


def write_model(
    path: Path,
    nstops: int,
    npoints: int,
    nroutes: int,
    walks: list[np.ndarray],
    board_walks: list[np.ndarray],
    trips: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(struct.pack("<5i", 20261013, nstops, npoints, nroutes, len(trips)))
        for edges in walks + board_walks:
            array = np.asarray(edges, dtype="<i4").reshape(-1, 2)
            f.write(struct.pack("<i", len(array)))
            f.write(array.tobytes())
        for t in trips:
            f.write(struct.pack("<2i", t["route"], len(t["rows"])))
            f.write(np.asarray(t["rows"], dtype="<i4").tobytes())


def delete_service(
    base: Path, target: Path, removed_trips: set[int], removed_routes: set[int] | None = None
) -> dict[str, Any]:
    """Copy the unchanged walking prefix and delete actual trip occurrences."""
    removed_routes = removed_routes or set()
    with base.open("rb") as f:
        header = struct.unpack("<5i", f.read(20))
        _, ns, np_, _, nt = header
        if any(t < 0 or t >= nt for t in removed_trips):
            raise ValueError("Deleted trip occurrence index outside the frozen model")
        for _ in range(ns + np_):
            length = struct.unpack("<i", f.read(4))[0]
            f.seek(length * 8, 1)
        offset = f.tell()
        trips = []
        for t in range(nt):
            route, count = struct.unpack("<2i", f.read(8))
            rows = f.read(count * 20)
            if t not in removed_trips and route not in removed_routes:
                trips.append((t, route, count, rows))
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = base.read_bytes()[:offset]
    with target.open("wb") as f:
        f.write(prefix[:16] + struct.pack("<i", len(trips)) + prefix[20:])
        for _, route, count, rows in trips:
            f.write(struct.pack("<2i", route, count))
            f.write(rows)
    return {
        "original_trip_occurrences": nt,
        "remaining_trip_occurrences": len(trips),
        "new_to_base_trip_indices": [t for t, _, _, _ in trips],
    }


def certificate_survives(witness: dict[str, Any], removed_trips: set[int]) -> bool:
    """All stored selected optima in an origin/departure batch avoid these trips."""
    return all(leg[1] not in removed_trips for leg in witness["legs"])


class Engine:
    def __init__(self, model: Path, npoints: int, nroutes: int, library: Path | None = None):
        self.library = ctypes.CDLL(str(library or compile_engine()))
        self.library.load_model.argtypes = [ctypes.c_char_p]
        self.library.load_model.restype = ctypes.c_void_p
        self.library.free_model.argtypes = [ctypes.c_void_p]
        ip = ctypes.POINTER(ctypes.c_int32)
        up = ctypes.POINTER(ctypes.c_uint8)
        self.library.route_query.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ip, up]
        self.library.route_query.restype = ctypes.c_int
        self.library.oracle_query.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ip]
        self.library.oracle_query.restype = ctypes.c_int
        self.library.geometry_query.argtypes = [ctypes.c_void_p, ctypes.c_int, ip, up]
        self.library.geometry_query.restype = ctypes.c_int
        self.library.query_witness.argtypes = [ctypes.c_void_p]
        self.library.query_witness.restype = ctypes.c_char_p
        self.handle = self.library.load_model(str(model).encode())
        if not self.handle:
            raise ValueError("Compiled engine rejected input model")
        self.npoints, self.nroutes = npoints, nroutes

    def close(self) -> None:
        if self.handle:
            self.library.free_model(self.handle)
            self.handle = None

    def query(
        self,
        origin: int,
        depart: int,
        removed_route: int = -1,
        removed_trip: int = -1,
        oracle: bool = False,
    ) -> tuple[np.ndarray, np.ndarray, int]:
        arrivals = np.empty(self.npoints, dtype=np.int32)
        support = np.zeros(self.nroutes, dtype=np.uint8)
        ip = arrivals.ctypes.data_as(ctypes.POINTER(ctypes.c_int32))
        if oracle:
            rounds = self.library.oracle_query(
                self.handle, origin, depart, removed_route, removed_trip, ip
            )
        else:
            rounds = self.library.route_query(
                self.handle,
                origin,
                depart,
                removed_route,
                removed_trip,
                ip,
                support.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            )
        if rounds < 0:
            raise RuntimeError(f"Routing error {rounds}")
        return arrivals, support, rounds

    def witness(self) -> dict[str, Any]:
        return json.loads(self.library.query_witness(self.handle).decode())

    def geometry(self, origin: int) -> np.ndarray:
        arrivals = np.empty(self.npoints, dtype=np.int32)
        support = np.zeros(self.nroutes, dtype=np.uint8)
        rounds = self.library.geometry_query(
            self.handle,
            origin,
            arrivals.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
            support.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        )
        if rounds < 0:
            raise RuntimeError("Geometry reference failed to converge")
        return arrivals
