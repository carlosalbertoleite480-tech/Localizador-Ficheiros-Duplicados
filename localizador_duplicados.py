# -*- coding: utf-8 -*-
"""
Localizador de Ficheiros Duplicados
Copyright (c) 2026 Carlos Leite Fonseca
Todos os direitos reservados.

Protótipo inicial: encontra ficheiros idênticos por SHA-256 e imagens visualmente
semelhantes por hash perceptual (se Pillow estiver instalado).
"""

from __future__ import annotations

import hashlib
import os
import queue
import threading
import sys
from collections import defaultdict
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Localizador de Ficheiros Duplicados"
APP_VERSION = "Versão 1.5"
COPYRIGHT = "© 2026 Carlos Leite Fonseca. Todos os direitos reservados."
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"
}
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows.old"
}
CHUNK_SIZE = 1024 * 1024

try:
    from PIL import Image, ImageOps, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    from send2trash import send2trash
    SEND2TRASH_AVAILABLE = True
except Exception:
    send2trash = None
    SEND2TRASH_AVAILABLE = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def image_phash(path: Path) -> int | None:
    """Hash perceptual simples 8x8; serve para sinalizar imagens parecidas."""
    if not PIL_AVAILABLE:
        return None
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("L").resize((8, 8))
            pixels = list(image.getdata())
        average = sum(pixels) / len(pixels)
        value = 0
        for pixel in pixels:
            value = (value << 1) | int(pixel >= average)
        return value
    except Exception:
        return None


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class DuplicateFinderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1120x720")
        self.root.minsize(850, 520)
        self.root.configure(bg="#f2f5f9")
        # Resolve o ícone tanto em execução normal como na aplicação compilada.
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        icon_path = bundle_dir / "localizador_clf.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass
        self.events: queue.Queue = queue.Queue()
        self.scan_thread: threading.Thread | None = None
        self.scanning = False
        self.results: list[dict] = []
        self.path_to_result: dict[str, dict] = {}
        self.thumbnail_refs = []
        self.list_thumbnail_refs = []
        self.gallery_selection_vars = {}

        self._style()
        self._build_ui()
        self.root.after(150, self._poll_events)

    def _style(self):
        style = ttk.Style()
        # Interface com aspeto consistente; usa o tema nativo do Windows quando disponível.
        # O tema clam respeita as cores personalizadas também no Windows;
        # o tema vista pode ignorar o fundo e deixar texto branco sobre fundo branco.
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#eef3f8")
        style.configure("TLabel", background="#eef3f8", foreground="#263445", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#24476b")
        style.configure("Sub.TLabel", foreground="#5b6b7b")
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7),
                        background="#24476b", foreground="#ffffff", borderwidth=0)
        style.map("TButton",
                  background=[("disabled", "#aab8c5"), ("active", "#193651"), ("!disabled", "#24476b")],
                  foreground=[("disabled", "#f2f5f9"), ("!disabled", "#ffffff")])
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"),
                        background="#24476b", foreground="#ffffff", padding=(12, 7))
        style.map("Primary.TButton",
                  background=[("disabled", "#aab8c5"), ("active", "#193651"), ("!disabled", "#24476b")],
                  foreground=[("disabled", "#f2f5f9"), ("!disabled", "#ffffff")])
        # Linhas mais altas para as miniaturas médias na vista Lista.
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=118, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(8, 8))

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)

        # Reservar primeiro o rodapé impede que os elementos expansíveis o empurrem para fora da janela.
        footer = tk.Frame(outer, bg="#24476b", padx=12, pady=8, height=42)
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        footer.pack_propagate(False)
        tk.Label(
            footer, text=COPYRIGHT, bg="#24476b", fg="#ffffff",
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", anchor="w", pady=2)
        tk.Label(
            footer, text=APP_VERSION, bg="#24476b", fg="#ffffff",
            font=("Segoe UI", 10, "bold")
        ).pack(side="right", anchor="e", pady=2)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        # Marca CLF maior e legível dentro da própria janela.
        logo = tk.Label(
            header, text="CLF", bg="#24476b", fg="#ffffff",
            font=("Segoe UI", 26, "bold"), padx=18, pady=10,
            relief="flat", borderwidth=0
        )
        logo.pack(side="left", padx=(0, 16), anchor="n")
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, text=APP_NAME, style="Title.TLabel").pack(anchor="w", pady=(1, 0))
        ttk.Label(
            heading,
            text="Analise discos e pastas para encontrar cópias e imagens semelhantes.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=(4, 0))

        folder_card = ttk.Frame(outer, padding=14)
        folder_card.pack(fill="x", pady=(0, 10))
        folder_row = ttk.Frame(folder_card)
        folder_row.pack(fill="x", pady=(0, 7))
        self.folder_var = tk.StringVar()
        ttk.Entry(folder_row, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(folder_row, text="Escolher pasta…", command=self.choose_folder).pack(side="left")
        analyze_button = tk.Button(
            folder_row, text="Analisar", command=self.start_scan,
            bg="#24476b", fg="#ffffff", activebackground="#193651",
            activeforeground="#ffffff", disabledforeground="#e8edf2",
            relief="flat", borderwidth=0, cursor="hand2",
            font=("Segoe UI", 10, "bold"), padx=18, pady=8,
            highlightthickness=0
        )
        analyze_button.bind("<Enter>", lambda _event: analyze_button.configure(bg="#193651"))
        analyze_button.bind("<Leave>", lambda _event: analyze_button.configure(bg="#24476b"))
        analyze_button.pack(side="left", padx=(8, 0))

        options = ttk.Frame(folder_card)
        options.pack(fill="x", pady=(0, 2))
        self.images_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options, text="Procurar também imagens semelhantes", variable=self.images_var,
            state=("normal" if PIL_AVAILABLE else "disabled")
        ).pack(side="left")
        if not PIL_AVAILABLE:
            ttk.Label(options, text="(instale Pillow para ativar esta opção)", style="Sub.TLabel").pack(side="left", padx=(5, 0))
        self.status_var = tk.StringVar(value="Escolha uma pasta ou a raiz de um disco para começar.")
        ttk.Label(outer, textvariable=self.status_var).pack(anchor="w", pady=(2, 7))

        table_card = ttk.Frame(outer, padding=8)
        table_card.pack(fill="both", expand=True)
        self.views = ttk.Notebook(table_card)
        self.views.pack(fill="both", expand=True)
        list_tab = ttk.Frame(self.views, padding=5)
        self.images_tab = ttk.Frame(self.views, padding=5)
        self.views.add(list_tab, text="Lista")
        self.views.add(self.images_tab, text="Imagens")
        table_frame = ttk.Frame(list_tab)
        table_frame.pack(fill="both", expand=True)
        columns = ("kind", "size", "name")
        # A coluna de árvore (#0) mostra miniaturas ao lado do nome do ficheiro.
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Img.")
        self.tree.column("#0", width=158, minwidth=158, stretch=False, anchor="center")
        self.tree.heading("kind", text="Correspondência")
        self.tree.heading("size", text="Tamanho")
        self.tree.heading("name", text="Nome do ficheiro")
        self.tree.column("kind", width=150, minwidth=130, stretch=False)
        self.tree.column("size", width=95, minwidth=85, anchor="e", stretch=False)
        self.tree.column("name", width=230, minwidth=150, stretch=True)
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_location)
        self.location_var = tk.StringVar(value="Selecione um ficheiro para consultar a localização completa.")
        ttk.Label(list_tab, textvariable=self.location_var, style="Sub.TLabel", wraplength=1050).pack(fill="x", anchor="w", pady=(6, 0))
        self.gallery_canvas = tk.Canvas(self.images_tab, background="#eef3f8", highlightthickness=0)
        gallery_scroll = ttk.Scrollbar(self.images_tab, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_inner = ttk.Frame(self.gallery_canvas)
        for gallery_col in range(3):
            self.gallery_inner.columnconfigure(gallery_col, weight=1, uniform="gallery")
        self.gallery_inner.bind("<Configure>", lambda _e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.create_window((0, 0), window=self.gallery_inner, anchor="nw")
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        gallery_scroll.pack(side="right", fill="y")
        # A roda do rato percorre a galeria mesmo quando o cursor está sobre uma miniatura.
        self.root.bind_all("<MouseWheel>", self._on_gallery_mousewheel)
        self.root.bind_all("<Button-4>", self._on_gallery_mousewheel)  # Linux: roda para cima
        self.root.bind_all("<Button-5>", self._on_gallery_mousewheel)  # Linux: roda para baixo

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Selecionar todas as linhas", command=self.select_all).pack(side="left")
        ttk.Button(actions, text="Enviar selecionados para a Reciclagem", command=self.delete_selected).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Exportar relatório CSV…", command=self.export_csv).pack(side="left", padx=(8, 0))
        warning = "Segurança: a aplicação não elimina ficheiros automaticamente; só envia para a Reciclagem após seleção e confirmação."
        if not SEND2TRASH_AVAILABLE:
            warning += " Para ativar o envio seguro para a Reciclagem, instale o pacote send2trash."
        ttk.Label(outer, text=warning, style="Sub.TLabel", wraplength=1050).pack(anchor="w", pady=(8, 0))

    def _on_gallery_mousewheel(self, event):
        """Scroll only the image gallery when the Images tab is active and hovered."""
        try:
            if self.views.select() != str(self.images_tab):
                return
            widget = event.widget
            inside_gallery = False
            while widget is not None:
                if widget == self.gallery_canvas or widget == self.gallery_inner:
                    inside_gallery = True
                    break
                widget = getattr(widget, "master", None)
            if not inside_gallery:
                return
            if getattr(event, "num", None) == 4:
                self.gallery_canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                self.gallery_canvas.yview_scroll(3, "units")
            else:
                delta = getattr(event, "delta", 0)
                if delta:
                    units = max(1, abs(delta) // 120) * 3
                    self.gallery_canvas.yview_scroll(-units if delta > 0 else units, "units")
            return "break"
        except tk.TclError:
            return

    def _show_selected_location(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            self.location_var.set("Selecione um ficheiro para consultar a localização completa.")
            return
        result = self.path_to_result.get(selected[0], {})
        self.location_var.set("Localização completa: " + result.get("path", ""))
        self._sync_gallery_selection()

    def _sync_gallery_selection(self):
        selected = set(self.tree.selection())
        for path, variable in self.gallery_selection_vars.items():
            iid = self._iid_for_path(path)
            if iid:
                variable.set(iid in selected)

    def _make_list_thumbnail(self, result):
        """Create a clearly visible medium-sized thumbnail for the list, kept alive for Tk."""
        if not PIL_AVAILABLE or Path(result.get("path", "")).suffix.lower() not in IMAGE_EXTS:
            return ""
        try:
            with Image.open(result["path"]) as original:
                thumb = ImageOps.exif_transpose(original).convert("RGB")
                thumb.thumbnail((148, 108))
                photo = ImageTk.PhotoImage(thumb)
            self.list_thumbnail_refs.append(photo)
            return photo
        except Exception:
            return ""

    def _populate_gallery(self):
        for child in self.gallery_inner.winfo_children():
            child.destroy()
        self.thumbnail_refs.clear()
        if not PIL_AVAILABLE:
            ttk.Label(self.gallery_inner, text="A pré-visualização de imagens não está disponível nesta versão.").grid(row=0, column=0, sticky="w")
            return
        image_results = [r for r in self.results if Path(r["path"]).suffix.lower() in IMAGE_EXTS]
        if not image_results:
            ttk.Label(self.gallery_inner, text="Não foram encontradas imagens entre os resultados desta análise.").grid(row=0, column=0, sticky="w")
            return
        for index, result in enumerate(image_results):
            card = ttk.Frame(self.gallery_inner, padding=8, relief="groove")
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=8, pady=8)
            try:
                with Image.open(result["path"]) as original:
                    thumb = ImageOps.exif_transpose(original).convert("RGB")
                    thumb.thumbnail((240, 180))
                    photo = ImageTk.PhotoImage(thumb)
                self.thumbnail_refs.append(photo)
                ttk.Label(card, image=photo).pack()
            except Exception:
                ttk.Label(card, text="Pré-visualização\nindisponível", width=20, anchor="center").pack(pady=22)
            ttk.Label(card, text=result["name"][:48], wraplength=230, justify="center").pack(pady=(6, 3))
            ttk.Label(card, text=self._human_size(result["size"]), style="Sub.TLabel").pack()
            iid = self._iid_for_path(result.get("path", ""))
            selected_var = tk.BooleanVar(value=bool(iid and iid in self.tree.selection()))
            self.gallery_selection_vars[result.get("path", "")] = selected_var
            ttk.Checkbutton(
                card, text="Selecionar para eliminar", variable=selected_var,
                command=lambda r=result, v=selected_var: self._toggle_gallery_selection(r, v.get())
            ).pack(pady=(5, 0))
            ttk.Button(card, text="Ver localização", command=lambda r=result: self._show_gallery_location(r)).pack(pady=(4, 0))

    def _iid_for_path(self, path):
        for iid, item in self.path_to_result.items():
            if item.get("path") == path:
                return iid
        return None

    def _toggle_gallery_selection(self, result, selected):
        iid = self._iid_for_path(result.get("path", ""))
        if not iid:
            return
        if selected:
            self.tree.selection_add(iid)
        else:
            self.tree.selection_remove(iid)
        self._show_selected_location()

    def _show_gallery_location(self, result):
        self.views.select(0)
        self.location_var.set("Localização completa: " + result.get("path", ""))
        for iid, item in self.path_to_result.items():
            if item.get("path") == result.get("path"):
                self.tree.selection_set(iid)
                self.tree.see(iid)
                break

    def choose_folder(self):
        chosen = filedialog.askdirectory(title="Escolha a pasta ou a raiz do disco a analisar")
        if chosen:
            self.folder_var.set(chosen)

    def start_scan(self):
        if self.scanning:
            return
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(APP_NAME, "Escolha uma pasta existente ou a raiz de um disco.")
            return
        if not messagebox.askyesno(
            APP_NAME,
            "A análise pode demorar bastante em discos grandes.\n\n"
            "Os ficheiros serão apenas lidos; nada será eliminado.\n\n"
            "Pretende continuar?"
        ):
            return
        self.scanning = True
        self.results.clear()
        self.path_to_result.clear()
        self.thumbnail_refs.clear()
        self.list_thumbnail_refs.clear()
        for child in self.gallery_inner.winfo_children():
            child.destroy()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_var.set("A preparar análise…")
        self.scan_thread = threading.Thread(
            target=self._scan_worker, args=(Path(folder), self.images_var.get()), daemon=True
        )
        self.scan_thread.start()

    def _scan_worker(self, root: Path, check_images: bool):
        files: list[Path] = []
        skipped = 0
        for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]
            for name in names:
                p = Path(current) / name
                try:
                    if p.is_file() and not p.is_symlink():
                        files.append(p)
                except OSError:
                    skipped += 1
            if len(files) % 250 == 0:
                self.events.put(("status", f"Ficheiros encontrados: {len(files):,}…"))
        self.events.put(("status", f"A comparar {len(files):,} ficheiros…"))

        by_size: dict[int, list[Path]] = defaultdict(list)
        for p in files:
            try:
                by_size[p.stat().st_size].append(p)
            except OSError:
                skipped += 1

        exact_groups: list[list[Path]] = []
        total_to_hash = sum(len(v) for v in by_size.values() if len(v) > 1)
        done = 0
        for size, candidates in by_size.items():
            if len(candidates) < 2:
                continue
            by_hash: dict[str, list[Path]] = defaultdict(list)
            for p in candidates:
                try:
                    by_hash[sha256_file(p)].append(p)
                except (OSError, PermissionError):
                    skipped += 1
                done += 1
                if done % 20 == 0:
                    self.events.put(("status", f"A comparar conteúdo: {done:,}/{total_to_hash:,}…"))
            exact_groups.extend(group for group in by_hash.values() if len(group) > 1)

        output = []
        for group in exact_groups:
            group_id = "exact-" + str(len(output) + 1)
            for p in group:
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                output.append({
                    "kind": "Duplicado exato",
                    "size": size,
                    "name": p.name,
                    "path": str(p),
                    "group": group_id,
                })

        similar_groups: list[list[Path]] = []
        if check_images and PIL_AVAILABLE:
            image_paths = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
            hashes: list[tuple[Path, int]] = []
            for idx, p in enumerate(image_paths, 1):
                ph = image_phash(p)
                if ph is not None:
                    hashes.append((p, ph))
                if idx % 50 == 0:
                    self.events.put(("status", f"A analisar imagens: {idx:,}/{len(image_paths):,}…"))
            # Agrupamento simples: cada imagem é comparada com as anteriores.
            used: set[str] = set()
            for i, (p1, h1) in enumerate(hashes):
                matches = [p1]
                for p2, h2 in hashes[i + 1:]:
                    if str(p2) not in used and hamming_distance(h1, h2) <= 5:
                        matches.append(p2)
                if len(matches) > 1:
                    similar_groups.append(matches)
                    used.update(str(p) for p in matches)
            # Evitar mostrar pares que já pertencem ao mesmo grupo de duplicados exatos.
            exact_paths = {r["path"] for r in output}
            for group in similar_groups:
                group_id = "image-" + str(len(output) + 1)
                for p in group:
                    if str(p) in exact_paths:
                        continue
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    output.append({
                        "kind": "Imagem semelhante",
                        "size": size,
                        "name": p.name,
                        "path": str(p),
                        "group": group_id,
                    })

        self.events.put(("done", output, len(files), skipped, len(exact_groups), len(similar_groups)))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    self.status_var.set(event[1])
                elif event[0] == "done":
                    _, results, scanned, skipped, exact_count, similar_count = event
                    self.results = results
                    self.path_to_result.clear()
                    self.list_thumbnail_refs.clear()
                    self.gallery_selection_vars.clear()
                    for old_iid in self.tree.get_children():
                        self.tree.delete(old_iid)
                    for result in results:
                        thumb = self._make_list_thumbnail(result)
                        iid = self.tree.insert(
                            "", "end", text="", image=thumb,
                            values=(result["kind"], self._human_size(result["size"]), result["name"])
                        )
                        self.path_to_result[iid] = result
                    self._populate_gallery()
                    self.scanning = False
                    msg = f"Concluído: {scanned:,} ficheiros analisados; {exact_count} grupo(s) de duplicados exatos"
                    if self.images_var.get() and PIL_AVAILABLE:
                        msg += f"; {similar_count} grupo(s) de imagens semelhantes"
                    msg += f". {skipped} ficheiro(s) não puderam ser lidos." if skipped else "."
                    self.status_var.set(msg)
                    if not results:
                        messagebox.showinfo(APP_NAME, "A análise terminou. Não foram encontrados grupos duplicados com os critérios atuais.")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    @staticmethod
    def _human_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())
        self._sync_gallery_selection()

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Selecione primeiro as linhas que pretende enviar para a Reciclagem.")
            return
        if not SEND2TRASH_AVAILABLE:
            messagebox.showerror(
                APP_NAME,
                "O envio para a Reciclagem não está disponível.\n\n"
                "Instale a dependência com:\npy -m pip install send2trash"
            )
            return
        paths = []
        for iid in selected:
            result = self.path_to_result.get(iid)
            if result and result["path"] not in paths:
                paths.append(result["path"])
        if not messagebox.askyesno(
            APP_NAME,
            f"Vai enviar {len(paths)} ficheiro(s) selecionado(s) para a Reciclagem do Windows.\n\n"
            "Confirme que não está a eliminar a única cópia de um ficheiro importante.\n\n"
            "Continuar?"
        ):
            return
        moved = 0
        failures = []
        for path in paths:
            try:
                send2trash(path)
                moved += 1
            except Exception as exc:
                failures.append(f"{path}: {exc}")
        message = f"{moved} ficheiro(s) enviados para a Reciclagem."
        if failures:
            message += f"\n\nNão foi possível enviar {len(failures)} ficheiro(s):\n" + "\n".join(failures[:5])
        messagebox.showinfo(APP_NAME, message)
        self.start_scan_refresh()

    def start_scan_refresh(self):
        # Remove linhas e cartões que já não correspondem a ficheiros existentes.
        for iid in list(self.tree.get_children()):
            result = self.path_to_result.get(iid, {})
            if not os.path.exists(result.get("path", "")):
                self.tree.delete(iid)
                self.path_to_result.pop(iid, None)
        self.results = [r for r in self.results if os.path.exists(r.get("path", ""))]
        self.gallery_selection_vars.clear()
        self._populate_gallery()
        self.status_var.set("Resultados atualizados após a eliminação selecionada.")

    def export_csv(self):
        if not self.results:
            messagebox.showinfo(APP_NAME, "Não existem resultados para exportar.")
            return
        filename = filedialog.asksaveasfilename(
            title="Guardar relatório",
            defaultextension=".csv",
            filetypes=[("Ficheiro CSV", "*.csv")],
            initialfile="relatorio_duplicados.csv"
        )
        if not filename:
            return
        import csv
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(["Grupo", "Tipo", "Tamanho em bytes", "Nome", "Localização"])
                for result in self.results:
                    writer.writerow([
                        result["group"], result["kind"], result["size"],
                        result["name"], result["path"]
                    ])
            messagebox.showinfo(APP_NAME, f"Relatório guardado em:\n{filename}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível guardar o relatório:\n{exc}")


def main():
    root = tk.Tk()
    DuplicateFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
