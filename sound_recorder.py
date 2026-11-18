import os
import time
import json
import soundcard as sc
import soundfile as sf
import tkinter as tk
import customtkinter as ctk
import threading
import numpy as np
from types import SimpleNamespace
from datetime import datetime
from pydub import AudioSegment
from pydub.effects import normalize
import queue

# Global variables for monitoring and recording control
monitoring_event = threading.Event()
recording_event = threading.Event()
pause_event = threading.Event()
realtime_levels = np.array([0.0, 0.0])
input_source_id = None
data = None
backup_dir = None

def dict_to_namespace(data):
    """Convert a dictionary to a namespace."""
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = dict_to_namespace(value)
        return SimpleNamespace(**data)
    else:
        return data

SETTINGS = dict_to_namespace(json.load(open("settings.json", "r", encoding="utf-8")))
LANG = dict_to_namespace(json.load(open(f"{SETTINGS.gui.lang}.json", "r", encoding="utf-8")))

def convert_seconds(seconds):
    """Convert seconds to a formatted string (HH:MM:SS)."""
    seconds = int(seconds)
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def backup_data_every(interval, backup_dir):
    """Backup data periodically during recording."""
    t = 0
    while recording_event.is_set():
        time.sleep(1)
        t += 1
        if t >= interval:
            np.savez_compressed(f"{backup_dir}/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.npz", data)
            t = 0

def monitoring_mic(sc_id):
    """Monitor the microphone input levels."""
    with sc.get_microphone(id=sc_id, include_loopback=True).recorder(samplerate=SETTINGS.recording.sample_rate) as mic:
        while monitoring_event.is_set():
            realtime_levels = np.max(mic.record(), axis=0)

def record_from_mic(recording_frame):
    """Capture audio from the microphone and store it in 'data'."""
    global data
    with sc.get_microphone(id=input_source_id, include_loopback=True).recorder(samplerate=SETTINGS.recording.sample_rate) as mic:
        while recording_event.is_set():
            _data = mic.record(numframes=SETTINGS.recording.sample_rate)
            if not pause_event.is_set():
                if data is None:
                    data = _data
                else:
                    if is_silence_cut.get() and np.any(np.abs(_data) >= SETTINGS.recording.silence_threshold):
                        data = np.concatenate((data, _data))
                    else:
                        data = np.concatenate((data, _data))

                sec = data.shape[0] / SETTINGS.recording.sample_rate
                t = convert_seconds(sec)
                recording_frame.label_time.configure(text=f"[REC {t}]", text_color="#ff3333")
            else:
                recording_frame.label_time.configure(text=LANG.labels.RecordingFrame.text_pause, text_color="#888888")
        recording_frame.label_time.configure(text="00:00:00", text_color="#ffffff")

def update_levels(monitor_frame):
    """Update audio input levels on the GUI."""
    def boost(v):
        return np.log2(np.abs(v) + 1)

    while True:
        lvs = boost(boost(realtime_levels))
        r_ch = 0 if len(realtime_levels) == 1 else 1
        monitor_frame.progress_l.set(lvs[0])
        monitor_frame.progress_r.set(lvs[r_ch])
        time.sleep(1 / 30)

class EzSoundCaptureApp(ctk.CTk):
    """Main application window."""
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("EZ Sound Capture")
        self.fonts = (LANG.fonts.font, LANG.fonts.font_size)
        self.resizable(False, False)
        self.init_gui()
    
    def init_gui(self):
        """Initialize GUI components."""
        self.setting_frame = SettingFrame(self, header_name=LANG.labels.SettingFrame.header_name)
        self.setting_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.monitor_frame = MonitorFrame(self, header_name=LANG.labels.MonitorFrame.header_name)
        self.monitor_frame.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        self.recording_frame = RecordingFrame(self, header_name=LANG.labels.RecordingFrame.header_name)
        self.recording_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        threading.Thread(target=update_levels, args=(self.monitor_frame,), daemon=True).start()

