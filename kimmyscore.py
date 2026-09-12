from __future__ import annotations

import argparse
import queue
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

INPUT_BAUD = 19200
OUTPUT_BAUD = 115200
HEADER = b"\xA6\x10"
BLANK_FRAME = HEADER + b" " * 16
QUIET_SECONDS = 0.025
MAX_WAIT_SECONDS = 0.100
MIN_FRAME_SECONDS = 0.025
SCORE_VALUES = frozenset(b"0123456789-aehlp ")
OUTPUT_VALUES = frozenset(b"0123456789 ")

# Hypseus: P1[6], P2[6], P1 lives, P2 lives, credits[2].
# A1Up:    P1[6], P1 lives, P2[6], P2 lives, credits[2].
PAYLOAD_POSITION = (0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 6, 13, 14, 15)


class Translator:
    def __init__(self):
        self.frame = bytearray(BLANK_FRAME)
        self.last_sent = None
        self.last_sent_at = -float("inf")
        self.buffer = bytearray()
        self.dirty = False
        self.first_change = 0.0
        self.last_change = 0.0
        self.packets = 0
        self.changes = 0
        self.duplicates = 0
        self.symbol_blanks = 0
        self.annunciators = 0
        self.resync_bytes = 0

    @staticmethod
    def plausible(unit, digit, value):
        if unit == 0:
            return digit < 16 and value in SCORE_VALUES
        if unit == 1:
            return value in (0, 1, 2, 4)
        return False

    def feed(self, incoming: bytes, now: float):
        self.buffer.extend(incoming)
        cursor = 0
        while len(self.buffer) - cursor >= 3:
            unit, digit, value = self.buffer[cursor:cursor + 3]
            if not self.plausible(unit, digit, value):
                # Best effort only: the upstream protocol has no marker/checksum.
                cursor += 1
                self.resync_bytes += 1
                continue
            cursor += 3
            self.packets += 1
            if unit == 1:
                self.annunciators += 1
                continue
            if value not in OUTPUT_VALUES:
                value = 0x20
                self.symbol_blanks += 1
            position = 2 + PAYLOAD_POSITION[digit]
            if self.frame[position] == value:
                self.duplicates += 1
                continue
            self.frame[position] = value
            self.changes += 1
            if self.frame == self.last_sent:
                self.dirty = False
                continue
            if not self.dirty:
                self.first_change = now
            self.dirty = True
            self.last_change = now
        del self.buffer[:cursor]

    def due(self, now: float):
        if not self.dirty or now - self.last_sent_at < MIN_FRAME_SECONDS:
            return None
        if now - self.last_change >= QUIET_SECONDS or now - self.first_change >= MAX_WAIT_SECONDS:
            return bytes(self.frame)
        return None

    def sent(self, packet: bytes, now: float):
        self.last_sent = bytes(packet)
        self.last_sent_at = now
        self.dirty = self.frame != packet


def open_serial(name: str, baud: int, timeout: float, input_side=False):
    if serial is None:
        raise RuntimeError("Install pyserial first: py -m pip install pyserial")
    port = serial.Serial(port=None, baudrate=baud, bytesize=8, parity="N", stopbits=1,
                         timeout=timeout, write_timeout=0.35, xonxoff=False,
                         rtscts=False, dsrdtr=False)
    port.dtr = input_side
    port.rts = input_side
    port.port = name
    port.open()
    return port


def write_frame(port, packet: bytes):
    if len(packet) != 18 or packet[:2] != HEADER or any(value not in OUTPUT_VALUES for value in packet[2:]):
        raise ValueError("Invalid A1Up digit/blank frame.")
    deadline = time.monotonic() + 0.5
    offset = 0
    while offset < len(packet):
        written = port.write(packet[offset:])
        if not written or written < 0:
            raise OSError("The CP2102 accepted no bytes.")
        offset += written
        if time.monotonic() > deadline:
            raise TimeoutError("CP2102 write timed out.")
    # Bounded draining instead of an unbounded flush(). Queue completion does
    # not prove that U1 received or displayed the frame.
    while port.out_waiting:
        if time.monotonic() > deadline:
            raise TimeoutError("CP2102 output queue did not drain.")
        time.sleep(0.001)


