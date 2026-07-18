"""
desktop_app.app
==================
Standalone Tkinter desktop UI wrapping the full capability set of the
``hrgs_scheduler`` package: network/objective configuration, brute-force
and DP outer-loop search, results browsing, schedule-artifact
save/load/verify, and Graphviz-based DAG visualization.

Run in development mode with a Tk-enabled Python interpreter::

    python3 app.py

(See ../README.md in this directory for why the project's pinned
``/usr/local/bin/python3.13`` interpreter cannot be used here, and for
instructions on building a standalone executable with PyInstaller.)
"""

from __future__ import annotations

import queue
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller as ctl  # noqa: E402

try:
    from PIL import Image, ImageTk

    _HAS_PIL = True
except ImportError:  # pragma: no cover - PIL is expected to be present
    _HAS_PIL = False

APP_TITLE = "HRGS Purification Scheduler"
_SCRATCH_DIR = Path(tempfile.mkdtemp(prefix="hrgs_ui_"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_optional_int(text: str) -> int | None:
    text = text.strip()
    return int(text) if text else None


def _parse_optional_float(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def show_image_window(parent: tk.Widget, image_path: Path, title: str) -> None:
    """Open a Toplevel window previewing a PNG (or, for SVG, offer to open externally)."""
    if image_path.suffix.lower() != ".png" or not _HAS_PIL:
        if messagebox.askyesno(
            "Open externally",
            f"'{image_path.name}' can't be previewed inline (needs a .png + Pillow).\n"
            "Open it with the system's default viewer instead?",
        ):
            try:
                ctl.open_externally(image_path)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Open failed", str(exc))
        return

    win = tk.Toplevel(parent)
    win.title(title)

    img = Image.open(image_path)
    max_w, max_h = 1000, 800
    ratio = min(max_w / img.width, max_h / img.height, 1.0)
    if ratio < 1.0:
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))
    photo = ImageTk.PhotoImage(img)

    label = tk.Label(win, image=photo)
    label.image = photo  # keep a reference alive
    label.pack(fill="both", expand=True)

    ttk.Button(win, text="Close", command=win.destroy).pack(pady=4)


def _run_in_background(
    target: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None],
    root: tk.Tk,
) -> None:
    """Run *target* in a daemon thread, delivering the result/exception on the main thread."""
    q: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            q.put(("ok", target()))
        except Exception as exc:  # noqa: BLE001
            q.put(("error", exc))

    def poll() -> None:
        try:
            kind, payload = q.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        if kind == "ok":
            on_done(payload)
        else:
            on_error(payload)

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, poll)


# ---------------------------------------------------------------------------
# Search tab
# ---------------------------------------------------------------------------