class SettingFrame(ctk.CTkFrame):
    """Settings frame to configure recording options."""
    def __init__(self, *args, header_name=LANG.labels.SettingFrame.header_name, **kwargs):
        super().__init__(*args, **kwargs)
        self.fonts = (LANG.fonts.font, LANG.fonts.font_size)
        self.header_name = header_name
        self.init_vars()
        self.init_gui()
    
    def init_vars(self):
        """Initialize variables for settings."""
        self.input_source = tk.StringVar()
        self.int_mp3 = tk.IntVar(value=1)
        self.int_normalize = tk.IntVar(value=1)
        self.int_cut = tk.IntVar(value=1)

    def init_gui(self):
        """Setup GUI for settings."""
        self.label_input_source = ctk.CTkLabel(self, text=LANG.labels.SettingFrame.label_input_source, font=self.fonts)
        self.label_input_source.grid(row=0, column=0, padx=5, pady=5)
        microphones = sc.all_microphones(include_loopback=True)
        self.microphones_dict = {f"{str(mic).replace('<', '').split(' ')[0]} {mic.name}": mic for mic in microphones}
        self.input_source_combo = ctk.CTkComboBox(master=self, width=300, font=self.fonts, values=self.microphones_dict.keys(), state="readonly", command=self.set_input_source, variable=self.input_source)
        self.input_source_combo.grid(row=0, column=1, padx=5, pady=5, columnspan=3)
        self.set_default_microphone()

    def set_default_microphone(self):
        """Set the default microphone."""
        mic = sc.get_microphone(id=sc.default_speaker().id, include_loopback=True)
        key = f"{str(mic).replace('<', '').split(' ')[0]} {mic.name}"
        self.set_input_source(key)

    def set_input_source(self, key):
        """Set the selected input source (microphone)."""
        global input_source_id
        input_source_id = self.microphones_dict[key].id
        monitoring_event.set()

class MonitorFrame(ctk.CTkFrame):
    """Monitor frame for displaying audio levels."""
    def __init__(self, *args, header_name=LANG.labels.MonitorFrame.header_name, **kwargs):
        super().__init__(*args, **kwargs)
        self.fonts = (LANG.fonts.font, LANG.fonts.font_size)
        self.header_name = header_name
        self.init_gui()

    def init_gui(self):
        """Setup GUI for monitoring audio levels."""
        self.label_level = ctk.CTkLabel(self, text=LANG.labels.MonitorFrame.label_level, font=self.fonts)
        self.label_level.grid(row=0, column=0, padx=5, pady=5, rowspan=2)
        self.progress_l = ctk.CTkProgressBar(self, width=300, progress_color="#55ff33")
        self.progress_l.grid(row=0, column=1, padx=5, pady=1)
        self.progress_r = ctk.CTkProgressBar(self, width=300, progress_color="#55ff33")
        self.progress_r.grid(row=1, column=1, padx=5, pady=1)

class RecordingFrame(ctk.CTkFrame):
    """Recording control frame."""
    def __init__(self, *args, header_name=LANG.labels.RecordingFrame.header_name, **kwargs):
        super().__init__(*args, **kwargs)
        self.fonts = (LANG.fonts.font, LANG.fonts.font_size)
        self.header_name = header_name
        self.init_gui()

    def init_gui(self):
        """Setup GUI for recording control."""
        self.recording_button = ctk.CTkButton(
            master=self, width=50, height=50, font=self.fonts, border_width=0,
            text=LANG.labels.RecordingFrame.label_recording, command=self.start_recording, fg_color="#bb0000", hover_color="#ee0000")
        self.recording_button.grid(row=0, column=0, padx=5, pady=5)
        self.label_time = ctk.CTkLabel(self, text="00:00:00", width=200, font=self.fonts)
        self.label_time.grid(row=0, column=1, padx=5, pady=5)
        self.recording_pause_button = ctk.CTkButton(
            master=self, width=50, height=50, font=self.fonts, border_width=0,
            text=LANG.labels.RecordingFrame.label_recording_pause, command=self.pause_recording, fg_color="#222222", hover_color="#555555")
        self.recording_pause_button.grid(row=0, column=2, padx=5, pady=5)

    def start_recording(self):
        """Start or stop recording."""
        if not recording_event.is_set():
            recording_event.set()
            self.recording_button.configure(text=LANG.labels.RecordingFrame.label_stop)
            global backup_dir
            backup_dir = f"./recordings/{datetime.now().strftime('%Y%m%d_%H%M%S')}/"
            os.makedirs(backup_dir, exist_ok=True)
            threading.Thread(target=backup_data_every, args=(SETTINGS.recording.backup_interval, backup_dir), daemon=True).start()
            threading.Thread(target=record_from_mic, args=(self,), daemon=True).start()

    def pause_recording(self):
        """Pause or resume recording."""
        if not recording_event.is_set():
            pause_event.set()
        else:
            pause_event.clear()

def main():
    """Main application entry."""
    monitoring_event.set()
    app = EzSoundCaptureApp()
    app.mainloop()
    monitoring_event.clear()

if __name__ == "__main__":
    main()