def run_bridge(input_name: str, output_name: str, stop: threading.Event,
               emit, opener=open_serial):
    source = destination = None
    translator = Translator()
    frames_sent = 0
    error = None
    try:
        if not input_name or not output_name or input_name.upper() == output_name.upper():
            raise ValueError("Choose two different serial ports: virtual input and CP2102 output.")
        destination = opener(output_name, OUTPUT_BAUD, 0, False)
        source = opener(input_name, INPUT_BAUD, 0.005, True)
        write_frame(destination, BLANK_FRAME)
        translator.sent(BLANK_FRAME, time.monotonic())
        frames_sent += 1
        emit("frame", ("Startup blank", BLANK_FRAME))
        emit("running", None)
        next_stats = time.monotonic()

        while not stop.is_set():
            incoming = source.read(max(1, min(source.in_waiting or 1, 1024)))
            if stop.is_set():
                break
            now = time.monotonic()
            if incoming:
                translator.feed(incoming, now)
            packet = translator.due(now)
            if packet is not None:
                write_frame(destination, packet)
                translator.sent(packet, time.monotonic())
                frames_sent += 1
                emit("frame", ("Batched update", packet))
            if now >= next_stats:
                emit("stats", (translator.packets, frames_sent, translator.duplicates,
                               translator.symbol_blanks, translator.resync_bytes))
                next_stats = now + 0.25
    except Exception as exc:
        error = str(exc)
    finally:
        # Discard pending changes and leave the physical display blank on Stop,
        # window close, or a read error. Do not resend an already blank state.
        if destination is not None:
            try:
                if translator.last_sent != BLANK_FRAME or error is not None:
                    write_frame(destination, BLANK_FRAME)
                    emit("frame", ("Stop blank", BLANK_FRAME))
            except Exception as exc:
                detail = "Could not blank the scoreboard: " + str(exc)
                error = f"{error}; {detail}" if error else detail
        for port in (source, destination):
            if port is not None:
                try:
                    port.close()
                except Exception as exc:
                    error = f"{error}; {exc}" if error else str(exc)
        emit("stopped", error)


