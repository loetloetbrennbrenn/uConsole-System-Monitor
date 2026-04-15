#!/usr/bin/env python3
"""
Raspberry Pi CM5 System Monitor Widget
Displays temperature, CPU clock, ARM/GPU memory and allows 3 GHz overclocking.
"""

import tkinter as tk
from tkinter import messagebox
import subprocess
import math
import os
import re

# ── Config ────────────────────────────────────────────────────────────────────
REFRESH_MS      = 2000          # poll interval in milliseconds
CONFIG_PATH     = "/boot/firmware/config.txt"   # Pi OS ≥ Bookworm
CONFIG_PATH_ALT = "/boot/config.txt"            # older Pi OS

OC_FREQ        = 3000           # MHz target
OC_VOLTAGE     = 8              # over_voltage for 3 GHz

BG        = "#1e1e2e"
PANEL_BG  = "#2a2a3e"
TEXT_CLR  = "#cdd6f4"
MUTED_CLR = "#6c7086"
GREEN     = "#a6e3a1"
YELLOW    = "#f9e2af"
RED       = "#f38ba8"
BLUE      = "#89b4fa"
MAUVE     = "#cba6f7"
TEAL      = "#94e2d5"

# ── vcgencmd helpers ──────────────────────────────────────────────────────────

def vcgen(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["vcgencmd"] + args,
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_temp() -> float | None:
    """Returns temperature in °C or None."""
    raw = vcgen(["measure_temp"])          # temp=47.8'C
    m = re.search(r"temp=([\d.]+)", raw)
    return float(m.group(1)) if m else None


def get_clock_mhz() -> float | None:
    """Returns ARM clock in MHz or None."""
    raw = vcgen(["measure_clock", "arm"])  # frequency(48)=1800000000
    m = re.search(r"=(\d+)", raw)
    return round(int(m.group(1)) / 1_000_000, 1) if m else None


def get_mem_arm() -> int | None:
    """Returns ARM memory in MB or None."""
    raw = vcgen(["get_mem", "arm"])        # arm=3840M
    m = re.search(r"arm=(\d+)", raw)
    return int(m.group(1)) if m else None


def get_mem_gpu() -> int | None:
    """Returns GPU memory in MB or None."""
    raw = vcgen(["get_mem", "gpu"])        # gpu=256M
    m = re.search(r"gpu=(\d+)", raw)
    return int(m.group(1)) if m else None

# ── config.txt helpers ────────────────────────────────────────────────────────

def _config_path() -> str:
    return CONFIG_PATH if os.path.exists(CONFIG_PATH) else CONFIG_PATH_ALT


def is_overclocked() -> bool:
    path = _config_path()
    if not os.path.exists(path):
        return False
    with open(path) as f:
        content = f.read()
    return f"arm_freq={OC_FREQ}" in content


def apply_overclock() -> bool:
    """Write OC settings to config.txt (requires root). Returns success."""
    path = _config_path()
    try:
        with open(path) as f:
            lines = f.readlines()

        # Remove old arm_freq / over_voltage lines we might have written
        lines = [l for l in lines
                 if not re.match(r"^\s*(arm_freq|over_voltage)\s*=", l)]

        lines.append(f"\n# Added by pi_widget\n")
        lines.append(f"over_voltage={OC_VOLTAGE}\n")
        lines.append(f"arm_freq={OC_FREQ}\n")

        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(lines)
        os.replace(tmp, path)
        return True
    except PermissionError:
        return False


def remove_overclock() -> bool:
    """Remove OC settings from config.txt (requires root). Returns success."""
    path = _config_path()
    try:
        with open(path) as f:
            lines = f.readlines()

        out = []
        skip_comment = False
        for line in lines:
            if "# Added by pi_widget" in line:
                skip_comment = True
                continue
            if skip_comment and re.match(r"^\s*(over_voltage|arm_freq)\s*=", line):
                continue
            skip_comment = False
            # Also strip stray oc lines not preceded by our comment
            if re.match(r"^\s*(over_voltage|arm_freq)\s*=", line):
                continue
            out.append(line)

        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(out)
        os.replace(tmp, path)
        return True
    except PermissionError:
        return False

# ── Arc Gauge widget ──────────────────────────────────────────────────────────

class ArcGauge(tk.Canvas):
    """A semicircular gauge drawn on a Canvas."""

    MIN_TEMP = 30.0
    MAX_TEMP = 90.0

    def __init__(self, parent, size=180, **kwargs):
        super().__init__(parent, width=size, height=size // 2 + 30,
                         bg=PANEL_BG, highlightthickness=0, **kwargs)
        self.size = size
        self._draw_static()
        self._arc_id  = None
        self._val_id  = None
        self._label_id = None

    def _draw_static(self):
        s = self.size
        cx, cy = s // 2, s // 2 + 10
        r = s // 2 - 10

        # Track arc (grey background)
        self.create_arc(cx - r, cy - r, cx + r, cy + r,
                        start=0, extent=180,
                        style=tk.ARC, outline=MUTED_CLR, width=12)

        # Tick marks
        for deg in range(0, 181, 30):
            angle = math.radians(180 - deg)
            x1 = cx + (r - 8)  * math.cos(angle)
            y1 = cy - (r - 8)  * math.sin(angle)
            x2 = cx + (r + 2)  * math.cos(angle)
            y2 = cy - (r + 2)  * math.sin(angle)
            self.create_line(x1, y1, x2, y2, fill=MUTED_CLR, width=1)

        # Labels 30°C … 90°C
        for i, label in enumerate(["30", "45", "60", "75", "90"]):
            deg   = i * 45
            angle = math.radians(180 - deg)
            lx = cx + (r - 22) * math.cos(angle)
            ly = cy - (r - 22) * math.sin(angle)
            self.create_text(lx, ly, text=label, fill=MUTED_CLR,
                             font=("Helvetica", 7))

        self._cx, self._cy, self._r = cx, cy, r

    def update_value(self, temp: float | None):
        s, cx, cy, r = self.size, self._cx, self._cy, self._r

        # Remove old dynamic items
        for item in (self._arc_id, self._val_id, self._label_id):
            if item:
                self.delete(item)

        if temp is None:
            self._val_id = self.create_text(cx, cy + 10, text="N/A",
                                            fill=MUTED_CLR,
                                            font=("Helvetica", 22, "bold"))
            return

        # Clamp & map to 0–180°
        ratio  = (temp - self.MIN_TEMP) / (self.MAX_TEMP - self.MIN_TEMP)
        ratio  = max(0.0, min(1.0, ratio))
        extent = ratio * 180

        # Colour: green → yellow → red
        if ratio < 0.5:
            color = GREEN
        elif ratio < 0.75:
            color = YELLOW
        else:
            color = RED

        self._arc_id = self.create_arc(cx - r, cy - r, cx + r, cy + r,
                                       start=0, extent=extent,
                                       style=tk.ARC, outline=color, width=10)

        self._val_id = self.create_text(cx, cy + 5, text=f"{temp:.1f}°C",
                                        fill=color,
                                        font=("Helvetica", 20, "bold"))
        self._label_id = self.create_text(cx, cy + 25, text="Temperature",
                                          fill=MUTED_CLR,
                                          font=("Helvetica", 9))

# ── Stat card ─────────────────────────────────────────────────────────────────

class StatCard(tk.Frame):
    """Simple label card showing icon + value + sub-label."""

    def __init__(self, parent, title: str, unit: str, color: str, **kwargs):
        super().__init__(parent, bg=PANEL_BG, padx=14, pady=10, **kwargs)
        self._unit  = unit
        self._color = color

        tk.Label(self, text=title, bg=PANEL_BG,
                 fg=MUTED_CLR, font=("Helvetica", 9)).pack(anchor="w")

        self._val_lbl = tk.Label(self, text="—", bg=PANEL_BG,
                                 fg=color, font=("Helvetica", 22, "bold"))
        self._val_lbl.pack(anchor="w")

        tk.Label(self, text=unit, bg=PANEL_BG,
                 fg=MUTED_CLR, font=("Helvetica", 8)).pack(anchor="w")

    def set(self, value):
        if value is None:
            self._val_lbl.config(text="—", fg=MUTED_CLR)
        else:
            self._val_lbl.config(text=str(value), fg=self._color)

# ── Main application ──────────────────────────────────────────────────────────

class PiWidget(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("uConsole Monitor")
        self.configure(bg=BG)
        self.resizable(False, False)

        self._build_ui()
        self._update()          # first poll immediately

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text="🍓  uConsole",
                 bg=BG, fg=TEXT_CLR,
                 font=("Helvetica", 15, "bold")).pack(side="left")

        self._status = tk.Label(hdr, text="● live", bg=BG, fg=GREEN,
                                font=("Helvetica", 9))
        self._status.pack(side="right", padx=4)

        # ── Temperature gauge ────────────────────────────────────────────────
        gauge_frame = tk.Frame(self, bg=PANEL_BG, bd=0)
        gauge_frame.pack(fill="x", padx=16, pady=(0, 10))

        self._gauge = ArcGauge(gauge_frame, size=220)
        self._gauge.pack(pady=(10, 6))

        # ── Stat cards row ───────────────────────────────────────────────────
        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=16)
        cards.columnconfigure((0, 1, 2), weight=1, uniform="card")

        self._clock_card = StatCard(cards, "ARM Clock", "MHz", BLUE)
        self._clock_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._arm_card = StatCard(cards, "ARM Memory", "MB", MAUVE)
        self._arm_card.grid(row=0, column=1, sticky="nsew", padx=3)

        self._gpu_card = StatCard(cards, "GPU Memory", "MB", TEAL)
        self._gpu_card.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        # ── Overclock section ────────────────────────────────────────────────
        oc_frame = tk.Frame(self, bg=PANEL_BG)
        oc_frame.pack(fill="x", padx=16, pady=12)

        tk.Label(oc_frame, text="Overclocking",
                 bg=PANEL_BG, fg=MUTED_CLR,
                 font=("Helvetica", 9)).pack(anchor="w", padx=14, pady=(10, 2))

        self._oc_info = tk.Label(
            oc_frame,
            text=self._oc_status_text(),
            bg=PANEL_BG, fg=TEXT_CLR, wraplength=320, justify="left",
            font=("Helvetica", 9)
        )
        self._oc_info.pack(anchor="w", padx=14, pady=(0, 8))

        self._oc_btn = tk.Button(
            oc_frame,
            text=self._oc_btn_label(),
            bg=RED if not is_overclocked() else GREEN,
            fg="#11111b", activebackground=YELLOW,
            relief="flat", padx=14, pady=7,
            font=("Helvetica", 10, "bold"),
            cursor="hand2",
            command=self._toggle_overclock
        )
        self._oc_btn.pack(side="left", padx=14, pady=(0, 12))

        # Footer
        tk.Label(self, text="Requires sudo · Reboot to apply OC changes",
                 bg=BG, fg=MUTED_CLR, font=("Helvetica", 7)).pack(pady=(0, 8))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _oc_status_text(self) -> str:
        if is_overclocked():
            return f"✔  {OC_FREQ} MHz overclock is ACTIVE  (over_voltage={OC_VOLTAGE})"
        return f"Overclock to {OC_FREQ} MHz — adds  over_voltage={OC_VOLTAGE}  to {_config_path()}"

    def _oc_btn_label(self) -> str:
        return "Remove 3 GHz Overclock" if is_overclocked() else "Enable 3 GHz Overclock"

    def _refresh_oc_ui(self):
        self._oc_info.config(text=self._oc_status_text())
        oc = is_overclocked()
        self._oc_btn.config(
            text=self._oc_btn_label(),
            bg=GREEN if oc else RED
        )

    # ── Overclock toggle ──────────────────────────────────────────────────────

    def _toggle_overclock(self):
        if is_overclocked():
            ok = remove_overclock()
            if ok:
                messagebox.showinfo(
                    "Overclock removed",
                    "OC settings removed from config.txt.\n\nReboot to apply."
                )
            else:
                messagebox.showerror(
                    "Permission denied",
                    "Could not write to config.txt.\n\n"
                    "Run this script with sudo:\n"
                    "  sudo python3 pi_widget.py"
                )
        else:
            confirm = messagebox.askyesno(
                "Enable Overclock",
                f"This will write the following to {_config_path()}:\n\n"
                f"  over_voltage={OC_VOLTAGE}\n"
                f"  arm_freq={OC_FREQ}\n\n"
                "Overclocking can void warranty and cause instability.\n"
                "Adequate cooling is required!\n\n"
                "Continue?"
            )
            if not confirm:
                return
            ok = apply_overclock()
            if ok:
                messagebox.showinfo(
                    "Overclock applied",
                    f"Settings written to {_config_path()}.\n\nReboot to apply."
                )
            else:
                messagebox.showerror(
                    "Permission denied",
                    "Could not write to config.txt.\n\n"
                    "Run this script with sudo:\n"
                    "  sudo python3 pi_widget.py"
                )
        self._refresh_oc_ui()

    # ── Periodic update ───────────────────────────────────────────────────────

    def _update(self):
        temp  = get_temp()
        clock = get_clock_mhz()
        arm   = get_mem_arm()
        gpu   = get_mem_gpu()

        self._gauge.update_value(temp)
        self._clock_card.set(clock)
        self._arm_card.set(arm)
        self._gpu_card.set(gpu)

        # Pulse status dot
        current = self._status.cget("fg")
        self._status.config(fg=MUTED_CLR if current == GREEN else GREEN)

        self.after(REFRESH_MS, self._update)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = PiWidget()
    app.mainloop()
