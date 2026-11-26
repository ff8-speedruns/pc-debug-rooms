"""Small GUI for warping to FF8's debug rooms on the live PC game.

Thin front-end over field_warp.py (same folder): pick a room, click Warp.
Only rooms that load are listed -- the crashers from DEBUG_ROOMS.md are left out.
Run: python debug_room_app.py
Be on an ordinary field (walking around, no menu/battle) before warping.
"""
import tkinter as tk
from tkinter import messagebox

import field_warp as fw

# (field id, name, what's there) -- from DEBUG_ROOMS.md's live survey
ROOMS = [
    (77, "test", "Master debug menu (start here)"),
    (83, "test6", "Kitase's room: biggest story/location/flag/card warp menu"),
    (88, "test14", "Refined copy of the master menu"),
    (79, "test2", "Dollet-arc mission & location warps"),
    (80, "test3", "Sound test + late-game location list"),
    (82, "test5", "Timber/Winhill/FH sidequest & story tester"),
    (84, "test7", "Warp list"),
    (87, "test13", "SeeD test result screen"),
    (95, "testbl6", "Zell's Duel test harness"),
    (98, "testbl9", "Ultimecia Castle seal-release menu"),
    (72, "testno", "Loads; Japanese-only text"),
    (86, "test9", "Stub, nothing to see"),
]
ENGINE = {0: "field", 1: "loading", 2: "world map", 3: "battle", 6: "menu", 10: "menu closing"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FF8 Debug Rooms")
        self.proc = None
        self.maplist = fw.load_maplist()

        self.list = tk.Listbox(self, width=70, height=len(ROOMS), font=("Consolas", 10))
        for fid, name, desc in ROOMS:
            self.list.insert(tk.END, f"{fid:>3}  {name:<8} {desc}")
        self.list.selection_set(0)
        self.list.pack(padx=8, pady=(8, 4), fill=tk.BOTH, expand=True)
        self.list.bind("<Double-Button-1>", lambda _e: self.warp())

        row = tk.Frame(self)
        row.pack(fill=tk.X, padx=8)
        tk.Label(row, text="Story progress (optional):").pack(side=tk.LEFT)
        self.story = tk.Entry(row, width=8)
        self.story.pack(side=tk.LEFT, padx=4)
        tk.Button(row, text="Warp", width=10, command=self.warp).pack(side=tk.RIGHT)

        self.status = tk.Label(self, anchor="w", fg="gray30")
        self.status.pack(fill=tk.X, padx=8, pady=(4, 8))
        self.poll()

    def attach(self):
        if self.proc is None:
            self.proc = fw.Proc.attach()
        return self.proc

    def poll(self):
        try:
            s = fw.read_state(self.attach(), self.maplist)
            eng = s["engine_state"]
            self.status.config(text=f"Attached ({s['build']}) | field {s['field_id']} "
                                    f"{s['live_name']!r} | {ENGINE.get(eng, eng)} | "
                                    f"{'offsets OK' if fw.verified(s) else 'OFFSET MISMATCH'}")
        except Exception as e:  # game not running / closed: retry next tick
            self.proc = None
            self.status.config(text=f"Not attached: {e}")
        self.after(500, self.poll)

    def warp(self):
        sel = self.list.curselection()
        if not sel:
            return
        fid = ROOMS[sel[0]][0]
        story = self.story.get().strip() or None
        if story is not None and not story.isdigit():
            messagebox.showerror("FF8 Debug Rooms", "Story progress must be a number.")
            return
        try:
            proc = self.attach()
            s = fw.read_state(proc, self.maplist)
            if not fw.verified(s):
                messagebox.showerror("FF8 Debug Rooms", "Live field name doesn't match the expected "
                                     "offsets (different game build?). Not warping.")
                return
            if s["engine_state"] != 0:
                if not messagebox.askyesno("FF8 Debug Rooms",
                                           "Game isn't on a normal field (menu/battle/world map?). "
                                           "Warp anyway?"):
                    return
            fw.cmd_warp(proc, self.maplist, str(fid), story)
        except Exception as e:
            messagebox.showerror("FF8 Debug Rooms", str(e))


if __name__ == "__main__":
    App().mainloop()