def make_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    class App:
        def __init__(self, root):
            self.root = root
            self.events = queue.Queue()
            self.worker = None
            self.stop_event = threading.Event()
            self.closing = False
            self.input_var = tk.StringVar(value="COM5")
            self.output_var = tk.StringVar(value="COM3")
            self.status = tk.StringVar(value="Stopped")
            self.stats = tk.StringVar(value="Waiting for Hypseus")
            self.display = tk.StringVar(value="P1: [      ]  Lives: [ ]    P2: [      ]  Lives: [ ]    Credits: [  ]")
            self.build()
            self.refresh()
            root.after(75, self.poll)
            root.protocol("WM_DELETE_WINDOW", self.close)
            root.after_idle(self.start)

        def build(self):
            self.root.title("Hypseus to A1Up - Bridge")
            self.root.geometry("870x490")
            self.root.minsize(780, 440)
            box = ttk.Frame(self.root, padding=12)
            box.pack(fill="both", expand=True)
            ttk.Label(box, text="Hypseus to Arcade1Up", font=("Segoe UI", 15, "bold")).pack(anchor="w")
            ttk.Label(box, text="Game digits pass unchanged. "
                      "Letters/dashes become spaces.", wraplength=820).pack(anchor="w", pady=(4, 10))
            ports = ttk.Frame(box)
            ports.pack(fill="x", pady=4)
            ttk.Label(ports, text="Virtual input (19200)").pack(side="left")
            self.input_box = ttk.Combobox(ports, textvariable=self.input_var, width=11)
            self.input_box.pack(side="left", padx=(6, 20))
            ttk.Label(ports, text="CP2102 output (115200)").pack(side="left")
            self.output_box = ttk.Combobox(ports, textvariable=self.output_var, width=11)
            self.output_box.pack(side="left", padx=6)
            self.refresh_button = ttk.Button(ports, text="Refresh", command=self.refresh)
            self.refresh_button.pack(side="left", padx=6)
            ttk.Label(box, text="Default layout: Hypseus uses COM4; paired COM5 is the bridge input; CP2102 is COM3.\n"
                      "Open before Hypseus. Game launch options:",
                      wraplength=820).pack(anchor="w", pady=(10, 4))
            command = ttk.Entry(box, font=("Consolas", 11))
            command.insert(0, "-usbscoreboard COM 4 19200")
            command.configure(state="readonly")
            command.pack(fill="x", pady=(0, 10))
            buttons = ttk.Frame(box)
            buttons.pack(fill="x", pady=4)
            self.start_button = ttk.Button(buttons, text="Start bridge", command=self.start)
            self.start_button.pack(side="left", padx=(0, 7))
            self.stop_button = ttk.Button(buttons, text="Stop & blank", command=self.stop, state="disabled")
            self.stop_button.pack(side="left")
            ttk.Label(buttons, textvariable=self.status).pack(side="right")
            ttk.Label(box, textvariable=self.display, font=("Consolas", 10), wraplength=820).pack(anchor="w", pady=8)
            ttk.Label(box, textvariable=self.stats, wraplength=820).pack(anchor="w", pady=(0, 6))
            self.log_box = ScrolledText(box, height=8, state="disabled", wrap="word", font=("Consolas", 9))
            self.log_box.pack(fill="both", expand=True)

        def refresh(self):
            names = [port.device for port in list_ports.comports()] if list_ports else []
            self.input_box["values"] = names or ("COM5",)
            self.output_box["values"] = names or ("COM3",)

        def log(self, message):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", time.strftime("%H:%M:%S ") + message + "\n")
            if int(self.log_box.index("end-1c").split(".")[0]) > 800:
                self.log_box.delete("1.0", "201.0")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        def start(self):
            if self.closing or (self.worker is not None and self.worker.is_alive()):
                return
            if serial is None:
                messagebox.showerror("pyserial required", "Run: py -m pip install pyserial", parent=self.root)
                return
            input_name, output_name = self.input_var.get().strip(), self.output_var.get().strip()
            if not input_name or not output_name or input_name.upper() == output_name.upper():
                messagebox.showerror("Ports", "Choose different input and output ports.", parent=self.root)
                return
            self.stop_event = threading.Event()
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.input_box.configure(state="disabled")
            self.output_box.configure(state="disabled")
            self.refresh_button.configure(state="disabled")
            self.status.set("Starting...")
            self.stats.set("Waiting for Hypseus")
            self.worker = threading.Thread(target=run_bridge, args=(input_name, output_name, self.stop_event,
                                          lambda kind, value: self.events.put((kind, value))), daemon=True)
            self.worker.start()

        def stop(self):
            if self.worker is not None and self.worker.is_alive():
                self.status.set("Stopping...")
                self.stop_button.configure(state="disabled")
                self.stop_event.set()

        def poll(self):
            for _ in range(150):
                try:
                    kind, value = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "running":
                    self.status.set("Running")
                elif kind == "frame":
                    description, packet = value
                    text = packet[2:].decode("ascii")
                    self.display.set(f"P1: [{text[:6]}]  Lives: [{text[6]}]    P2: [{text[7:13]}]  "
                                     f"Lives: [{text[13]}]    Credits: [{text[14:]}]")
                    self.log(description + ": " + packet.hex(" ").upper())
                elif kind == "stats":
                    packets, frames, duplicates, symbols, resync = value
                    self.stats.set(f"Packets: {packets} | Frames: {frames} | Duplicate digits: {duplicates} | "
                                   f"Symbols blanked: {symbols} | Resync bytes: {resync}")
                elif kind == "stopped":
                    self.status.set("Error - see log" if value else "Stopped")
                    self.log("ERROR: " + value if value else "Stopped; serial ports closed.")
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.input_box.configure(state="normal")
                    self.output_box.configure(state="normal")
                    self.refresh_button.configure(state="normal")
            if self.closing and (self.worker is None or not self.worker.is_alive()):
                self.root.destroy()
                return
            self.root.after(75, self.poll)

        def close(self):
            self.closing = True
            self.start_button.configure(state="disabled")
            self.stop()

    root = tk.Tk()
    app = App(root)
    return root, app


