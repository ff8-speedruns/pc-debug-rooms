"""
Live field warp for FF8 (2013 Steam, EN or FR), with an optional story-progress
override. Replicates the SCRIPT_MAPJUMP0 field opcode from outside the game:
spawn X/Y/triangle, destination field id, then the low byte of
globalFieldNextModuleID = 1. Uses the "keep current position" sentinel, which
is fine for debug rooms (they have no incoming gateways).

EN/FR: offsets below are EN-build. FR = EN - 0x328 (dominant delta for this
region in addresses.json, NOT verified on a live FR process). Run `verify`
before `warp` on FR. If your FR exe isn't named FF8_FR.exe, set
FF8_PROCESS_NAME (plus FF8_BUILD=FR) to override.

CLI:
    python field_warp.py fields [prefix]            # look up field ids, no game needed
    python field_warp.py read                       # dump live state (read-only)
    python field_warp.py verify                     # cross-check CURRENT_FIELD_ID vs maplist
    python field_warp.py story [value]              # read (or write) story progress, var 256
    python field_warp.py warp <id_or_name> [story]  # write experiment (default: "test")
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pymem
import pymem.process

EN_PROCESS_NAME = "FF8_EN.exe"
FR_PROCESS_NAME = "FF8_FR.exe"  # naming-convention guess, not confirmed
EN_FR_DELTA = 0x328             # en_offset - fr_offset, see docstring


class Proc:
    """Live-process handle: reads/writes by EN-build module-relative offset,
    auto-converted to FR when attached to the FR build."""

    def __init__(self, pm, base: int, build: str):
        self.pm = pm
        self.base = base
        self.build = build  # "EN" or "FR"

    @classmethod
    def attach(cls) -> "Proc":
        override_name = os.environ.get("FF8_PROCESS_NAME")
        if override_name:
            candidates = [(override_name, os.environ.get("FF8_BUILD", "EN").upper())]
        else:
            candidates = [(EN_PROCESS_NAME, "EN"), (FR_PROCESS_NAME, "FR")]

        last_err = None
        for name, build in candidates:
            try:
                pm = pymem.Pymem(name)
            except Exception as e:  # noqa: BLE001 -- pymem raises its own broad exception types
                last_err = e
                continue
            mod = pymem.process.module_from_name(pm.process_handle, name)
            if mod is None:
                raise RuntimeError(f"attached to {name} but could not resolve its module")
            if build == "FR":
                print(f"NOTE: attached to {name} as FR; addresses use the unverified "
                      f"EN-FR delta 0x{EN_FR_DELTA:X}. Run `verify` before `warp`.")
            return cls(pm, mod.lpBaseOfDll, build)

        names = ", ".join(n for n, _ in candidates)
        raise RuntimeError(f"none of [{names}] is running (last error: {last_err})")

    def abs_addr(self, en_offset: int) -> int:
        return self.base + (en_offset - EN_FR_DELTA if self.build == "FR" else en_offset)

    def read_u16(self, en_offset: int) -> int:
        return self.pm.read_ushort(self.abs_addr(en_offset))

    def read_u32(self, en_offset: int) -> int:
        return self.pm.read_uint(self.abs_addr(en_offset))

    def read_cstr(self, en_offset: int, max_len: int = 256) -> str:
        raw = self.pm.read_bytes(self.abs_addr(en_offset), max_len)
        return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace")

    # Write experiments -- the only write paths.
    def write_u16(self, en_offset: int, value: int) -> None:
        self.pm.write_ushort(self.abs_addr(en_offset), value & 0xFFFF)

    def write_u8(self, en_offset: int, value: int) -> None:
        self.pm.write_uchar(self.abs_addr(en_offset), value & 0xFF)


# EN-build module-relative offsets, all CONFIRMED live on EN-Steam 2026-07-26.
CURRENT_FIELD_ID = 0x18D2FC0              # u16 -- field to load next / currently loaded
CURRENT_FIELD_NAME = 0x18D2DB0            # cstr -- filled from maplist by Field_LoadResources
ENGINE_STATE = 0x18E0758                  # u32 -- 0=field,1=wm-transition,2=wm,3=battle,6=menu,10=menu-closing
GLOBAL_FIELD_NEXT_MODULE_ID = 0x18E4760   # u16 -- same-module quick-jump request; low byte 1=another field
MENU_STATE_OPCODE_MENU_ID = 0x18E4762     # u16 -- destination field ID for a field jump
WM2FIELD_FIELD_X = 0x18E4764              # u16 -- spawn X
WM2FIELD_FIELD_Y = 0x18E4766              # u16 -- spawn Y
WM2FIELD_EXTRA = 0x18E4768                # u16 -- spawn walkmesh triangle
VARMAP_START = 0x18FE9B8                  # savemap script-variable block
STORY_PROGRESS = VARMAP_START + 256       # u16 -- "Main Story quest progress" (var 256)

KEEP_POSITION = 0x7FFF
DEFAULT_TARGET = "test"

# maplist lives next to this script (or inside the PyInstaller bundle).
MAPLIST_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "maplist"


def load_maplist() -> list[str]:
    return MAPLIST_PATH.read_text(encoding="latin-1").splitlines()


def field_name(field_id: int, maplist: list[str]) -> str:
    return maplist[field_id].strip() if 0 <= field_id < len(maplist) else "<out of range>"


def resolve_field_id(spec: str, maplist: list[str]) -> int:
    if spec.isdigit():
        return int(spec)
    matches = [i for i, name in enumerate(maplist) if name.strip().lower() == spec.lower()]
    if not matches:
        raise ValueError(f"no field named {spec!r} found in maplist")
    if len(matches) > 1:
        raise ValueError(f"{spec!r} is ambiguous: maplist lines {matches}")
    return matches[0]


def read_state(proc: Proc, maplist: list[str]) -> dict:
    field_id = proc.read_u16(CURRENT_FIELD_ID)
    return {
        "build": proc.build,
        "field_id": field_id,
        "maplist_name": field_name(field_id, maplist),
        "live_name": proc.read_cstr(CURRENT_FIELD_NAME).strip(),
        "engine_state": proc.read_u32(ENGINE_STATE),
        "next_module_id": proc.read_u16(GLOBAL_FIELD_NEXT_MODULE_ID),
        "menu_id": proc.read_u16(MENU_STATE_OPCODE_MENU_ID),
    }


def verified(state: dict) -> bool:
    """Offsets are right iff the live field-name string matches maplist[CURRENT_FIELD_ID]."""
    return bool(state["live_name"]) and state["live_name"] == state["maplist_name"]


def cmd_read(proc: Proc, maplist: list[str]):
    print(f"Live state ({proc.build} build, module base 0x{proc.base:X}):")
    for k, v in read_state(proc, maplist).items():
        print(f"  {k} = {v!r}")


def cmd_verify(proc: Proc, maplist: list[str]):
    s = read_state(proc, maplist)
    print(f"build = {s['build']}, CURRENT_FIELD_ID = {s['field_id']}")
    print(f"  maplist name = {s['maplist_name']!r}, live name = {s['live_name']!r}")
    print("MATCH -- offsets OK." if verified(s) else "MISMATCH -- do not run `warp`.")


def cmd_fields(maplist: list[str], prefix: str = ""):
    for i, name in enumerate(maplist):
        if name.strip().lower().startswith(prefix.lower()):
            print(f"{i}\t{name.strip()}")


def cmd_story(proc: Proc, value=None):
    current = proc.read_u16(STORY_PROGRESS)
    if value is None:
        print(f"Main Story quest progress (var 256) = {current}")
        return
    print(f"STORY WRITE EXPERIMENT: Main Story quest progress {current} -> {int(value)}")
    proc.write_u16(STORY_PROGRESS, int(value))


def cmd_warp(proc: Proc, maplist: list[str], spec: str, story=None):
    field_id = resolve_field_id(spec, maplist)
    print(f"WARP EXPERIMENT ({proc.build} build): field id {field_id} "
          f"({field_name(field_id, maplist)!r}), replicating SCRIPT_MAPJUMP0.")
    proc.write_u16(WM2FIELD_FIELD_X, KEEP_POSITION)
    proc.write_u16(WM2FIELD_FIELD_Y, KEEP_POSITION)
    proc.write_u16(WM2FIELD_EXTRA, 0)
    proc.write_u16(MENU_STATE_OPCODE_MENU_ID, field_id)
    proc.write_u8(GLOBAL_FIELD_NEXT_MODULE_ID, 1)  # low byte only; high byte may carry flags
    if story is not None:
        cmd_story(proc, story)
    print("Written. Give the game a couple of frames, then run `read` to confirm the jump landed.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return
    cmd, *rest = argv
    maplist = load_maplist()
    if cmd == "fields":
        cmd_fields(maplist, rest[0] if rest else "")
        return

    proc = Proc.attach()
    if cmd == "read":
        cmd_read(proc, maplist)
    elif cmd == "verify":
        cmd_verify(proc, maplist)
    elif cmd == "story":
        cmd_story(proc, rest[0] if rest else None)
    elif cmd == "warp":
        cmd_warp(proc, maplist, rest[0] if rest else DEFAULT_TARGET, rest[1] if len(rest) > 1 else None)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
