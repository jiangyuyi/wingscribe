#!/usr/bin/env python3
"""
WingScribe Configuration Wizard

A simple GUI wizard for configuring WingScribe on first run.
This helps users set up their photo directories and preferences.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import yaml
from pathlib import Path


class ConfigWizard:
    """Configuration wizard for WingScribe first-time setup."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WingScribe 配置向导")
        self.root.geometry("700x600")
        self.root.resizable(False, False)

        # Set window icon if available
        try:
            icon_path = Path(__file__).parent.parent / "assets" / "app-icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except:
            pass

        # Configuration values - simplified structure
        # User selects one root directory, we'll create subdirectories inside
        self.root_dir = os.path.expanduser("~/WingScribe")
        self.web_port = 8000

        # Current page
        self.current_page = 0

        # Page containers
        self.page_container = None

        # Build UI
        self.setup_ui()
        self.show_page(0)

    def setup_ui(self):
        """Setup the wizard UI."""
        # Header
        header = tk.Frame(self.root, bg="#667eea", height=70)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title_label = tk.Label(
            header,
            text="🕊️ WingScribe 配置向导",
            font=("Microsoft YaHei UI", 16, "bold"),
            bg="#667eea",
            fg="white"
        )
        title_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Content area
        self.page_container = tk.Frame(self.root, bg="white")
        self.page_container.pack(fill=tk.BOTH, expand=True)

        # Create pages
        self.create_welcome_page()
        self.create_directory_page()
        self.create_complete_page()

        # Button area - using tk.Button for better control
        button_frame = tk.Frame(self.root, bg="#f8f9fa", pady=20)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.back_btn = tk.Button(
            button_frame,
            text="< 上一步",
            command=self.go_back,
            font=("Microsoft YaHei UI", 10),
            width=12,
            height=2,
            bg="white",
            relief=tk.RAISED,
            state=tk.DISABLED
        )
        self.back_btn.pack(side=tk.LEFT, padx=30, pady=10)

        self.next_btn = tk.Button(
            button_frame,
            text="下一步 >",
            command=self.go_next,
            font=("Microsoft YaHei UI", 10),
            width=12,
            height=2,
            bg="#667eea",
            fg="white",
            relief=tk.RAISED,
            activebackground="#5568d3",
            activeforeground="white"
        )
        self.next_btn.pack(side=tk.RIGHT, padx=30, pady=10)

    def show_page(self, page_num):
        """Show a specific page."""
        # Clear current page
        for widget in self.page_container.winfo_children():
            widget.destroy()

        # Show requested page
        self.pages[page_num](self.page_container)
        self.current_page = page_num

        # Update button states
        num_pages = len(self.pages)
        self.back_btn.config(state=tk.NORMAL if page_num > 0 else tk.DISABLED)

        if page_num == num_pages - 1:
            self.next_btn.config(text="完成", command=self.finish, bg="#28a745",
                               activebackground="#218838")
        else:
            self.next_btn.config(text="下一步 >", command=self.go_next, bg="#667eea",
                               activebackground="#5568d3")

    def go_back(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.show_page(self.current_page - 1)

    def go_next(self):
        """Go to next page."""
        if self.current_page < len(self.pages) - 1:
            # Validate current page before moving
            if self.validate_page(self.current_page):
                self.show_page(self.current_page + 1)

    def validate_page(self, page_num):
        """Validate the current page before proceeding."""
        if page_num == 1:  # Directory page
            root_dir = self.root_dir_var.get().strip()
            if not root_dir:
                messagebox.showerror("错误", "请选择 WingScribe 根目录")
                return False

            # Test if directory exists or can be created
            if not os.path.exists(root_dir):
                try:
                    os.makedirs(root_dir, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("错误", f"无法创建目录: {e}")
                    return False

        return True

    def finish(self):
        """Finish the wizard and save configuration."""
        try:
            root_dir = self.root_dir_var.get().strip().replace('\\', '/')
            port = self.port_var.get()

            # Save configuration
            self.save_config(root_dir, port)

            # Show success message
            messagebox.showinfo(
                "配置完成",
                "WingScribe 配置已完成！\n\n"
                f"根目录: {root_dir}\n"
                f"访问地址: http://localhost:{port}\n\n"
                "点击确定后，Web 服务将自动启动。"
            )

            self.root.quit()
            self.root.destroy()

        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def save_config(self, root_dir, port):
        """Save configuration to settings.yaml."""
        # Get app root
        if getattr(sys, 'frozen', False):
            app_root = Path(sys.executable).parent
        else:
            app_root = Path(__file__).parent.parent

        config_path = app_root / "config" / "settings.yaml"
        config_dir = config_path.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        # Simplified configuration structure
        # root_dir is the base directory containing everything
        config_content = f"""# WingScribe config
# Generated by configuration wizard

paths:
  # Root directory for all data (photos input/output, database, models, etc.)
  base_dir: "{root_dir}"

  sources:
    # Source photos will be in: {root_dir}/原始照片/
    - path: "原始照片"
      recursive: true
      enabled: true

  output:
    # Processed photos will be saved to: {root_dir}/处理结果/
    root_dir: "处理结果"
    structure_template: "{{{{source_structure}}}}/{{{{filename}}}}_{{{{species_cn}}}}_{{{{confidence}}}}"
    write_back_to_source: false

  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"

processing:
  device: "cpu"
  yolo_model: "yolov26n.pt"
  confidence_threshold: 0.5
  blur_threshold: 40.0
  target_size: 640
  crop_padding: 200

recognition:
  mode: "local"
  region_filter: "auto"
  top_k: 5
  alternatives_threshold: 70
  low_confidence_threshold: 60
  hf_mirror: ""
  local:
    model_type: "bioclip-2"
    batch_size: 512
    inference_batch_size: 16

web:
  host: "0.0.0.0"
  port: {port}
  log_level: "info"
"""
        config_path.write_text(config_content, encoding='utf-8')

        # Create subdirectories
        (Path(root_dir) / "原始照片").mkdir(parents=True, exist_ok=True)
        (Path(root_dir) / "处理结果").mkdir(parents=True, exist_ok=True)
        (Path(root_dir) / "data").mkdir(parents=True, exist_ok=True)
        (Path(root_dir) / "data" / "db").mkdir(parents=True, exist_ok=True)
        (Path(root_dir) / "data" / "models").mkdir(parents=True, exist_ok=True)
        (Path(root_dir) / "data" / "references").mkdir(parents=True, exist_ok=True)
        (Path(root_dir) / "data" / "processed").mkdir(parents=True, exist_ok=True)

    def create_welcome_page(self):
        """Create welcome page function."""
        def render(container):
            container.config(bg="white")

            # Main content frame
            content = tk.Frame(container, bg="white", padx=50, pady=40)
            content.pack(expand=True, fill=tk.BOTH)

            # Title
            tk.Label(
                content,
                text="欢迎使用 WingScribe",
                font=("Microsoft YaHei UI", 20, "bold"),
                bg="white",
                fg="#333"
            ).pack(pady=(0, 10))

            tk.Label(
                content,
                text="🕊️ 飞羽志 | AI 鸟类照片管理系统",
                font=("Microsoft YaHei UI", 12),
                bg="white",
                fg="#667eea"
            ).pack(pady=(0, 40))

            # Info box
            info_frame = tk.Frame(content, bg="#f8f9fa", padx=30, pady=25)
            info_frame.pack(fill=tk.X, pady=20)

            tk.Label(
                info_frame,
                text="配置向导说明",
                font=("Microsoft YaHei UI", 12, "bold"),
                bg="#f8f9fa",
                fg="#333"
            ).pack(anchor=tk.W, pady=(0, 15))

            steps = [
                "• 选择 WingScribe 根目录（所有数据存放在此目录下）",
                "• 系统会自动创建以下子目录：",
                "  - 原始照片/    （放入待处理的照片）",
                "  - 处理结果/   （AI 识别后的照片）",
                "  - data/        （数据库和模型缓存）",
                "• 配置 Web 服务访问端口",
                "• 首次运行时，AI 模型将自动下载（约 500MB）"
            ]

            for step in steps:
                tk.Label(
                    info_frame,
                    text=step,
                    font=("Microsoft YaHei UI", 10),
                    bg="#f8f9fa",
                    fg="#555",
                    justify=tk.LEFT
                ).pack(anchor=tk.W, pady=3)

            # Tip
            tip_frame = tk.Frame(content, bg="#e8f4fd", padx=20, pady=15)
            tip_frame.pack(fill=tk.X, pady=20)

            tk.Label(
                tip_frame,
                text="💡 提示：建议选择有足够空间的磁盘（至少 10GB）",
                font=("Microsoft YaHei UI", 9),
                bg="#e8f4fd",
                fg="#0969da"
            ).pack(anchor=tk.W)

        self.pages.append(render)

    def create_directory_page(self):
        """Create directory selection page function."""
        def render(container):
            container.config(bg="white")

            # Main content frame
            content = tk.Frame(container, bg="white", padx=50, pady=40)
            content.pack(expand=True, fill=tk.BOTH)

            # Title
            tk.Label(
                content,
                text="步骤 1/1: 设置目录和端口",
                font=("Microsoft YaHei UI", 16, "bold"),
                bg="white",
                fg="#333"
            ).pack(pady=(0, 10))

            tk.Label(
                content,
                text="配置 WingScribe 的根目录",
                font=("Microsoft YaHei UI", 10),
                bg="white",
                fg="gray"
            ).pack(pady=(0, 30))

            # Root directory selection
            dir_frame = tk.Frame(content, bg="white")
            dir_frame.pack(fill=tk.X, pady=20)

            tk.Label(
                dir_frame,
                text="WingScribe 根目录：",
                font=("Microsoft YaHei UI", 10, "bold"),
                bg="white",
                fg="#333",
                width=120,
                anchor=tk.W
            ).pack(side=tk.LEFT, padx=(0, 10))

            self.root_dir_var = tk.StringVar(value=self.root_dir)

            entry_frame = tk.Frame(dir_frame, bg="white")
            entry_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Entry(
                entry_frame,
                textvariable=self.root_dir_var,
                font=("Microsoft YaHei UI", 10),
                width=40
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Button(
                entry_frame,
                text="浏览...",
                command=lambda: self.browse_directory(self.root_dir_var),
                font=("Microsoft YaHei UI", 9),
                bg="white",
                relief=tk.RAISED
            ).pack(side=tk.LEFT, padx=(10, 0))

            # Port configuration
            port_frame = tk.Frame(content, bg="white")
            port_frame.pack(fill=tk.X, pady=20)

            tk.Label(
                port_frame,
                text="Web 服务端口：",
                font=("Microsoft YaHei UI", 10, "bold"),
                bg="white",
                fg="#333",
                width=120,
                anchor=tk.W
            ).pack(side=tk.LEFT, padx=(0, 10))

            self.port_var = tk.StringVar(value=str(self.web_port))

            port_spinbox = tk.Spinbox(
                port_frame,
                from_=1024,
                to=65535,
                textvariable=self.port_var,
                font=("Microsoft YaHei UI", 10),
                width=10,
                bg="white",
                relief=tk.SUNKEN,
                bd=1
            )
            port_spinbox.pack(side=tk.LEFT)

            # Info box
            info_frame = tk.Frame(content, bg="#f8f9fa", padx=20, pady=15)
            info_frame.pack(fill=tk.X, pady=30)

            tk.Label(
                info_frame,
                text="目录结构说明",
                font=("Microsoft YaHei UI", 11, "bold"),
                bg="#f8f9fa",
                fg="#333"
            ).pack(anchor=tk.W, pady=(0, 10))

            structure_text = """WingScribe 根目录/
├── 原始照片/           ← 将待处理的鸟类照片放入此文件夹
│   └── 20240101_北京天坛/
│       └── IMG_001.jpg
├── 处理结果/           ← AI 识别后的照片自动保存到这里
│   └── 2024/
│       └── 北京天坛/
│           └── IMG_001_麻雀_85.jpg
└── data/              ← 数据库和模型缓存（自动管理）
    ├── db/
    ├── models/
    └── references/"""

            tk.Label(
                info_frame,
                text=structure_text,
                font=("Consolas", 9),
                bg="#f8f9fa",
                fg="#555",
                justify=tk.LEFT,
                anchor=tk.W
            ).pack(anchor=tk.W)

        self.pages.append(render)

    def create_complete_page(self):
        """Create completion page function."""
        def render(container):
            container.config(bg="white")

            # Main content frame
            content = tk.Frame(container, bg="white", padx=50, pady=40)
            content.pack(expand=True, fill=tk.BOTH)

            # Success icon
            tk.Label(
                content,
                text="✓",
                font=("Microsoft YaHei UI", 48),
                bg="white",
                fg="#28a745"
            ).pack(pady=(0, 20))

            tk.Label(
                content,
                text="配置完成！",
                font=("Microsoft YaHei UI", 18, "bold"),
                bg="white",
                fg="#333"
            ).pack(pady=(0, 30))

            # Summary frame
            summary_frame = tk.Frame(content, bg="#f8f9fa", padx=25, pady=20)
            summary_frame.pack(fill=tk.X, pady=20)

            tk.Label(
                summary_frame,
                text="配置摘要",
                font=("Microsoft YaHei UI", 11, "bold"),
                bg="#f8f9fa",
                fg="#333"
            ).pack(anchor=tk.W, pady=(0, 15))

            # Dynamic summary (will be updated before showing)
            self.summary_labels = {}
            summary_items = [
                ("root_dir", "根目录："),
                ("port", "Web 服务端口：")
            ]

            for key, label in summary_items:
                row = tk.Frame(summary_frame, bg="#f8f9fa")
                row.pack(fill=tk.X, pady=5)

                tk.Label(
                    row,
                    text=label,
                    font=("Microsoft YaHei UI", 10),
                    bg="#f8f9fa",
                    fg="#555",
                    width=120,
                    anchor=tk.W
                ).pack(side=tk.LEFT)

                value_label = tk.Label(
                    row,
                    text="",
                    font=("Microsoft YaHei UI", 10, "bold"),
                    bg="#f8f9fa",
                    fg="#333",
                    anchor=tk.W
                )
                value_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
                self.summary_labels[key] = value_label

            # Next steps
            steps_frame = tk.Frame(content, bg="#e8f4fd", padx=20, pady=20)
            steps_frame.pack(fill=tk.X, pady=30)

            tk.Label(
                steps_frame,
                text="下一步操作",
                font=("Microsoft YaHei UI", 11, "bold"),
                bg="#e8f4fd",
                fg="#0969da"
            ).pack(anchor=tk.W, pady=(0, 10))

            steps = [
                "1. 将您的鸟类照片放入「原始照片」文件夹",
                "2. 点击「完成」启动 Web 服务",
                "3. 在浏览器中访问管理界面触发处理",
                "4. 首次运行时，AI 模型会自动下载（约 500MB）"
            ]

            for step in steps:
                tk.Label(
                    steps_frame,
                    text=step,
                    font=("Microsoft YaHei UI", 9),
                    bg="#e8f4fd",
                    fg="#333",
                    justify=tk.LEFT
                ).pack(anchor=tk.W, pady=3)

        self.pages.append(render)

    def update_summary(self):
        """Update the summary on the completion page."""
        if hasattr(self, 'summary_labels'):
            self.summary_labels['root_dir'].config(text=self.root_dir_var.get())
            self.summary_labels['port'].config(text=self.port_var.get())

    def browse_directory(self, variable):
        """Open directory browser dialog."""
        directory = filedialog.askdirectory(
            title="选择目录",
            initialdir=variable.get()
        )
        if directory:
            variable.set(directory)

    def run(self):
        """Run the wizard."""
        # Override show_page to update summary when showing completion page
        original_show_page = self.show_page

        def enhanced_show_page(page_num):
            original_show_page(page_num)
            if page_num == len(self.pages) - 1:
                self.update_summary()

        self.show_page = enhanced_show_page

        self.root.mainloop()


def main():
    """Main entry point."""
    wizard = ConfigWizard()
    wizard.run()


if __name__ == "__main__":
    main()
