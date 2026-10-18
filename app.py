"""
Macro de Controle - grava o que voce aperta no controle de PS5 e repete num controle virtual.

Atalhos globais (funcionam com o jogo em primeiro plano):
  F9  = comecar / parar gravacao
  F8  = executar / parar macro
"""
import copy
import json
import os
import random
import sys
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# Deixa o SDL receber o controle mesmo sem janela do pygame em foco.
os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame
from pygame._sdl2 import controller as sdlc

try:
    import vgamepad as vg
except Exception as e:  # driver ViGEmBus ausente ou pacote nao instalado
    vg = None
    VG_ERRO = str(e)
else:
    VG_ERRO = ""

try:
    import keyboard
except Exception:
    keyboard = None

# No app empacotado (.exe) as macros ficam ao lado do executavel, para a pasta inteira ser portatil.
def resource(name):
    """Arquivo que vai dentro do programa (icone, macros padrao, driver)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# Macros e configuracoes ficam em %APPDATA%\MacroControle: o .exe pode ficar em qualquer pasta
# sem criar nada ao lado dele. Na primeira vez num PC, copia as macros que vem dentro do programa.
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MacroControle")
MACROS_DIR = os.path.join(DATA_DIR, "macros")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
DRIVER_MSI = resource("ViGEmBusSetup_x64.msi")


def seed_data():
    import shutil
    first = not os.path.isdir(MACROS_DIR)
    os.makedirs(MACROS_DIR, exist_ok=True)
    src = resource(os.path.join("padrao", "macros"))
    if first and os.path.isdir(src):
        for f in os.listdir(src):
            if f.endswith(".json"):
                shutil.copy2(os.path.join(src, f), os.path.join(MACROS_DIR, f))
    cfg = resource(os.path.join("padrao", "settings.json"))
    if not os.path.exists(SETTINGS_FILE) and os.path.exists(cfg):
        shutil.copy2(cfg, SETTINGS_FILE)


seed_data()

# Botoes do SDL (SDL_GameControllerButton) -> nome PlayStation
BTN_NAMES = {
    0: "cross", 1: "circle", 2: "square", 3: "triangle",
    4: "create", 5: "ps", 6: "options", 7: "l3", 8: "r3",
    9: "l1", 10: "r1", 11: "up", 12: "down", 13: "left", 14: "right",
    15: "mute", 20: "touchpad",
}
AXIS_NAMES = {0: "lx", 1: "ly", 2: "rx", 3: "ry", 4: "l2", 5: "r2"}
LABEL = {
    "cross": "X", "circle": "O", "square": "□", "triangle": "△", "create": "Create",
    "ps": "PS", "options": "Options", "l3": "L3", "r3": "R3", "l1": "L1", "r1": "R1",
    "up": "↑", "down": "↓", "left": "←", "right": "→", "mute": "Mute", "touchpad": "Touchpad",
    "lx": "Analógico E", "ly": "Analógico E", "rx": "Analógico D", "ry": "Analógico D",
    "l2": "L2", "r2": "R2",
}


# ---------------------------------------------------------------------------
# Controle virtual (saida)
# ---------------------------------------------------------------------------
class VirtualPad:
    """Envolve o vgamepad. tipo = 'ds4' (aparece como controle PlayStation) ou 'x360'."""

    def __init__(self, tipo):
        if vg is None:
            raise RuntimeError("Controle virtual indisponível: " + VG_ERRO)
        self.tipo = tipo
        self.pad = vg.VDS4Gamepad() if tipo == "ds4" else vg.VX360Gamepad()
        self.dpad = set()
        self.axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "l2": 0.0, "r2": 0.0}
        if tipo == "ds4":
            B, S = vg.DS4_BUTTONS, vg.DS4_SPECIAL_BUTTONS
            self.btn = {
                "cross": B.DS4_BUTTON_CROSS, "circle": B.DS4_BUTTON_CIRCLE,
                "square": B.DS4_BUTTON_SQUARE, "triangle": B.DS4_BUTTON_TRIANGLE,
                "l1": B.DS4_BUTTON_SHOULDER_LEFT, "r1": B.DS4_BUTTON_SHOULDER_RIGHT,
                "l3": B.DS4_BUTTON_THUMB_LEFT, "r3": B.DS4_BUTTON_THUMB_RIGHT,
                "options": B.DS4_BUTTON_OPTIONS, "create": B.DS4_BUTTON_SHARE,
            }
            self.special = {"ps": S.DS4_SPECIAL_BUTTON_PS, "touchpad": S.DS4_SPECIAL_BUTTON_TOUCHPAD}
        else:
            X = vg.XUSB_BUTTON
            self.btn = {
                "cross": X.XUSB_GAMEPAD_A, "circle": X.XUSB_GAMEPAD_B,
                "square": X.XUSB_GAMEPAD_X, "triangle": X.XUSB_GAMEPAD_Y,
                "l1": X.XUSB_GAMEPAD_LEFT_SHOULDER, "r1": X.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "l3": X.XUSB_GAMEPAD_LEFT_THUMB, "r3": X.XUSB_GAMEPAD_RIGHT_THUMB,
                "options": X.XUSB_GAMEPAD_START, "create": X.XUSB_GAMEPAD_BACK,
                "touchpad": X.XUSB_GAMEPAD_BACK, "ps": X.XUSB_GAMEPAD_GUIDE,
                "up": X.XUSB_GAMEPAD_DPAD_UP, "down": X.XUSB_GAMEPAD_DPAD_DOWN,
                "left": X.XUSB_GAMEPAD_DPAD_LEFT, "right": X.XUSB_GAMEPAD_DPAD_RIGHT,
            }
            self.special = {}
        self.neutral()

    def _dpad_ds4(self):
        D = vg.DS4_DPAD_DIRECTIONS
        u, d, l, r = ("up" in self.dpad), ("down" in self.dpad), ("left" in self.dpad), ("right" in self.dpad)
        if u and r: v = D.DS4_BUTTON_DPAD_NORTHEAST
        elif u and l: v = D.DS4_BUTTON_DPAD_NORTHWEST
        elif d and r: v = D.DS4_BUTTON_DPAD_SOUTHEAST
        elif d and l: v = D.DS4_BUTTON_DPAD_SOUTHWEST
        elif u: v = D.DS4_BUTTON_DPAD_NORTH
        elif d: v = D.DS4_BUTTON_DPAD_SOUTH
        elif l: v = D.DS4_BUTTON_DPAD_WEST
        elif r: v = D.DS4_BUTTON_DPAD_EAST
        else: v = D.DS4_BUTTON_DPAD_NONE
        self.pad.directional_pad(direction=v)

    def button(self, name, pressed):
        if self.tipo == "ds4" and name in ("up", "down", "left", "right"):
            (self.dpad.add if pressed else self.dpad.discard)(name)
            self._dpad_ds4()
        elif name in self.special:
            if pressed: self.pad.press_special_button(special_button=self.special[name])
            else: self.pad.release_special_button(special_button=self.special[name])
        elif name in self.btn:
            if pressed: self.pad.press_button(button=self.btn[name])
            else: self.pad.release_button(button=self.btn[name])

    def axis(self, name, value):
        self.axes[name] = value
        a = self.axes
        if name in ("l2", "r2"):
            (self.pad.left_trigger_float if name == "l2" else self.pad.right_trigger_float)(value_float=value)
            if self.tipo == "ds4":  # o DS4 tambem tem o "botao" digital do gatilho
                b = vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_LEFT if name == "l2" else vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_RIGHT
                (self.pad.press_button if value > 0.1 else self.pad.release_button)(button=b)
        else:
            # SDL: Y positivo = para baixo. DS4 tambem; no Xbox o Y positivo e para cima.
            inv = -1.0 if self.tipo == "x360" else 1.0
            if name in ("lx", "ly"):
                self.pad.left_joystick_float(x_value_float=a["lx"], y_value_float=a["ly"] * inv)
            else:
                self.pad.right_joystick_float(x_value_float=a["rx"], y_value_float=a["ry"] * inv)

    def apply(self, ev):
        if ev["k"] == "b":
            self.button(ev["n"], ev["v"] == 1)
        else:
            self.axis(ev["n"], ev["v"])

    def update(self):
        self.pad.update()

    def neutral(self):
        self.pad.reset()
        self.dpad.clear()
        for k in self.axes:
            self.axes[k] = 0.0
        self.pad.update()


# ---------------------------------------------------------------------------
# Leitura do controle fisico (entrada)
# ---------------------------------------------------------------------------
class InputReader(threading.Thread):
    def __init__(self, out_q):
        super().__init__(daemon=True)
        self.out_q = out_q
        self.recording = False
        self.paused = False          # True enquanto a macro toca (nao grava a propria saida)
        self.events = []
        self.t0 = None
        self.first_input_start = True
        self.last_axis = {}
        self.controllers = {}
        self.lock = threading.Lock()

    def start_recording(self, first_input_start=True):
        with self.lock:
            self.events = []
            self.last_axis = {}
            self.first_input_start = first_input_start
            self.t0 = None if first_input_start else time.perf_counter()
            self.rec_started = time.perf_counter()
            self.recording = True

    def stop_recording(self):
        with self.lock:
            self.recording = False
            end = time.perf_counter()
            if self.t0 is None:
                return {"length": 0.0, "events": []}
            evs = self.events
            # solta tudo que ficou apertado no fim, para a macro nao terminar com botao preso
            held = {}
            for e in evs:
                held[(e["k"], e["n"])] = e["v"]
            length = round(end - self.t0, 4)
            for (k, n), v in held.items():
                if (k == "b" and v == 1) or (k == "a" and abs(v) > 0.0):
                    evs.append({"t": length, "k": k, "n": n, "v": 0 if k == "b" else 0.0})
            return {"length": length, "events": evs}

    def _rec(self, k, n, v):
        if not self.recording or self.paused:
            return
        now = time.perf_counter()
        with self.lock:
            if self.t0 is None:
                self.t0 = now
            self.events.append({"t": round(now - self.t0, 4), "k": k, "n": n, "v": v})
            count = len(self.events)
        self.out_q.put(("rec_count", count))

    def run(self):
        pygame.display.init()
        pygame.joystick.init()
        sdlc.init()
        for i in range(sdlc.get_count()):
            self._open(i)
        while True:
            for e in pygame.event.get():
                if e.type == pygame.CONTROLLERDEVICEADDED:
                    self._open(e.device_index)
                elif e.type == pygame.CONTROLLERDEVICEREMOVED:
                    self.controllers.pop(e.instance_id, None)
                    self.out_q.put(("devices", self._names()))
                elif e.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
                    n = BTN_NAMES.get(e.button)
                    if n:
                        self._rec("b", n, 1 if e.type == pygame.CONTROLLERBUTTONDOWN else 0)
                        if e.type == pygame.CONTROLLERBUTTONDOWN:
                            self.out_q.put(("pressed", n))
                elif e.type == pygame.CONTROLLERAXISMOTION:
                    n = AXIS_NAMES.get(e.axis)
                    if not n:
                        continue
                    v = max(-1.0, min(1.0, e.value / 32767.0))
                    if n in ("l2", "r2"):
                        v = max(0.0, v)
                    elif abs(v) < 0.06:   # zona morta do analogico
                        v = 0.0
                    v = round(v, 3)
                    last = self.last_axis.get(n, 0.0)
                    # so grava mudanca relevante, para a macro nao ficar gigante
                    if abs(v - last) >= 0.02 or (v != last and v in (0.0, 1.0, -1.0)):
                        self.last_axis[n] = v
                        self._rec("a", n, v)
            time.sleep(0.001)

    def _open(self, idx):
        try:
            if sdlc.is_controller(idx):
                c = sdlc.Controller(idx)
                self.controllers[c.as_joystick().get_instance_id()] = c
                self.out_q.put(("devices", self._names()))
        except Exception as ex:
            self.out_q.put(("log", f"Não consegui abrir o controle {idx}: {ex}"))

    def _names(self):
        out = []
        for c in self.controllers.values():
            try:
                out.append(c.name)
            except Exception:
                pass
        return out


# ---------------------------------------------------------------------------
# Execucao da macro
# ---------------------------------------------------------------------------
def wait_until(target, stop_evt, deadline=None):
    """Espera ate `target` (perf_counter). Retorna False se mandaram parar ou passou da duracao."""
    while True:
        if stop_evt.is_set():
            return False
        now = time.perf_counter()
        if deadline is not None and now >= deadline:
            return False
        rest = target - now
        if rest <= 0:
            return True
        time.sleep(min(rest - 0.0015, 0.01) if rest > 0.003 else 0)


MIN_HOLD = 0.02  # nenhuma tecla fica apertada menos que isso no modo humano (o jogo poderia nao ver)


def timeline(macro, human=None):
    """Lista [(tempo, evento)] e duracao total de uma execucao.
    human = (min_s, max_s): cada intervalo antes de um BOTAO ganha um desvio aleatorio nessa janela.
    Movimentos de analogico mantem o espacamento entre si (senao o movimento ficaria picotado)."""
    events = sorted(macro["events"], key=lambda e: e["t"])
    length = macro["length"]
    if not human:
        return [(e["t"], e) for e in events], length
    lo, hi = human
    out, pressed = [], {}
    prev_old = prev_new = 0.0
    for e in events:
        gap = e["t"] - prev_old
        if e["k"] == "b":
            gap = max(0.0, gap + random.uniform(lo, hi))
        nt = prev_new + gap
        if e["k"] == "b":
            if e["v"] == 1:
                pressed[e["n"]] = nt
            elif e["n"] in pressed and nt - pressed[e["n"]] < MIN_HOLD:
                nt = pressed[e["n"]] + MIN_HOLD
        out.append((nt, e))
        prev_old, prev_new = e["t"], nt
    tail = max(0.0, length - prev_old + random.uniform(lo, hi))
    return out, prev_new + tail


def play_macro(pad, macro, speed, reps, max_secs, pause, stop_evt, report, human=None):
    start = time.perf_counter()
    deadline = start + max_secs if max_secs > 0 else None
    n = 0
    try:
        while not stop_evt.is_set():
            tl, length = timeline(macro, human)
            t0 = time.perf_counter()
            n += 1
            report(("run", n))
            ok = True
            for t, ev in tl:
                if not wait_until(t0 + t / speed, stop_evt, deadline):
                    ok = False
                    break
                pad.apply(ev)
                pad.update()
            if ok:
                wait_until(t0 + length / speed, stop_evt, deadline)
            pad.neutral()
            if not ok or stop_evt.is_set():
                break
            if reps > 0 and n >= reps:
                break
            if deadline is not None and time.perf_counter() >= deadline:
                break
            p = max(0.0, pause + random.uniform(*human)) if human else pause
            if p > 0 and not wait_until(time.perf_counter() + p, stop_evt, deadline):
                break
    finally:
        pad.neutral()
        report(("done", n, time.perf_counter() - start))


# ---------------------------------------------------------------------------
# Edicao: a macro vira uma lista de PASSOS (cada tecla apertada), com
# "pausa antes" (desde que a tecla anterior foi solta) e "segurar" (quanto tempo fica apertada).
# Mexer na pausa empurra tudo o que vem depois; mexer no segurar muda so o soltar daquela tecla.
# ---------------------------------------------------------------------------
def steps_of(macro):
    macro["events"].sort(key=lambda e: e["t"])
    rows, open_ = [], {}
    for e in macro["events"]:
        if e["k"] != "b":
            continue
        if e["v"] == 1:
            open_[e["n"]] = len(rows)
            rows.append({"n": e["n"], "on": e, "off": None})
        elif e["n"] in open_:
            rows[open_.pop(e["n"])]["off"] = e
    return rows


def _end(row):
    return row["off"]["t"] if row["off"] else row["on"]["t"]


def step_pause(rows, i):
    return rows[i]["on"]["t"] - (_end(rows[i - 1]) if i > 0 else 0.0)


def step_hold(row):
    return _end(row) - row["on"]["t"]


def _fix_length(macro, tail=None):
    last = max((e["t"] for e in macro["events"]), default=0.0)
    if tail is not None:
        macro["length"] = round(last + max(0.0, tail), 4)
    else:
        macro["length"] = round(max(macro["length"], last), 4)


def set_pause(macro, i, pause):
    rows = steps_of(macro)
    prev_end = _end(rows[i - 1]) if i > 0 else 0.0
    prev_start = rows[i - 1]["on"]["t"] if i > 0 else 0.0
    old = rows[i]["on"]["t"]
    new = max(prev_start, prev_end + pause)   # nunca comeca antes da tecla anterior
    delta = new - old
    tail = macro["length"] - max(e["t"] for e in macro["events"])
    for e in macro["events"]:
        if e["t"] >= old - 1e-9:
            e["t"] = round(max(0.0, e["t"] + delta), 4)
    _fix_length(macro, tail)


def set_hold(macro, i, hold):
    rows = steps_of(macro)
    r = rows[i]
    tail = final_pause(macro)
    hold = max(0.01, hold)
    if r["off"] is None:
        r["off"] = {"t": r["on"]["t"], "k": "b", "n": r["n"], "v": 0}
        macro["events"].append(r["off"])
    old_end = r["off"]["t"]
    delta = round(r["on"]["t"] + hold - old_end, 4)
    # tudo o que acontecia depois de soltar esta tecla anda junto: as pausas seguintes nao mudam
    for e in macro["events"]:
        if e is r["off"] or e["t"] >= old_end - 1e-9 and e is not r["on"]:
            e["t"] = round(max(0.0, e["t"] + delta), 4)
    _fix_length(macro, tail)
    macro["events"].sort(key=lambda e: e["t"])


def delete_step(macro, i):
    r = steps_of(macro)[i]
    macro["events"] = [e for e in macro["events"] if e is not r["on"] and e is not r["off"]]


def add_step(macro, name, pause, hold):
    rows = steps_of(macro)
    tail = macro["length"] - max((e["t"] for e in macro["events"]), default=0.0)
    start = (_end(rows[-1]) if rows else 0.0) + max(0.0, pause)
    macro["events"].append({"t": round(start, 4), "k": "b", "n": name, "v": 1})
    macro["events"].append({"t": round(start + max(0.01, hold), 4), "k": "b", "n": name, "v": 0})
    _fix_length(macro, tail if rows else 0.1)


def final_pause(macro):
    return macro["length"] - max((e["t"] for e in macro["events"]), default=0.0)



# ---------------------------------------------------------------------------
# Interface (customtkinter)
# ---------------------------------------------------------------------------
import customtkinter as ctk
from PIL import Image

ctk.set_appearance_mode("dark")

BG, CARD, FIELD, BORDER, HOVER = "#0a0b0d", "#14161b", "#1d2027", "#2a2e37", "#262a33"
FG, MUTED, WHITE = "#eceef1", "#8b92a0", "#ffffff"
RED, RED_H, GREEN, GREEN_H = "#e5484d", "#f2585d", "#1fb866", "#28cc75"
FONT = "Segoe UI"


def F(size, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def set_icon(win):
    def _set():
        try:
            win.iconbitmap(resource("icone.ico"))
        except Exception:
            pass
    _set()
    win.after(300, _set)  # o customtkinter troca o icone logo depois de abrir; reaplica por cima


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER, **kw)


def entry(parent, var, width=80):
    return ctk.CTkEntry(parent, textvariable=var, width=width, height=34, fg_color=FIELD, border_color=BORDER,
                        corner_radius=8, font=F(13), justify="center", text_color=FG)


def ghost(parent, text, cmd, color=FG, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(parent, text=text, command=cmd, fg_color=FIELD, hover_color=HOVER, text_color=color,
                         corner_radius=8, font=F(13), **kw)


def solid(parent, text, cmd, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(parent, text=text, command=cmd, fg_color=WHITE, hover_color="#d9dbe0", text_color="#000",
                         corner_radius=8, font=F(13, "bold"), **kw)


def clean_name(name):
    return "".join(c for c in (name or "") if c not in '\\/:*?"<>|').strip()


def ask_name(parent, title):
    d = ctk.CTkInputDialog(title=title, text="Nome da macro:", fg_color=BG, button_fg_color=WHITE,
                           button_hover_color="#d9dbe0", button_text_color="#000", entry_fg_color=FIELD,
                           entry_border_color=BORDER, font=F(13))
    set_icon(d)
    return clean_name(d.get_input())


def tree_style(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("Dark.Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, rowheight=32,
                 borderwidth=0, font=(FONT, 11))
    st.configure("Dark.Treeview.Heading", background=CARD, foreground=MUTED, relief="flat", borderwidth=0,
                 font=(FONT, 10, "bold"), padding=8)
    st.map("Dark.Treeview", background=[("selected", WHITE)], foreground=[("selected", "#000")])
    st.map("Dark.Treeview.Heading", background=[("active", CARD)])
    st.layout("Dark.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.configure("Dark.Vertical.TScrollbar", background=FIELD, troughcolor=CARD, bordercolor=CARD,
                 arrowcolor=MUTED, lightcolor=FIELD, darkcolor=FIELD)


def macro_meta(m):
    keys = sum(1 for e in m.get("events", []) if e["k"] == "b" and e["v"] == 1)
    return f"{m.get('length', 0):.1f}s  ·  {keys} teclas"


def sequence_text(m, limit=24):
    seq = [LABEL.get(e["n"], e["n"]) for e in m["events"] if e["k"] == "b" and e["v"] == 1]
    return "  ".join(seq[:limit]) + ("  …" if len(seq) > limit else "")


# ---------------------------------------------------------------------------
# Editor de tempos
# ---------------------------------------------------------------------------
class Editor(ctk.CTkToplevel):
    def __init__(self, app, macro, name):
        super().__init__(app.root, fg_color=BG)
        self.app = app
        self.m = copy.deepcopy(macro)
        self.name = name
        self.title("Editar macro")
        self.geometry("980x720")
        self.minsize(900, 680)
        set_icon(self)
        self.transient(app.root)
        self.after(150, self.lift)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 10))
        self.lbl_title = ctk.CTkLabel(head, text="", font=F(20, "bold"), text_color=FG)
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="", font=F(12), text_color=MUTED)
        self.lbl_info.pack(side="left", padx=14)

        tc = card(self)
        tc.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=(0, 20))
        cols = ("n", "botao", "pausa", "segurar", "inicio")
        wrap = ctk.CTkFrame(tc, fg_color=FIELD, corner_radius=10)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        self.tv = ttk.Treeview(wrap, columns=cols, show="headings", style="Dark.Treeview", selectmode="browse")
        for c, t, w in zip(cols, ("#", "Botão", "Pausa antes (s)", "Segurar (s)", "Começa em (s)"),
                           (44, 110, 130, 110, 120)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="center")
        sb = ctk.CTkScrollbar(wrap, command=self.tv.yview, fg_color=FIELD, button_color=BORDER,
                              button_hover_color=HOVER)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="left", fill="y", pady=6)
        self.tv.bind("<<TreeviewSelect>>", lambda e: self._fill())

        side = ctk.CTkFrame(self, fg_color="transparent", width=320)
        side.grid(row=1, column=1, sticky="ns", padx=(8, 20), pady=(0, 20))

        # botoes de salvar primeiro, presos embaixo: nunca somem mesmo com a janela baixa
        bt = ctk.CTkFrame(side, fg_color="transparent"); bt.pack(fill="x", side="bottom")
        solid(bt, "Salvar", lambda: self.save(False), height=42).pack(fill="x")
        b3 = ctk.CTkFrame(bt, fg_color="transparent"); b3.pack(fill="x", pady=(8, 0))
        ghost(b3, "Salvar como…", lambda: self.save(True)).pack(side="left", expand=True, fill="x")
        ghost(b3, "Fechar", self.destroy).pack(side="left", expand=True, fill="x", padx=(8, 0))

        s1 = card(side); s1.pack(fill="x")
        ctk.CTkLabel(s1, text="Tecla selecionada", font=F(14, "bold"), text_color=FG).pack(anchor="w", padx=16, pady=(14, 8))
        self.v_pause, self.v_hold = tk.StringVar(), tk.StringVar()
        g = ctk.CTkFrame(s1, fg_color="transparent"); g.pack(fill="x", padx=16)
        for i, (t, v) in enumerate((("Pausa antes (s)", self.v_pause), ("Segurar (s)", self.v_hold))):
            ctk.CTkLabel(g, text=t, font=F(12), text_color=MUTED).grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else 10, 0))
            entry(g, v, 120).grid(row=1, column=i, sticky="w", padx=(0 if i == 0 else 10, 0), pady=(2, 0))
        b = ctk.CTkFrame(s1, fg_color="transparent"); b.pack(fill="x", padx=16, pady=(12, 0))
        solid(b, "Aplicar", self.apply_one).pack(side="left", expand=True, fill="x")
        ghost(b, "Apagar tecla", self.delete, color=RED).pack(side="left", expand=True, fill="x", padx=(8, 0))
        b2 = ctk.CTkFrame(s1, fg_color="transparent"); b2.pack(fill="x", padx=16, pady=(8, 16))
        ghost(b2, "Pausa em todas", self.pause_all).pack(side="left", expand=True, fill="x")
        ghost(b2, "Segurar em todas", self.hold_all).pack(side="left", expand=True, fill="x", padx=(8, 0))

        s2 = card(side); s2.pack(fill="x", pady=12)
        ctk.CTkLabel(s2, text="Adicionar tecla no fim", font=F(14, "bold"), text_color=FG).pack(anchor="w", padx=16, pady=(14, 8))
        keys = [k for k in LABEL if k not in ("lx", "ly", "rx", "ry", "l2", "r2", "mute")]
        self._opts = {f"{LABEL[k]}   ({k})": k for k in keys}
        self.opt = ctk.CTkOptionMenu(s2, values=list(self._opts), fg_color=FIELD, button_color=BORDER,
                                     button_hover_color=HOVER, dropdown_fg_color=FIELD, dropdown_hover_color=HOVER,
                                     font=F(13), dropdown_font=F(13), height=34, corner_radius=8)
        self.opt.pack(fill="x", padx=16)
        self.v_add_pause, self.v_add_hold = tk.StringVar(value="0.2"), tk.StringVar(value="0.1")
        g2 = ctk.CTkFrame(s2, fg_color="transparent"); g2.pack(fill="x", padx=16, pady=(8, 0))
        for i, (t, v) in enumerate((("Pausa antes", self.v_add_pause), ("Segurar", self.v_add_hold))):
            ctk.CTkLabel(g2, text=t, font=F(12), text_color=MUTED).grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else 10, 0))
            entry(g2, v, 120).grid(row=1, column=i, sticky="w", padx=(0 if i == 0 else 10, 0), pady=(2, 0))
        ghost(s2, "Adicionar", self.add).pack(fill="x", padx=16, pady=(12, 16))

        s3 = card(side); s3.pack(fill="x")
        r3 = ctk.CTkFrame(s3, fg_color="transparent"); r3.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(r3, text="Pausa no fim (s)", font=F(13), text_color=FG).pack(side="left")
        self.v_tail = tk.StringVar()
        ghost(r3, "Aplicar", self.apply_tail, width=80).pack(side="right")
        entry(r3, self.v_tail, 80).pack(side="right", padx=8)
        self.refresh()

    def _num(self, var, label):
        try:
            return float(var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Editar", f"'{label}' precisa ser um número em segundos. Ex.: 0.15", parent=self)
            return None

    def _sel(self):
        s = self.tv.selection()
        return self.tv.index(s[0]) if s else None

    def refresh(self, keep=None):
        self.lbl_title.configure(text=self.name or "Macro não salva")
        self.tv.delete(*self.tv.get_children())
        rows = steps_of(self.m)
        for i, r in enumerate(rows):
            self.tv.insert("", "end", values=(i + 1, LABEL.get(r["n"], r["n"]), f"{step_pause(rows, i):.3f}",
                                              f"{step_hold(r):.3f}", f"{r['on']['t']:.3f}"))
        analog = sum(1 for e in self.m["events"] if e["k"] == "a")
        info = f"{len(rows)} teclas  ·  {self.m['length']:.2f}s no total"
        if analog:
            info += f"  ·  {analog} movimentos de analógico/gatilho acompanham os tempos"
        self.lbl_info.configure(text=info)
        self.v_tail.set(f"{final_pause(self.m):.3f}")
        if keep is not None and rows:
            k = self.tv.get_children()[min(keep, len(rows) - 1)]
            self.tv.selection_set(k)
            self.tv.see(k)

    def _fill(self):
        i = self._sel()
        if i is None:
            return
        rows = steps_of(self.m)
        self.v_pause.set(f"{step_pause(rows, i):.3f}")
        self.v_hold.set(f"{step_hold(rows[i]):.3f}")

    def apply_one(self):
        i = self._sel()
        if i is None:
            return
        p, h = self._num(self.v_pause, "Pausa antes"), self._num(self.v_hold, "Segurar")
        if p is None or h is None:
            return
        set_hold(self.m, i, h)
        set_pause(self.m, i, p)
        self.refresh(i)

    def pause_all(self):
        p = self._num(self.v_pause, "Pausa antes")
        if p is None:
            return
        for i in range(1, len(steps_of(self.m))):
            set_pause(self.m, i, p)
        self.refresh(self._sel())

    def hold_all(self):
        h = self._num(self.v_hold, "Segurar")
        if h is None:
            return
        for i in range(len(steps_of(self.m))):
            set_hold(self.m, i, h)
        self.refresh(self._sel())

    def delete(self):
        i = self._sel()
        if i is None:
            return
        delete_step(self.m, i)
        self.refresh(i)

    def add(self):
        p, h = self._num(self.v_add_pause, "Pausa antes"), self._num(self.v_add_hold, "Segurar")
        if p is None or h is None:
            return
        add_step(self.m, self._opts[self.opt.get()], p, h)
        self.refresh(len(steps_of(self.m)) - 1)

    def apply_tail(self):
        t = self._num(self.v_tail, "Pausa no fim")
        if t is None:
            return
        _fix_length(self.m, t)
        self.refresh(self._sel())

    def save(self, as_new):
        if not self.m["events"]:
            messagebox.showinfo("Salvar", "A macro está vazia.", parent=self)
            return
        name = self.name
        if as_new or not name:
            name = ask_name(self, "Salvar macro")
            if not name:
                return
            if os.path.exists(os.path.join(MACROS_DIR, name + ".json")) and name != self.name:
                if not messagebox.askyesno("Salvar", f"Já existe '{name}'. Substituir?", parent=self):
                    return
        self.m["events"].sort(key=lambda e: e["t"])
        with open(os.path.join(MACROS_DIR, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(self.m, f)
        self.name = name
        self.app.macro, self.app.macro_name = copy.deepcopy(self.m), name
        self.app._refresh_list()
        self.app._show_macro()
        self.app.log(f"Macro '{name}' salva pelo editor.")
        self.refresh(self._sel())


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.reader = InputReader(self.q)
        self.reader.start()
        self.pad = None
        self.pad_tipo = None
        self.macro = None
        self.macro_name = None
        self.play_thread = None
        self.stop_evt = threading.Event()
        self.items = {}

        s = self._load_settings()
        self.v_speed = tk.DoubleVar(value=s.get("speed", 1.0))
        self.v_reps = tk.StringVar(value=str(s.get("reps", 1)))
        self.v_max = tk.StringVar(value=f"{s.get('max_secs', 0):g}")
        self.v_pause = tk.StringVar(value=f"{s.get('pause', 0.5):g}")
        self.tipo = s.get("tipo", "ds4")
        self.v_first = tk.BooleanVar(value=s.get("first_input_start", True))
        self.v_human = tk.BooleanVar(value=s.get("human", False))
        self.v_hum_lo = tk.StringVar(value=str(s.get("human_lo_ms", 30)))
        self.v_hum_hi = tk.StringVar(value=str(s.get("human_hi_ms", 60)))

        root.title("Macro Controle")
        root.geometry("1040x700")
        root.minsize(960, 660)
        root.configure(fg_color=BG)
        tree_style(root)
        self._build()
        self._refresh_list()
        self._hotkeys()
        root.after(30, self._poll)
        root.protocol("WM_DELETE_WINDOW", self._close)
        last = s.get("last_macro")
        if last and last in self.items:
            self._select(last)
        if VG_ERRO:
            self.log("Controle virtual indisponível: " + VG_ERRO)

    # ----- layout -----
    def _build(self):
        r = self.root
        r.grid_columnconfigure((0, 1), weight=1, uniform="col")
        r.grid_rowconfigure(1, weight=1)

        hd = ctk.CTkFrame(r, fg_color="transparent")
        hd.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 14))
        try:
            img = ctk.CTkImage(Image.open(resource("icone.png")), size=(48, 48))
            ctk.CTkLabel(hd, image=img, text="").pack(side="left")
        except Exception:
            pass
        tt = ctk.CTkFrame(hd, fg_color="transparent"); tt.pack(side="left", padx=14)
        ctk.CTkLabel(tt, text="MACRO CONTROLE", font=F(24, "bold"), text_color=FG).pack(anchor="w")
        self.lbl_dev = ctk.CTkLabel(tt, text="●  Procurando controles…", font=F(12), text_color=MUTED)
        self.lbl_dev.pack(anchor="w")
        for t in ("F8   Executar", "F9   Gravar"):
            ctk.CTkLabel(hd, text=f"  {t}  ", font=F(12), text_color=MUTED, fg_color=FIELD, corner_radius=8,
                         height=30).pack(side="right", padx=(8, 0))

        # ----- coluna da esquerda: gravar + macros
        left = ctk.CTkFrame(r, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=(0, 24))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        rc = card(left); rc.grid(row=0, column=0, sticky="ew")
        self.btn_rec = ctk.CTkButton(rc, text="●   GRAVAR", fg_color=RED, hover_color=RED_H, height=50,
                                     corner_radius=10, font=F(15, "bold"), command=self.toggle_record)
        self.btn_rec.pack(fill="x", padx=16, pady=(16, 10))
        ctk.CTkSwitch(rc, text="Começar a contar no primeiro botão", variable=self.v_first, font=F(12),
                      text_color=MUTED, progress_color=GREEN, button_color=WHITE, button_hover_color="#d9dbe0",
                      fg_color=BORDER).pack(anchor="w", padx=16)
        self.lbl_rec = ctk.CTkLabel(rc, text="Aperte GRAVAR, faça a sequência no controle e aperte de novo.",
                                    font=F(12), text_color=MUTED, wraplength=430, justify="left")
        self.lbl_rec.pack(anchor="w", padx=16, pady=(6, 14))

        mc = card(left); mc.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        mh = ctk.CTkFrame(mc, fg_color="transparent"); mh.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(mh, text="Macros", font=F(16, "bold"), text_color=FG).pack(side="left")
        self.lbl_count = ctk.CTkLabel(mh, text="", font=F(12), text_color=MUTED)
        self.lbl_count.pack(side="left", padx=8)
        ghost(mh, "Abrir pasta", lambda: os.startfile(MACROS_DIR), width=96, height=30).pack(side="right")
        self.list = ctk.CTkScrollableFrame(mc, fg_color=FIELD, corner_radius=10, scrollbar_button_color=BORDER,
                                           scrollbar_button_hover_color=HOVER)
        self.list.pack(fill="both", expand=True, padx=16)
        self.lbl_seq = ctk.CTkLabel(mc, text="Escolha uma macro na lista.", font=F(12), text_color=MUTED,
                                    wraplength=430, justify="left")
        self.lbl_seq.pack(anchor="w", padx=16, pady=(10, 8))
        bb = ctk.CTkFrame(mc, fg_color="transparent"); bb.pack(fill="x", padx=16, pady=(0, 16))
        bb.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="bb")
        for i, w in enumerate((solid(bb, "Editar tempos", self.edit_macro, width=20),
                               ghost(bb, "Salvar como", self.save_macro, width=20),
                               ghost(bb, "Renomear", self.rename_macro, width=20),
                               ghost(bb, "Apagar", self.delete_macro, color=RED, width=20))):
            w.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))

        # ----- coluna da direita: execucao
        rt = card(r)
        rt.grid(row=1, column=1, sticky="nsew", padx=(10, 24), pady=(0, 24))
        ctk.CTkLabel(rt, text="Execução", font=F(16, "bold"), text_color=FG).pack(anchor="w", padx=20, pady=(16, 10))

        sp = ctk.CTkFrame(rt, fg_color="transparent"); sp.pack(fill="x", padx=20)
        ctk.CTkLabel(sp, text="Velocidade", font=F(13), text_color=FG).pack(side="left")
        self.lbl_speed = ctk.CTkLabel(sp, text="", font=F(13, "bold"), text_color=FG)
        self.lbl_speed.pack(side="right")
        ctk.CTkSlider(rt, from_=0.25, to=4.0, number_of_steps=15, variable=self.v_speed, command=self._speed_lbl,
                      progress_color=WHITE, button_color=WHITE, button_hover_color="#d9dbe0", fg_color=FIELD,
                      height=18).pack(fill="x", padx=20, pady=(6, 14))
        self._speed_lbl(self.v_speed.get())

        g = ctk.CTkFrame(rt, fg_color="transparent"); g.pack(fill="x", padx=20)
        g.grid_columnconfigure((0, 1, 2), weight=1, uniform="b")
        for i, (t, v, hint) in enumerate((("Repetições", self.v_reps, "0 = sem fim"),
                                          ("Duração máx. (s)", self.v_max, "0 = sem limite"),
                                          ("Pausa entre (s)", self.v_pause, "entre repetições"))):
            bx = ctk.CTkFrame(g, fg_color=FIELD, corner_radius=10)
            bx.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            ctk.CTkLabel(bx, text=t, font=F(12), text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkEntry(bx, textvariable=v, height=34, fg_color=CARD, border_color=BORDER, corner_radius=8,
                         font=F(15, "bold"), justify="center", text_color=FG).pack(fill="x", padx=12)
            ctk.CTkLabel(bx, text=hint, font=F(11), text_color=MUTED).pack(anchor="w", padx=12, pady=(2, 10))

        ctk.CTkLabel(rt, text="Controle virtual", font=F(13), text_color=FG).pack(anchor="w", padx=20, pady=(16, 6))
        self.seg = ctk.CTkSegmentedButton(rt, values=["PlayStation", "Xbox"], command=self._tipo, height=36,
                                          font=F(13), fg_color=FIELD, selected_color="#3a3f4a",
                                          selected_hover_color="#444a56", unselected_color=FIELD,
                                          unselected_hover_color=HOVER, corner_radius=8)
        self.seg.pack(fill="x", padx=20)
        self.seg.set("PlayStation" if self.tipo == "ds4" else "Xbox")

        hm = ctk.CTkFrame(rt, fg_color=FIELD, corner_radius=10); hm.pack(fill="x", padx=20, pady=(16, 0))
        h1 = ctk.CTkFrame(hm, fg_color="transparent"); h1.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(h1, text="Modo humano", font=F(13, "bold"), text_color=FG).pack(side="left")
        ctk.CTkSwitch(h1, text="", variable=self.v_human, width=44, progress_color=GREEN, button_color=WHITE,
                      button_hover_color="#d9dbe0", fg_color=BORDER).pack(side="right")
        ctk.CTkLabel(hm, text="Cada tecla e pausa sai com um atraso aleatório diferente a cada repetição.",
                     font=F(11), text_color=MUTED, wraplength=420, justify="left").pack(anchor="w", padx=14)
        h2 = ctk.CTkFrame(hm, fg_color="transparent"); h2.pack(fill="x", padx=14, pady=(8, 12))
        ctk.CTkLabel(h2, text="Mais rápido até", font=F(12), text_color=MUTED).pack(side="left")
        ctk.CTkEntry(h2, textvariable=self.v_hum_lo, width=56, height=30, fg_color=CARD, border_color=BORDER,
                     corner_radius=8, justify="center", font=F(13)).pack(side="left", padx=6)
        ctk.CTkLabel(h2, text="ms     Mais lento até", font=F(12), text_color=MUTED).pack(side="left")
        ctk.CTkEntry(h2, textvariable=self.v_hum_hi, width=56, height=30, fg_color=CARD, border_color=BORDER,
                     corner_radius=8, justify="center", font=F(13)).pack(side="left", padx=6)
        ctk.CTkLabel(h2, text="ms", font=F(12), text_color=MUTED).pack(side="left")

        self.btn_play = ctk.CTkButton(rt, text="▶   EXECUTAR", fg_color=GREEN, hover_color=GREEN_H, height=58,
                                      corner_radius=12, font=F(17, "bold"), command=self.toggle_play)
        self.btn_play.pack(fill="x", padx=20, pady=(18, 6))
        self.lbl_run = ctk.CTkLabel(rt, text="Parado.", font=F(12), text_color=MUTED)
        self.lbl_run.pack(anchor="w", padx=20)
        self.txt = ctk.CTkTextbox(rt, height=80, fg_color=FIELD, text_color=MUTED, font=("Consolas", 11),
                                  corner_radius=10, border_width=0)
        self.txt.pack(fill="both", expand=True, padx=20, pady=(6, 18))
        self.txt.configure(state="disabled")

    def _speed_lbl(self, v):
        v = round(float(v) * 4) / 4
        self.lbl_speed.configure(text=f"{v:.2f}x")

    def _tipo(self, v):
        self.tipo = "ds4" if v == "PlayStation" else "x360"

    def log(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", time.strftime("%H:%M:%S  ") + msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    # ----- atalhos -----
    def _hotkeys(self):
        if keyboard is None:
            self.log("Atalhos F8/F9 indisponíveis. Use os botões.")
            return
        keyboard.add_hotkey("f9", lambda: self.q.put(("hotkey", "rec")))
        keyboard.add_hotkey("f8", lambda: self.q.put(("hotkey", "play")))

    # ----- mensagens das threads -----
    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                kind = m[0]
                if kind == "devices":
                    names = m[1]
                    if names:
                        self.lbl_dev.configure(text="●  " + "  ·  ".join(names), text_color=GREEN)
                    else:
                        self.lbl_dev.configure(text="●  Nenhum controle. Conecte o de PS5 por USB ou Bluetooth.",
                                               text_color=RED)
                elif kind == "rec_count":
                    self.lbl_rec.configure(text=f"Gravando…  {m[1]} ações capturadas.")
                elif kind == "log":
                    self.log(m[1])
                elif kind == "hotkey":
                    self.toggle_record() if m[1] == "rec" else self.toggle_play()
                elif kind == "run":
                    self.lbl_run.configure(text=f"Executando…  repetição {m[1]}")
                elif kind == "done":
                    self.reader.paused = False
                    self.btn_play.configure(text="▶   EXECUTAR", fg_color=GREEN, hover_color=GREEN_H)
                    self.lbl_run.configure(text=f"Parado.  {m[1]} repetição(ões) em {m[2]:.1f}s.")
                    self.log(f"Terminou: {m[1]} repetição(ões), {m[2]:.1f}s.")
        except queue.Empty:
            pass
        self.root.after(30, self._poll)

    # ----- gravacao -----
    def toggle_record(self):
        if self.play_thread and self.play_thread.is_alive():
            self.log("Pare a macro antes de gravar.")
            return
        if not self.reader.recording:
            self.reader.start_recording(self.v_first.get())
            self.btn_rec.configure(text="■   PARAR GRAVAÇÃO", fg_color="#8f2427", hover_color="#a3292c")
            self.lbl_rec.configure(text="Gravando…  faça a sequência no controle.")
            self.log("Gravação iniciada.")
            return
        m = self.reader.stop_recording()
        self.btn_rec.configure(text="●   GRAVAR", fg_color=RED, hover_color=RED_H)
        if not m["events"]:
            self.lbl_rec.configure(text="Nada foi gravado. Nenhum botão foi apertado.")
            return
        self.macro, self.macro_name = m, None
        self.lbl_rec.configure(text=f"Gravado: {len(m['events'])} ações em {m['length']:.2f}s.")
        self._show_macro()
        self._select_none()
        self.log("Gravação terminada.")
        self.save_macro()

    # ----- lista de macros -----
    def _refresh_list(self):
        for w in self.list.winfo_children():
            w.destroy()
        self.items = {}
        names = sorted(f[:-5] for f in os.listdir(MACROS_DIR) if f.endswith(".json"))
        for name in names:
            try:
                with open(os.path.join(MACROS_DIR, name + ".json"), encoding="utf-8") as f:
                    meta = macro_meta(json.load(f))
            except Exception:
                meta = "arquivo com problema"
            row = ctk.CTkFrame(self.list, fg_color="transparent", corner_radius=8, cursor="hand2")
            row.pack(fill="x", pady=2, padx=2)
            l1 = ctk.CTkLabel(row, text=name, font=F(14, "bold"), text_color=FG, anchor="w", cursor="hand2")
            l1.pack(fill="x", padx=12, pady=(8, 0))
            l2 = ctk.CTkLabel(row, text=meta, font=F(12), text_color=MUTED, anchor="w", cursor="hand2")
            l2.pack(fill="x", padx=12, pady=(0, 8))
            for w in (row, l1, l2):
                w.bind("<Button-1>", lambda e, n=name: self._select(n))
                w.bind("<Double-Button-1>", lambda e, n=name: (self._select(n), self.edit_macro()))
                w.bind("<Enter>", lambda e, n=name: self._hover(n, True))
                w.bind("<Leave>", lambda e, n=name: self._hover(n, False))
            self.items[name] = (row, l1, l2)
        self.lbl_count.configure(text=f"{len(names)} salva(s)")
        self._highlight()

    def _hover(self, name, on):
        if name != self.macro_name and name in self.items:
            self.items[name][0].configure(fg_color=HOVER if on else "transparent")

    def _highlight(self):
        for n, (row, l1, l2) in self.items.items():
            on = n == self.macro_name
            row.configure(fg_color=WHITE if on else "transparent")
            l1.configure(text_color="#000" if on else FG)
            l2.configure(text_color="#4a4f59" if on else MUTED)

    def _select_none(self):
        self.macro_name = None
        self._highlight()

    def _select(self, name):
        try:
            with open(os.path.join(MACROS_DIR, name + ".json"), encoding="utf-8") as f:
                self.macro = json.load(f)
            self.macro_name = name
            self._highlight()
            self._show_macro()
        except Exception as ex:
            messagebox.showerror("Erro", f"Não consegui abrir a macro: {ex}")

    def _show_macro(self):
        if not self.macro:
            self.lbl_seq.configure(text="Escolha uma macro na lista.")
            return
        nome = self.macro_name or "Gravação não salva"
        self.lbl_seq.configure(text=f"{nome}   ·   {macro_meta(self.macro)}\n{sequence_text(self.macro)}")

    def save_macro(self):
        if not self.macro:
            messagebox.showinfo("Salvar", "Grave uma macro primeiro.")
            return
        name = ask_name(self.root, "Salvar macro")
        if not name:
            self.log("Gravação ainda não salva. Use 'Salvar como' para guardar.")
            return
        path = os.path.join(MACROS_DIR, name + ".json")
        if os.path.exists(path) and name != self.macro_name:
            if not messagebox.askyesno("Salvar", f"Já existe uma macro chamada '{name}'. Substituir?"):
                return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.macro, f)
        self.macro_name = name
        self._refresh_list()
        self._show_macro()
        self.log(f"Macro '{name}' salva.")

    def edit_macro(self):
        if not self.macro or not self.macro.get("events"):
            messagebox.showinfo("Editar", "Escolha uma macro na lista ou grave uma primeiro.")
            return
        Editor(self, self.macro, self.macro_name)

    def rename_macro(self):
        old = self.macro_name
        if not old:
            messagebox.showinfo("Renomear", "Escolha uma macro salva na lista.")
            return
        new = ask_name(self.root, f"Renomear '{old}'")
        if not new or new == old:
            return
        if os.path.exists(os.path.join(MACROS_DIR, new + ".json")):
            messagebox.showerror("Renomear", f"Já existe uma macro chamada '{new}'.")
            return
        os.replace(os.path.join(MACROS_DIR, old + ".json"), os.path.join(MACROS_DIR, new + ".json"))
        self.macro_name = new
        self._refresh_list()
        self._show_macro()

    def delete_macro(self):
        name = self.macro_name
        if not name:
            messagebox.showinfo("Apagar", "Escolha uma macro salva na lista.")
            return
        if messagebox.askyesno("Apagar", f"Apagar a macro '{name}'?"):
            os.remove(os.path.join(MACROS_DIR, name + ".json"))
            self.macro, self.macro_name = None, None
            self._refresh_list()
            self._show_macro()

    # ----- execucao -----
    def _get_pad(self):
        if self.pad is None or self.pad_tipo != self.tipo:
            self.pad = None
            self.pad = VirtualPad(self.tipo)
            self.pad_tipo = self.tipo
            self.log("Controle virtual criado (" + ("PlayStation" if self.tipo == "ds4" else "Xbox") + ").")
            time.sleep(0.5)
        return self.pad

    def _nums(self):
        f = lambda v: float(v.get().replace(",", "."))
        return (max(0.25, float(self.v_speed.get())), max(0, int(f(self.v_reps))), max(0.0, f(self.v_max)),
                max(0.0, f(self.v_pause)), max(0, int(f(self.v_hum_lo))), max(0, int(f(self.v_hum_hi))))

    def toggle_play(self):
        if self.play_thread and self.play_thread.is_alive():
            self.stop_evt.set()
            self.lbl_run.configure(text="Parando…")
            return
        if self.reader.recording:
            self.log("Pare a gravação antes de executar.")
            return
        if not self.macro or not self.macro.get("events"):
            messagebox.showinfo("Executar", "Escolha uma macro na lista ou grave uma primeiro.")
            return
        try:
            speed, reps, max_secs, pause, lo, hi = self._nums()
        except ValueError:
            messagebox.showerror("Executar", "Confira os números das opções: use só números, como 2 ou 0.5.")
            return
        human = (-lo / 1000.0, hi / 1000.0) if self.v_human.get() else None
        if reps == 0 and max_secs == 0:
            self.log("Sem fim: aperte F8 para parar.")
        try:
            pad = self._get_pad()
        except Exception as ex:
            self._driver_missing(ex)
            return
        self._save_settings()
        self.stop_evt.clear()
        self.reader.paused = True
        self.btn_play.configure(text="■   PARAR", fg_color=RED, hover_color=RED_H)
        self.play_thread = threading.Thread(
            target=play_macro,
            args=(pad, copy.deepcopy(self.macro), speed, reps, max_secs, pause, self.stop_evt, self.q.put, human),
            daemon=True)
        self.play_thread.start()

    def _driver_missing(self, ex):
        msg = ("O controle virtual precisa de um driver (ViGEmBus) que ainda não está instalado neste PC."
               "\n\nInstalar agora? Depois de instalar, feche e abra o Macro Controle de novo.")
        if os.path.exists(DRIVER_MSI) and messagebox.askyesno("Instalar driver", msg):
            os.startfile(DRIVER_MSI)
        elif not os.path.exists(DRIVER_MSI):
            messagebox.showerror("Controle virtual", "Não consegui criar o controle virtual.\n\n" + str(ex))

    # ----- configuracoes -----
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self):
        try:
            speed, reps, max_secs, pause, lo, hi = self._nums()
        except ValueError:
            return
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"speed": speed, "reps": reps, "max_secs": max_secs, "pause": pause, "tipo": self.tipo,
                           "first_input_start": self.v_first.get(), "human": self.v_human.get(),
                           "human_lo_ms": lo, "human_hi_ms": hi, "last_macro": self.macro_name}, f)
        except Exception:
            pass

    def _close(self):
        self.stop_evt.set()
        try:
            self._save_settings()
            if self.pad:
                self.pad.neutral()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    try:  # texto nitido em telas com zoom e icone proprio na barra de tarefas
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("leko.macrocontrole")
    except Exception:
        pass
    root = ctk.CTk(fg_color=BG)
    set_icon(root)
    App(root)
    root.mainloop()
