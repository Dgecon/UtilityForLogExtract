import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import re
import os

from datetime import datetime, date

MT_RE = re.compile(
    r"^(?P<inner_ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)"
    r"\s*\|\s*(?P<level>DEBUG|ERROR|INFO|WARN)"
    r"\s*\|\s*(?P<message>.+)$",
    re.IGNORECASE
)

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

def parse_outer_ts(raw_t: str) -> datetime | None:
    """
    Парсит внешнюю метку:
        2026-05-07 08:00:07.087+03:00
    """

    m = TS_RE.match(raw_t)

    if not m:
        return None

    try:
        frac = raw_t[len(m.group(1)):]
        frac_m = re.match(r"\.(\d+)", frac)

        ms = (
            int(frac_m.group(1)[:6].ljust(6, "0"))
            if frac_m
            else 0
        )

        base = datetime.strptime(
            m.group(1),
            "%Y-%m-%d %H:%M:%S"
        )

        return base.replace(microsecond=ms)

    except ValueError:
        return None


def parse_line(raw: str):
    """
    Парсит одну JSON-строку.
    Возвращает dict или None.
    """

    raw = raw.strip().rstrip("\r")

    if not raw.startswith("{"):
        return None

    try:
        obj = json.loads(raw)

    except json.JSONDecodeError:
        return None

    lg = obj.get("lg", "")
    mt = obj.get("mt", "")

    if not mt:
        return None

    # формат с внутренним timestamp
    m = MT_RE.match(mt.strip())

    if m:
        try:
            ts = datetime.strptime(
                m.group("inner_ts"),
                "%Y-%m-%d %H:%M:%S.%f"
            )

        except ValueError:
            return None

        return {
            "ts": ts,
            "level": m.group("level").upper(),
            "message": m.group("message").strip(),
            "logger": lg,
        }

    # fallback — внешний timestamp
    outer_ts = parse_outer_ts(obj.get("t", ""))

    if outer_ts is None:
        return None

    raw_level = obj.get("l", "").upper()

    level_map = {
        "DEBUG": "DEBUG",
        "INFO": "INFO",
        "ERROR": "ERROR",
        "WARN": "WARN",
        "WARNING": "WARN",
        "TRACE": "DEBUG"
    }

    level = level_map.get(raw_level)

    if not level:
        return None

    return {
        "ts": outer_ts,
        "level": level,
        "message": mt.strip(),
        "logger": lg,
    }


def is_key_conversion_message(msg: str) -> bool:
    """
    Проверяет, относится ли сообщение к ключевым записям конвертации.
    """

    m = msg.lower()

    return (
        "запущена постановка в очередь конвертации писем в docx" in m
        or "найдено писем для постановки в очередь:" in m
        or "постановка в очередь завершена. всего" in m
        or m.startswith("convertonemail:")
    )


def sort_log_files(paths: list[str]) -> list[str]:
    """
    Сортировка rotated logs:

        *.0.log
        *.1.log
        *.2.log
        *.log   <- последний

    Пример:
        worker.2026-05-06.0.log
        worker.2026-05-06.1.log
        worker.2026-05-06.log
    """

    def extract_index(path: str):

        name = os.path.basename(path)

        # *.N.log
        m = re.search(r"\.(\d+)\.log$", name)

        if m:
            return int(m.group(1))

        # без индекса — основной файл
        return 10**9

    return sorted(paths, key=extract_index)


def extract_logs(
    filepaths: list[str],
    date_from: datetime,
    date_to: datetime,
    levels: set,
    only_converter: bool,
    only_key: bool
) -> list:

    results = []

    sorted_files = sort_log_files(filepaths)

    for filepath in sorted_files:

        with open(
            filepath,
            "r",
            encoding="utf-8",
            errors="replace"
        ) as f:

            for raw in f:

                entry = parse_line(raw)

                if entry is None:
                    continue

                if entry["level"] not in levels:
                    continue

                if only_converter and entry["logger"] != "Logger":
                    continue

                if only_key and not is_key_conversion_message(entry["message"]):
                    continue

                if date_from <= entry["ts"] <= date_to:
                    results.append(entry)

    # финальная хронологическая сортировка
    results.sort(key=lambda e: e["ts"])

    return results


def format_entry(entry: dict) -> str:

    ts_str = entry["ts"].strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]

    return (
        f"{ts_str} | "
        f"{entry['level']:<5} | "
        f"{entry['message']}"
    )


