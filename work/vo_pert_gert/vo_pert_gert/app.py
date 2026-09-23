from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .engine import Case, load_case, save_case, validate_case
from .outputs import generate_outputs


class SimulatorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VO PERT-GERT Monte Carlo Simulator")
        self.geometry("1180x760")
        self.case = Case(notes="Load an authoritative case before running.")
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        self.sim_name = self._entry(top, "Simulation Name", self.case.simulation_name, 0, 0)
        self.vo_id = self._entry(top, "Variation Order ID", self.case.variation_order_id, 0, 2)
        self.scenario = self._entry(top, "Scenario Name", self.case.scenario_name, 1, 0)
        self.iterations = self._entry(top, "Number of Iterations", "", 1, 2)
        self.seed = self._entry(top, "Random Seed", str(self.case.seed), 2, 0)
        ttk.Label(top, text="Blank iterations uses 50,000").grid(row=2, column=2, sticky="w")
        buttons = ttk.Frame(self, padding=10)
        buttons.pack(fill="x")
        for text, cmd in [
            ("Load Case", self.load_case), ("Save Case", self.save_case), ("Reset Defaults", self.reset_case),
            ("Run Simulation", self.run_simulation)
        ]:
            ttk.Button(buttons, text=text, command=cmd).pack(side="left", padx=4)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.pert_table = self._table("PERT Activities", ["ID", "Name", "Enabled", "O", "ML", "P"])
        self.gert_table = self._table("GERT Arcs", ["ID", "Name", "From", "To", "Probability", "Loop Cap", "O", "ML", "P"])
        self.refresh_tables()

    def _entry(self, parent, label, value, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=3)
        var = tk.StringVar(value=value)
        ttk.Entry(parent, textvariable=var, width=34).grid(row=row, column=col + 1, sticky="we", padx=4, pady=3)
        return var

    def _table(self, title, columns):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=130, anchor="center")
        y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscroll=y.set, xscroll=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="we")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def refresh_tables(self) -> None:
        for tree in [self.pert_table, self.gert_table]:
            tree.delete(*tree.get_children())
        for a in self.case.pert:
            self.pert_table.insert("", "end", values=[a.id, a.name, a.enabled, a.o, a.ml, a.p])
        for a in self.case.arcs:
            self.gert_table.insert("", "end", values=[a.id, a.name, a.from_node, a.to_node, a.probability, a.loop_cap or "", a.o, a.ml, a.p])

    def sync_case(self) -> None:
        self.case.simulation_name = self.sim_name.get()
        self.case.variation_order_id = self.vo_id.get()
        self.case.scenario_name = self.scenario.get()
        self.case.iterations = int(self.iterations.get()) if self.iterations.get().strip() else None
        self.case.seed = int(self.seed.get() or "42")

    def load_case(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Case files", "*.json")])
        if path:
            self.case = load_case(Path(path))
            self.refresh_tables()

    def save_case(self) -> None:
        self.sync_case()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Case files", "*.json")])
        if path:
            save_case(self.case, Path(path))

    def reset_case(self) -> None:
        self.case = Case(notes="Load an authoritative case before running.")
        self.refresh_tables()

    def run_simulation(self) -> None:
        try:
            self.sync_case()
            errors = validate_case(self.case)
            if errors:
                raise RuntimeError("AUTHORITATIVE INPUT INCOMPLETE - SIMULATION BLOCKED\n" + "\n".join(errors[:20]))
            out = filedialog.askdirectory(title="Choose output folder")
            if not out:
                return
            generate_outputs(self.case, Path(out), self.case.requested_iterations)
            messagebox.showinfo("Complete", "Simulation outputs were created.")
        except Exception as exc:
            messagebox.showerror("Simulation blocked", str(exc))


def main() -> None:
    SimulatorApp().mainloop()


if __name__ == "__main__":
    main()