class SearchTab(ttk.Frame):
    _COLUMNS = ("rank", "label", "F", "R", "C", "L (ms)", "P_succ", "score")

    def __init__(self, parent: tk.Widget, root: tk.Tk) -> None:
        super().__init__(parent)
        self._root = root
        self.results: list[Any] = []
        self.network: Any = None

        form = ttk.Frame(self)
        form.pack(side="left", fill="y", padx=8, pady=8)
        table_frame = ttk.Frame(self)
        table_frame.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        self._build_form(form)
        self._build_table(table_frame)

    # -- form ---------------------------------------------------------

    def _build_form(self, form: ttk.Frame) -> None:
        row = 0

        def add_row(label: str, widget: tk.Widget) -> None:
            nonlocal row
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=1)
            widget.grid(row=row, column=1, sticky="ew", pady=1)
            row += 1

        net_box = ttk.LabelFrame(form, text="Network")
        net_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        row += 1

        self.network_kind = tk.StringVar(value="paper")
        ttk.Label(net_box, text="Kind").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            net_box, textvariable=self.network_kind, values=ctl.NETWORK_KINDS, state="readonly", width=12
        ).grid(row=0, column=1)

        self.n_hops = tk.StringVar(value="10")
        self.e_d = tk.StringVar(value="0.005")
        self.length = tk.StringVar(value="2.0")
        self.gamma = tk.StringVar(value="0.0")
        self.c_speed = tk.StringVar(value="2e5")
        self.branching = tk.StringVar(value="16,14,1")
        self.arm_count = tk.StringVar(value="18")
        self.p_x_inner = tk.StringVar(value="0.0")
        self.p_z_inner = tk.StringVar(value="0.0")

        fields = (
            ("N (hops, uniform only)", self.n_hops),
            ("e_d", self.e_d),
            ("hop length (km, uniform only)", self.length),
            ("gamma", self.gamma),
            ("c (km/time-unit)", self.c_speed),
            ("branching (uniform only)", self.branching),
            ("arm_count (uniform only)", self.arm_count),
            ("p_x_inner (uniform only)", self.p_x_inner),
            ("p_z_inner (uniform only)", self.p_z_inner),
        )
        for i, (label, var) in enumerate(fields, start=1):
            ttk.Label(net_box, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(net_box, textvariable=var, width=14).grid(row=i, column=1, sticky="ew")

        obj_box = ttk.LabelFrame(form, text="Objective")
        obj_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        self.objective_kind = tk.StringVar(value="rate")
        ttk.Label(obj_box, text="Kind").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            obj_box, textvariable=self.objective_kind, values=ctl.OBJECTIVE_KINDS, state="readonly", width=12
        ).grid(row=0, column=1)

        self.f_min = tk.StringVar(value="0.9")
        self.r_min = tk.StringVar(value="")
        ttk.Label(obj_box, text="f_min (rate objective)").grid(row=1, column=0, sticky="w")
        ttk.Entry(obj_box, textvariable=self.f_min, width=14).grid(row=1, column=1, sticky="ew")
        ttk.Label(obj_box, text="r_min (fidelity objective)").grid(row=2, column=0, sticky="w")
        ttk.Entry(obj_box, textvariable=self.r_min, width=14).grid(row=2, column=1, sticky="ew")

        algo_box = ttk.LabelFrame(form, text="Algorithm")
        algo_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        self.algorithm = tk.StringVar(value="dp")
        ttk.Label(algo_box, text="Algorithm").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            algo_box, textvariable=self.algorithm, values=ctl.ALGORITHMS, state="readonly", width=12
        ).grid(row=0, column=1)

        self.e_max = tk.StringVar(value="40")
        ttk.Label(algo_box, text="e_max (budget)").grid(row=1, column=0, sticky="w")
        ttk.Entry(algo_box, textvariable=self.e_max, width=14).grid(row=1, column=1, sticky="ew")

        bf_box = ttk.LabelFrame(form, text="Brute-force options")
        bf_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        self.max_n_pur = tk.StringVar(value="")
        self.bf_max_rounds = tk.StringVar(value="4")
        self.include_heralded = tk.BooleanVar(value=True)
        self.include_optimistic = tk.BooleanVar(value=True)
        self.include_link_level = tk.BooleanVar(value=True)

        ttk.Label(bf_box, text="max_n_pur (blank=auto)").grid(row=0, column=0, sticky="w")
        ttk.Entry(bf_box, textvariable=self.max_n_pur, width=14).grid(row=0, column=1, sticky="ew")
        ttk.Label(bf_box, text="max_enumerated_rounds").grid(row=1, column=0, sticky="w")
        ttk.Entry(bf_box, textvariable=self.bf_max_rounds, width=14).grid(row=1, column=1, sticky="ew")
        ttk.Checkbutton(bf_box, text="include_heralded", variable=self.include_heralded).grid(
            row=2, column=0, columnspan=2, sticky="w"
        )
        ttk.Checkbutton(bf_box, text="include_optimistic", variable=self.include_optimistic).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )
        ttk.Checkbutton(bf_box, text="include_link_level", variable=self.include_link_level).grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        dp_box = ttk.LabelFrame(form, text="DP options")
        dp_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        row += 1

        self.max_link_copies = tk.StringVar(value="3")
        self.dp_max_rounds = tk.StringVar(value="3")
        self.include_bf_families = tk.BooleanVar(value=True)

        ttk.Label(dp_box, text="max_link_copies").grid(row=0, column=0, sticky="w")
        ttk.Entry(dp_box, textvariable=self.max_link_copies, width=14).grid(row=0, column=1, sticky="ew")
        ttk.Label(dp_box, text="max_enumerated_rounds").grid(row=1, column=0, sticky="w")
        ttk.Entry(dp_box, textvariable=self.dp_max_rounds, width=14).grid(row=1, column=1, sticky="ew")
        ttk.Checkbutton(
            dp_box, text="include_brute_force_families", variable=self.include_bf_families
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        self.run_button = ttk.Button(form, text="Run Search", command=self._on_run)
        self.run_button.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        row += 1

        self.status = tk.StringVar(value="Idle.")
        ttk.Label(form, textvariable=self.status, foreground="#555").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        actions = ttk.Frame(form)
        actions.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(actions, text="Visualize selected", command=self._on_visualize).pack(fill="x")
        ttk.Button(actions, text="Save selected...", command=self._on_save_selected).pack(fill="x", pady=2)

        top_n_frame = ttk.Frame(form)
        top_n_frame.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
        self.save_top_n = tk.StringVar(value="3")
        ttk.Label(top_n_frame, text="Save top N:").pack(side="left")
        ttk.Entry(top_n_frame, textvariable=self.save_top_n, width=5).pack(side="left", padx=4)
        ttk.Button(top_n_frame, text="Save...", command=self._on_save_top_n).pack(side="left")

        export_frame = ttk.Frame(form)
        export_frame.grid(row=row + 2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(export_frame, text="Export CSV...", command=self._on_export_csv).pack(
            side="left", expand=True, fill="x"
        )
        ttk.Button(export_frame, text="Export JSON...", command=self._on_export_json).pack(
            side="left", expand=True, fill="x", padx=(4, 0)
        )

        form.columnconfigure(1, weight=1)
        for box in (net_box, obj_box, algo_box, bf_box, dp_box):
            box.columnconfigure(1, weight=1)

    def _build_table(self, table_frame: ttk.Frame) -> None:
        self.tree = ttk.Treeview(table_frame, columns=self._COLUMNS, show="headings")
        widths = (50, 260, 90, 100, 50, 90, 90, 90)
        for col, w in zip(self._COLUMNS, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="w" if col in ("label",) else "e")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # -- parameter gathering -------------------------------------------

    def _gather_network(self) -> Any:
        return ctl.build_network(
            self.network_kind.get(),
            N=int(self.n_hops.get()),
            e_d=float(self.e_d.get()),
            length=float(self.length.get()),
            gamma=float(self.gamma.get()),
            c=float(self.c_speed.get()),
            branching=tuple(int(x) for x in self.branching.get().split(",") if x.strip()),
            arm_count=int(self.arm_count.get()),
            p_x_inner=float(self.p_x_inner.get()),
            p_z_inner=float(self.p_z_inner.get()),
        )

    def _gather_objective(self) -> Any:
        return ctl.build_objective(
            self.objective_kind.get(),
            f_min=_parse_optional_float(self.f_min.get()),
            r_min=_parse_optional_float(self.r_min.get()),
        )

    def _gather_search_kwargs(self) -> dict[str, Any]:
        if self.algorithm.get() == "brute_force":
            return {
                "max_n_pur": _parse_optional_int(self.max_n_pur.get()),
                "max_enumerated_rounds": int(self.bf_max_rounds.get()),
                "include_heralded": self.include_heralded.get(),
                "include_optimistic": self.include_optimistic.get(),
                "include_link_level": self.include_link_level.get(),
            }
        return {
            "max_link_copies": int(self.max_link_copies.get()),
            "max_enumerated_rounds": int(self.dp_max_rounds.get()),
            "include_brute_force_families": self.include_bf_families.get(),
        }

    # -- actions ---------------------------------------------------------

    def _on_run(self) -> None:
        try:
            network = self._gather_network()
            objective = self._gather_objective()
            e_max = int(self.e_max.get())
            algorithm = self.algorithm.get()
            kwargs = self._gather_search_kwargs()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self.run_button.state(["disabled"])
        self.status.set("Running search...")

        def work() -> list[Any]:
            return ctl.run_search(algorithm, network, objective, e_max, **kwargs)

        def done(results: list[Any]) -> None:
            self.run_button.state(["!disabled"])
            self.results = results
            self.network = network
            self.status.set(f"Done: {len(results)} result(s).")
            self._populate_table(results)

        def error(exc: Exception) -> None:
            self.run_button.state(["!disabled"])
            self.status.set("Search failed.")
            messagebox.showerror("Search failed", str(exc))

        _run_in_background(work, done, error, self._root)

    def _populate_table(self, results: list[Any]) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, res in enumerate(results, 1):
            ev = res.eval_result
            score_str = "-inf" if res.score == float("-inf") else f"{res.score:.4g}"
            self.tree.insert(
                "",
                "end",
                iid=str(i - 1),
                values=(
                    i,
                    res.label,
                    f"{ev.fidelity:.4f}",
                    f"{ev.rate:.4g}" if ev.rate else "N/A",
                    ev.resource_cost,
                    f"{ev.latency * 1e3:.4f}",
                    f"{ev.success_prob:.4f}",
                    score_str,
                ),
            )

    def _selected_result(self) -> Any | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a row in the results table first.")
            return None
        return self.results[int(sel[0])]

    def _on_visualize(self) -> None:
        res = self._selected_result()
        if res is None:
            return
        out_path = _SCRATCH_DIR / f"search_{res.label[:40]}.png".replace("/", "_")
        try:
            ctl.render_dag(res.dag, out_path, network=self.network, annotate=True)
        except RuntimeError as exc:
            messagebox.showerror("Graphviz not found", str(exc))
            return
        show_image_window(self, out_path, res.label)

    def _on_save_selected(self) -> None:
        res = self._selected_result()
        if res is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save schedule artifact",
            defaultextension=".json",
            initialdir=str(ctl.DEFAULT_SAVE_DIR),
            filetypes=[("Schedule JSON", "*.json")],
        )
        if not path:
            return
        ctl.save_selected(res, path, network=self.network)
        messagebox.showinfo("Saved", f"Saved to {path}")

    def _on_save_top_n(self) -> None:
        if not self.results:
            messagebox.showinfo("No results", "Run a search first.")
            return
        try:
            n = int(self.save_top_n.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Save top N must be an integer.")
            return
        directory = filedialog.askdirectory(
            title="Choose output directory", initialdir=str(ctl.DEFAULT_SAVE_DIR)
        )
        if not directory:
            return
        paths = ctl.save_top_n(self.results, directory, network=self.network, n=n)
        messagebox.showinfo("Saved", f"Saved {len(paths)} artifact(s) to {directory}")

    def _on_export_csv(self) -> None:
        if not self.results:
            messagebox.showinfo("No results", "Run a search first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export CSV", defaultextension=".csv", initialdir=str(ctl.DEFAULT_EXPORT_DIR)
        )
        if not path:
            return
        ctl.export_csv(self.results, path)
        messagebox.showinfo("Exported", f"Exported to {path}")

    def _on_export_json(self) -> None:
        if not self.results:
            messagebox.showinfo("No results", "Run a search first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export JSON", defaultextension=".json", initialdir=str(ctl.DEFAULT_EXPORT_DIR)
        )
        if not path:
            return
        ctl.export_json(self.results, path)
        messagebox.showinfo("Exported", f"Exported to {path}")


# ---------------------------------------------------------------------------
# Load / verify tab
# ---------------------------------------------------------------------------


class LoadTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, root: tk.Tk) -> None:
        super().__init__(parent)
        self._root = root
        self.loaded_result: Any = None
        self.loaded_network: Any = None
        self._current_path: Path | None = None

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Button(top, text="Browse artifact...", command=self._on_browse).pack(side="left")
        self.path_label = ttk.Label(top, text="(no file loaded)")
        self.path_label.pack(side="left", padx=8)

        self.summary = tk.Text(self, height=10, wrap="word")
        self.summary.pack(fill="both", expand=True, padx=8, pady=4)
        self.summary.configure(state="disabled")

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=4)
        ttk.Button(actions, text="Verify", command=self._on_verify).pack(side="left")
        ttk.Button(actions, text="Node counts", command=self._on_node_counts).pack(side="left", padx=4)
        ttk.Button(actions, text="Visualize", command=self._on_visualize).pack(side="left", padx=4)
        self.annotate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="annotate", variable=self.annotate_var).pack(side="left", padx=4)
        ttk.Button(actions, text="Export DOT...", command=self._on_export_dot).pack(side="left", padx=4)

        self.table = ttk.Treeview(self, columns=("field", "value"), show="headings", height=8)
        self.table.heading("field", text="Field")
        self.table.heading("value", text="Value")
        self.table.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    def _set_summary(self, text: str) -> None:
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", text)
        self.summary.configure(state="disabled")

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Open schedule artifact",
            initialdir=str(ctl.DEFAULT_SAVE_DIR),
            filetypes=[("Schedule JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            result, network = ctl.load_artifact(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        self.loaded_result = result
        self.loaded_network = network
        self._current_path = Path(path)
        self.path_label.config(text=str(path))
        ev = result.eval_result
        score_str = "infeasible" if result.score == float("-inf") else f"{result.score:.6g}"
        summary = (
            f"label       : {result.label}\n"
            f"score       : {score_str}\n"
            f"fidelity    : {ev.fidelity:.6f}\n"
            f"rate        : {ev.rate:.6g}\n"
            f"resource_cost: {ev.resource_cost}\n"
            f"latency_s   : {ev.latency:.6g}\n"
            f"success_prob: {ev.success_prob:.6f}\n\n"
            f"--- network ---\n{ctl.network_summary(network)}"
        )
        self._set_summary(summary)
        self.table.delete(*self.table.get_children())

    def _require_loaded(self) -> bool:
        if self.loaded_result is None:
            messagebox.showinfo("No artifact loaded", "Browse for a schedule artifact first.")
            return False
        return True

    def _on_verify(self) -> None:
        if not self._require_loaded():
            return
        rows = ctl.verify_against_stored(self.loaded_result.dag, self.loaded_network, self.loaded_result)
        self.table.delete(*self.table.get_children())
        self.table.configure(columns=("field", "recomputed", "stored", "ok"))
        for col in ("field", "recomputed", "stored", "ok"):
            self.table.heading(col, text=col)
        for r in rows:
            self.table.insert(
                "",
                "end",
                values=(r.field, f"{r.recomputed:.6g}", f"{r.stored:.6g}", "OK" if r.ok else "MISMATCH"),
            )
        if all(r.ok for r in rows):
            messagebox.showinfo("Verify", "All metrics match the stored values.")
        else:
            messagebox.showwarning("Verify", "Some metrics do NOT match the stored values.")

    def _on_node_counts(self) -> None:
        if not self._require_loaded():
            return
        counts = ctl.node_counts(self.loaded_result.dag)
        self.table.delete(*self.table.get_children())
        self.table.configure(columns=("field", "value"))
        self.table.heading("field", text="Node type")
        self.table.heading("value", text="Count")
        for name, n in sorted(counts.items()):
            self.table.insert("", "end", values=(name, n))

    def _on_visualize(self) -> None:
        if not self._require_loaded():
            return
        out_path = _SCRATCH_DIR / "loaded_artifact.png"
        try:
            ctl.render_dag(
                self.loaded_result.dag,
                out_path,
                network=self.loaded_network,
                annotate=self.annotate_var.get(),
            )
        except RuntimeError as exc:
            messagebox.showerror("Graphviz not found", str(exc))
            return
        show_image_window(self, out_path, self.loaded_result.label)

    def _on_export_dot(self) -> None:
        if not self._require_loaded():
            return
        path = filedialog.asksaveasfilename(title="Export DOT", defaultextension=".dot")
        if not path:
            return
        dot_src = ctl.dag_to_dot(
            self.loaded_result.dag, network=self.loaded_network, annotate=self.annotate_var.get()
        )
        Path(path).write_text(dot_src, encoding="utf-8")
        messagebox.showinfo("Exported", f"Exported to {path}")


# ---------------------------------------------------------------------------
# Figures browser tab
# ---------------------------------------------------------------------------


class FiguresTab(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Button(top, text="Refresh", command=self._refresh).pack(side="left")
        ttk.Button(top, text="Preview", command=self._preview).pack(side="left", padx=4)
        ttk.Button(top, text="Open externally", command=self._open_externally).pack(side="left")

        self.listbox = tk.Listbox(self)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._paths: list[Path] = []
        self._refresh()

    def _refresh(self) -> None:
        self._paths = ctl.list_figures()
        self.listbox.delete(0, "end")
        root = ctl.PROJECT_ROOT
        for p in self._paths:
            try:
                display = str(p.relative_to(root))
            except ValueError:
                display = str(p)
            self.listbox.insert("end", display)

    def _selected_path(self) -> Path | None:
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("No selection", "Pick a figure from the list first.")
            return None
        return self._paths[sel[0]]

    def _preview(self) -> None:
        path = self._selected_path()
        if path is not None:
            show_image_window(self, path, path.name)

    def _open_externally(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        try:
            ctl.open_externally(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open failed", str(exc))


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x760")

        if shutil.which("dot") is None:
            self.after(
                200,
                lambda: messagebox.showwarning(
                    "Graphviz not found",
                    "The Graphviz 'dot' executable was not found on PATH.\n"
                    "Search, save, load and verify will still work, but "
                    "visualization ('Visualize'/render) will fail until "
                    "Graphviz is installed (e.g. `apt install graphviz`).",
                ),
            )

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        notebook.add(SearchTab(notebook, self), text="Search")
        notebook.add(LoadTab(notebook, self), text="Load / Verify Artifact")
        notebook.add(FiguresTab(notebook), text="Figures")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        shutil.rmtree(_SCRATCH_DIR, ignore_errors=True)
        self.destroy()


def main() -> None:
    self_test = "--self-test" in sys.argv
    app = App()
    if self_test:
        # Non-interactive smoke test hook: exercise a tiny end-to-end flow
        # then close automatically, so this can be verified without a
        # human clicking through the UI (used in CI / headless checks).
        def run_self_test() -> None:
            try:
                notebook: ttk.Notebook = app.winfo_children()[0]
                search_tab: SearchTab = notebook.winfo_children()[0]
                search_tab.network_kind.set("paper")
                search_tab.algorithm.set("brute_force")
                search_tab.e_max.set("40")
                search_tab.max_n_pur.set("2")
                search_tab._on_run()
            finally:
                app.after(3000, app._on_close)

        app.after(100, run_self_test)
    app.mainloop()


if __name__ == "__main__":
    main()