def self_test():
    def updates(values):
        return b"".join(bytes((0, index, value)) for index, value in enumerate(values))

    translator = Translator()
    assert bytes(translator.frame) == BLANK_FRAME
    translator.sent(BLANK_FRAME, 0)
    # Digits, including genuine zero, retain the correct physical field order.
    data = updates(b"1234567890123456")
    for index in range(0, len(data), 2):
        translator.feed(data[index:index + 2], 0.010)
    expected = HEADER + b"123456" + b"3" + b"789012" + b"4" + b"56"
    assert translator.due(0.020) is None
    assert translator.due(0.036) == expected
    translator.sent(expected, 0.036)
    translator.feed(data, 0.050)
    assert translator.due(0.200) is None
    # Every unsupported stock symbol clears its position with 20, never 30.
    translator.feed(updates(b"-aehlp " * 2 + b"-a"), 0.250)
    assert translator.due(0.276) == BLANK_FRAME
    translator.sent(BLANK_FRAME, 0.276)
    # Changes returning to the last transmitted state create no output frame.
    translator.feed(bytes((0, 0, ord("8"))), 0.300)
    translator.feed(bytes((0, 0, ord(" "))), 0.310)
    assert translator.due(0.500) is None
    # Annunciators are consumed as three-byte packets. Noise is skipped.
    translator.feed(b"\xFF" + bytes((1, 7, 4, 0, 0, ord("0"))), 0.600)
    assert translator.annunciators == 1 and translator.resync_bytes == 1
    assert translator.due(0.626) == HEADER + b"0" + b" " * 15
    # Continuously changing data still reaches the output within the timer.
    translator = Translator()
    translator.sent(BLANK_FRAME, 0)
    for step, value in enumerate(b"123456"):
        translator.feed(bytes((0, 0, value)), 0.010 + step * 0.019)
    assert translator.due(0.111) == HEADER + b"6" + b" " * 15

    class FakeOutput:
        def __init__(self):
            self.out_waiting = 0
            self.frames = []
            self.closed = False

        def write(self, packet):
            self.frames.append(bytes(packet))
            return len(packet)

        def close(self):
            self.closed = True

    class FakeInput:
        def __init__(self):
            self.data = bytearray(updates(b"12 45678 0123456"))
            self.closed = False

        @property
        def in_waiting(self):
            return len(self.data)

        def read(self, size):
            if self.data:
                result = bytes(self.data[:size])
                del self.data[:size]
                return result
            time.sleep(0.005)
            return b""

        def close(self):
            self.closed = True

    stop = threading.Event()
    source, destination = FakeInput(), FakeOutput()
    errors = []

    def emit(kind, value):
        if kind == "frame" and value[0] == "Batched update":
            stop.set()
        if kind == "stopped" and value:
            errors.append(value)

    def open_fake(name, baud, timeout, input_side):
        return source if input_side else destination

    timer = threading.Timer(2, stop.set)
    timer.start()
    try:
        run_bridge("COM5", "COM3", stop, emit, open_fake)
    finally:
        timer.cancel()
    assert not errors and source.closed and destination.closed
    assert len(destination.frames) == 3
    assert destination.frames[0] == destination.frames[-1] == BLANK_FRAME
    assert destination.frames[1][2:] == b"12 456" + b"3" + b"78 012" + b"4" + b"56"
    print("PASS: blank initialization/stop, digit/blank mapping, fragmented input,")
    print("      annunciators, resynchronization, duplicate suppression, reverted changes,")
    print("      quiet/max-delay batching and full bridge lifecycle. Physical board not tested.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run offline bridge checks.")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        root, app = make_gui()
        root.mainloop()