class LogExtractorApp(tk.Tk):

    def __init__(self):

        super().__init__()

        self.title("Log Extractor — Convertation")
        self.geometry("1300x600")
        self.minsize(850, 500)

        self.configure(bg="#1a1a2e")

        self._entries: list = []

        # список файлов
        self.file_paths: list[str] = []

        self._build_ui()


    def _build_ui(self):

        PAD = 10

        # header
        header = tk.Frame(
            self,
            bg="#16213e",
            pady=12
        )

        header.pack(fill="x")

        tk.Label(
            header,
            text="LOG EXTRACTOR",
            font=("Courier New", 18, "bold"),
            bg="#16213e",
            fg="#e94560"
        ).pack(side="left", padx=16)

        tk.Label(
            header,
            text="GenericService / Convertation  •  JSON Lines",
            font=("Courier New", 10),
            bg="#16213e",
            fg="#7a8ba0"
        ).pack(side="left")

        # controls
        ctrl = tk.Frame(
            self,
            bg="#1a1a2e",
            pady=6
        )

        ctrl.pack(fill="x", padx=PAD)


        row = tk.Frame(ctrl, bg="#1a1a2e")
        row.pack(fill="x", pady=4)

        tk.Label(
            row,
            text="Файлы логов:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0",
            width=14,
            anchor="w"
        ).pack(side="left")

        self.file_var = tk.StringVar()

        tk.Entry(
            row,
            textvariable=self.file_var,
            font=("Courier New", 9),
            bg="#0f3460",
            fg="#e0e0e0",
            insertbackground="white",
            relief="flat",
            bd=4
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 6)
        )

        self._btn(
            row,
            "Обзор…",
            self._browse_file
        ).pack(side="left")

        row2 = tk.Frame(ctrl, bg="#1a1a2e")
        row2.pack(fill="x", pady=4)

        tk.Label(
            row2,
            text="Дата от:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0",
            width=14,
            anchor="w"
        ).pack(side="left")

        self.date_from_var = tk.StringVar(
            value=date.today().strftime("%Y-%m-%d")
        )

        self._entry(
            row2,
            self.date_from_var,
            12
        ).pack(side="left", padx=(0, 4))

        tk.Label(
            row2,
            text="Время от:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0"
        ).pack(side="left")

        self.time_from_var = tk.StringVar(
            value="00:00:00"
        )

        self._entry(
            row2,
            self.time_from_var,
            10
        ).pack(side="left", padx=(0, 16))

        tk.Label(
            row2,
            text="Дата до:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0"
        ).pack(side="left")

        self.date_to_var = tk.StringVar(
            value=date.today().strftime("%Y-%m-%d")
        )

        self._entry(
            row2,
            self.date_to_var,
            12
        ).pack(side="left", padx=(0, 4))

        tk.Label(
            row2,
            text="Время до:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0"
        ).pack(side="left")

        self.time_to_var = tk.StringVar(
            value="23:59:59"
        )

        self._entry(
            row2,
            self.time_to_var,
            10
        ).pack(side="left")

        row3 = tk.Frame(ctrl, bg="#1a1a2e")
        row3.pack(fill="x", pady=6)

        tk.Label(
            row3,
            text="Уровни:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0",
            width=14,
            anchor="w"
        ).pack(side="left")

        self.lvl_debug = tk.BooleanVar(value=True)
        self.lvl_error = tk.BooleanVar(value=True)
        self.lvl_info = tk.BooleanVar(value=True)
        self.lvl_warn = tk.BooleanVar(value=True)

        for txt, var in [
            ("DEBUG", self.lvl_debug),
            ("ERROR", self.lvl_error),
            ("INFO", self.lvl_info),
            ("WARN", self.lvl_warn)
        ]:

            tk.Checkbutton(
                row3,
                text=txt,
                variable=var,
                font=("Courier New", 9),
                bg="#1a1a2e",
                fg="#c0d0e0",
                selectcolor="#0f3460",
                activebackground="#1a1a2e",
                activeforeground="#e94560"
            ).pack(side="left", padx=4)

      
        self.only_conv_var = tk.BooleanVar(value=True)

        tk.Checkbutton(
            row3,
            text="Только конвертация",
            variable=self.only_conv_var,
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#f0a050",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
            activeforeground="#e94560"
        ).pack(side="left", padx=(12, 4))

        self.only_key_var = tk.BooleanVar(value=True)

        tk.Checkbutton(
            row3,
            text="🔑 Только ключевые записи",
            variable=self.only_key_var,
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#a0d0e0",
            selectcolor="#0f3460",
            activebackground="#1a1a2e",
            activeforeground="#e94560"
        ).pack(side="left", padx=(4, 12))

        tk.Label(
            row3,
            text="Фильтр:",
            font=("Courier New", 9),
            bg="#1a1a2e",
            fg="#7a8ba0"
        ).pack(side="left")

        self.filter_var = tk.StringVar()

        self._entry(
            row3,
            self.filter_var,
            18
        ).pack(side="left", padx=(0, 8))

        self._btn(
            row3,
            "▶  Извлечь",
            self._run_extract,
            accent=True
        ).pack(side="left", padx=3)

        self._btn(
            row3,
            "💾  Сохранить",
            self._save_result
        ).pack(side="left", padx=3)

        self._btn(
            row3,
            "✕  Очистить",
            self._clear
        ).pack(side="left", padx=3)

      
        sf = tk.Frame(
            self,
            bg="#16213e",
            pady=4
        )

        sf.pack(fill="x", padx=PAD)

        self.status_var = tk.StringVar(
            value="Выберите файл и нажмите «Извлечь»"
        )

        tk.Label(
            sf,
            textvariable=self.status_var,
            font=("Courier New", 9),
            bg="#16213e",
            fg="#4caf82",
            anchor="w"
        ).pack(fill="x", padx=8)

        tf = tk.Frame(self, bg="#1a1a2e")
        tf.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

        style = ttk.Style(self)
        style.theme_use("default")

        style.configure(
            "Dark.Treeview",
            background="#0d1b2a",
            foreground="#c8d8e8",
            fieldbackground="#0d1b2a",
            font=("Courier New", 9),
            rowheight=20
        )

        style.configure(
            "Dark.Treeview.Heading",
            background="#16213e",
            foreground="#7ab0d0",
            font=("Courier New", 9, "bold"),
            relief="flat"
        )

        style.map(
            "Dark.Treeview",
            background=[("selected", "#1a4a7a")]
        )

        cols = ("ts", "level", "message")

        self.tree = ttk.Treeview(
            tf,
            columns=cols,
            show="headings",
            style="Dark.Treeview",
            selectmode="extended"
        )

        self.tree.heading("ts", text="Время")
        self.tree.heading("level", text="Уровень")
        self.tree.heading("message", text="Сообщение")

        self.tree.column(
            "ts",
            width=210,
            minwidth=180,
            stretch=False
        )

        self.tree.column(
            "level",
            width=70,
            minwidth=60,
            stretch=False
        )

        self.tree.column(
            "message",
            width=700,
            minwidth=300,
            stretch=True
        )

        self.tree.tag_configure(
            "ERROR",
            foreground="#e94560"
        )

        self.tree.tag_configure(
            "DEBUG",
            foreground="#c8d8e8"
        )

        self.tree.tag_configure(
            "INFO",
            foreground="#4caf82"
        )

        self.tree.tag_configure(
            "WARN",
            foreground="#f0a050"
        )

        vsb = ttk.Scrollbar(
            tf,
            orient="vertical",
            command=self.tree.yview
        )

        hsb = ttk.Scrollbar(
            tf,
            orient="horizontal",
            command=self.tree.xview
        )

        self.tree.configure(
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

      
        ctx = tk.Menu(
            self,
            tearoff=0,
            bg="#16213e",
            fg="#c8d8e8",
            activebackground="#1a4a7a"
        )

        ctx.add_command(
            label="Копировать строку",
            command=self._copy_row
        )

        ctx.add_command(
            label="Копировать всё",
            command=self._copy_all
        )

        self.ctx_menu = ctx

        self.tree.bind(
            "<Button-3>",
            lambda e: ctx.tk_popup(e.x_root, e.y_root)
        )

   
    def _btn(self, parent, text, cmd, accent=False):

        return tk.Button(
            parent,
            text=text,
            command=cmd,
            font=("Courier New", 9, "bold"),
            bg="#e94560" if accent else "#0f3460",
            fg="#ffffff",
            activebackground="#c0324e" if accent else "#1a4a7a",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2"
        )

    def _entry(self, parent, var, w):

        return tk.Entry(
            parent,
            textvariable=var,
            font=("Courier New", 9),
            bg="#0f3460",
            fg="#e0e0e0",
            insertbackground="white",
            relief="flat",
            bd=4,
            width=w
        )

    def _browse_file(self):

        paths = filedialog.askopenfilenames(
            title="Выберите файлы логов",
            filetypes=[
                ("Log files", "*.log *.txt"),
                ("All files", "*.*")
            ]
        )

        if paths:

            self.file_paths = list(paths)

            if len(paths) == 1:
                self.file_var.set(paths[0])

            else:
                self.file_var.set(
                    f"Выбрано файлов: {len(paths)}"
                )

    def _parse_dt(self, d: str, t: str, label: str) -> datetime:

        raw = f"{d.strip()} {t.strip()}"

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M"
        ):

            try:
                return datetime.strptime(raw, fmt)

            except ValueError:
                continue

        raise ValueError(
            f"Не удалось разобрать {label}: «{raw}»\n"
            f"Формат: YYYY-MM-DD HH:MM:SS"
        )

    def _run_extract(self):

        if not self.file_paths:
            messagebox.showerror(
                "Ошибка",
                "Укажите файлы логов."
            )
            return

        for p in self.file_paths:

            if not os.path.isfile(p):
                messagebox.showerror(
                    "Ошибка",
                    f"Файл не найден:\n{p}"
                )
                return

        try:

            dt_from = self._parse_dt(
                self.date_from_var.get(),
                self.time_from_var.get(),
                "Дата от"
            )

            dt_to = self._parse_dt(
                self.date_to_var.get(),
                self.time_to_var.get(),
                "Дата до"
            )

        except ValueError as e:

            messagebox.showerror(
                "Ошибка формата даты",
                str(e)
            )

            return

        if dt_from > dt_to:

            messagebox.showerror(
                "Ошибка",
                "«Дата от» должна быть раньше «Дата до»."
            )

            return

        levels = {
            l
            for l, v in [
                ("DEBUG", self.lvl_debug),
                ("ERROR", self.lvl_error),
                ("INFO", self.lvl_info),
                ("WARN", self.lvl_warn)
            ]
            if v.get()
        }

        if not levels:

            messagebox.showwarning(
                "Предупреждение",
                "Выберите хотя бы один уровень."
            )

            return

        self.status_var.set("⏳ Читаю файлы…")
        self.update()

        try:

            entries = extract_logs(
                self.file_paths,
                dt_from,
                dt_to,
                levels,
                only_converter=self.only_conv_var.get(),
                only_key=self.only_key_var.get()
            )

        except Exception as e:

            messagebox.showerror(
                "Ошибка чтения",
                str(e)
            )

            self.status_var.set(
                "Ошибка чтения файлов."
            )

            return

        flt = self.filter_var.get().strip().lower()

        if flt:

            entries = [
                e
                for e in entries
                if flt in e["message"].lower()
            ]

        self._entries = entries

        self.tree.delete(*self.tree.get_children())

        for e in entries:

            ts_str = e["ts"].strftime(
                "%Y-%m-%d %H:%M:%S.%f"
            )[:-3]

            self.tree.insert(
                "",
                "end",
                values=(
                    ts_str,
                    e["level"],
                    e["message"]
                ),
                tags=(e["level"],)
            )

        size_mb = (
            sum(
                os.path.getsize(p)
                for p in self.file_paths
            )
            / 1024 / 1024
        )

        self.status_var.set(
            f"✔ Найдено: {len(entries)} записей | "
            f"Файлов: {len(self.file_paths)} "
            f"({size_mb:.1f} МБ)"
        )

    def _save_result(self):

        if not self._entries:

            messagebox.showinfo(
                "Нет данных",
                "Сначала выполните извлечение."
            )

            return

        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[
                ("Log files", "*.log"),
                ("Text files", "*.txt")
            ],
            initialfile=(
                f"extracted_"
                f"{datetime.now():%Y%m%d_%H%M%S}.log"
            )
        )

        if not path:
            return

        try:

            with open(
                path,
                "w",
                encoding="utf-8"
            ) as f:

                for e in self._entries:
                    f.write(format_entry(e) + "\n")

            self.status_var.set(
                f"💾 Сохранено "
                f"{len(self._entries)} строк → {path}"
            )

        except Exception as ex:

            messagebox.showerror(
                "Ошибка сохранения",
                str(ex)
            )

 
    def _clear(self):

        self.tree.delete(*self.tree.get_children())

        self._entries = []

        self.file_paths = []

        self.file_var.set("")

        self.filter_var.set("")

        self.status_var.set("Очищено.")

  
    def _copy_row(self):

        lines = [
            " | ".join(self.tree.item(i, "values"))
            for i in self.tree.selection()
        ]

        if lines:

            self.clipboard_clear()

            self.clipboard_append(
                "\n".join(lines)
            )

    def _copy_all(self):

        if self._entries:

            self.clipboard_clear()

            self.clipboard_append(
                "\n".join(
                    format_entry(e)
                    for e in self._entries
                )
            )


if __name__ == "__main__":

    app = LogExtractorApp()

    app.mainloop()