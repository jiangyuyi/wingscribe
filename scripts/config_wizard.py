#!/usr/bin/env python3
"""
WingScribe Configuration Wizard

A simple GUI wizard for configuring WingScribe on first run.
This helps users set up their photo directories and preferences.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import yaml
from pathlib import Path


class ConfigWizard:
    """Configuration wizard for WingScribe first-time setup."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WingScribe 配置向导")
        self.root.geometry("600x500")
        self.root.resizable(False, False)

        # Try to set icon if available
        try:
            icon_path = Path(__file__).parent.parent / "assets" / "app-icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except:
            pass

        # Configuration values
        self.config = {
            'base_dir': os.path.expanduser("~/Pictures"),
            'output_dir': "data/processed",
            'web_host': "0.0.0.0",
            'web_port': 8000,
            'device': "cpu"
        }

        # Current page
        self.current_page = 0

        # Pages
        self.pages = []

        # Build UI
        self.setup_ui()
        self.show_page(0)

    def setup_ui(self):
        """Setup the wizard UI."""
        # Header
        header = tk.Frame(self.root, bg="#667eea", height=80)
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
        self.content_frame = tk.Frame(self.root, padx=40, pady=30)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        # Button area
        button_frame = tk.Frame(self.root, pady=20)
        button_frame.pack(fill=tk.X)

        self.back_btn = ttk.Button(
            button_frame,
            text="<< 上一步",
            command=self.go_back,
            width=12
        )
        self.back_btn.pack(side=tk.LEFT, padx=10)
        self.back_btn.state(['disabled'])

        self.next_btn = ttk.Button(
            button_frame,
            text="下一步 >>",
            command=self.go_next,
            width=12
        )
        self.next_btn.pack(side=tk.RIGHT, padx=10)

        # Create pages
        self.create_welcome_page()
        self.create_photo_dir_page()
        self.create_output_dir_page()
        self.create_web_config_page()
        self.create_complete_page()

    def show_page(self, page_num):
        """Show a specific page."""
        # Hide all pages
        for page in self.pages:
            page.pack_forget()

        # Show requested page
        self.pages[page_num].pack(fill=tk.BOTH, expand=True)
        self.current_page = page_num

        # Update button states
        self.back_btn.state(['!disabled'] if page_num > 0 else ['disabled'])

        if page_num == len(self.pages) - 1:
            self.next_btn.configure(text="完成", command=self.finish)
        else:
            self.next_btn.configure(text="下一步 >>", command=self.go_next)

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
        if page_num == 1:  # Photo directory page
            photo_dir = self.photo_dir_var.get().strip()
            if not photo_dir:
                messagebox.showerror("错误", "请选择照片目录")
                return False
            if not os.path.exists(photo_dir):
                result = messagebox.askyesno(
                    "目录不存在",
                    f"目录不存在: {photo_dir}\n\n是否创建此目录？"
                )
                if result:
                    try:
                        os.makedirs(photo_dir, exist_ok=True)
                    except Exception as e:
                        messagebox.showerror("错误", f"无法创建目录: {e}")
                        return False
                else:
                    return False

        elif page_num == 2:  # Output directory page
            output_dir = self.output_dir_var.get().strip()
            if not output_dir:
                messagebox.showerror("错误", "请选择输出目录")
                return False

        return True

    def finish(self):
        """Finish the wizard and save configuration."""
        try:
            # Update config from UI
            self.config['base_dir'] = self.photo_dir_var.get().strip().replace('\\', '/')
            self.config['output_dir'] = self.output_dir_var.get().strip().replace('\\', '/')
            self.config['web_host'] = self.host_var.get()
            self.config['web_port'] = int(self.port_var.get())

            # Save configuration
            self.save_config()

            # Show success message
            messagebox.showinfo(
                "配置完成",
                "WingScribe 配置已完成！\n\n"
                "您可以启动 Web 服务开始使用。"
            )

            self.root.quit()
            self.root.destroy()

        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def save_config(self):
        """Save configuration to settings.yaml."""
        # Get app root
        if getattr(sys, 'frozen', False):
            app_root = Path(sys.executable).parent
        else:
            app_root = Path(__file__).parent.parent

        config_path = app_root / "config" / "settings.yaml"
        config_dir = config_path.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        # Generate YAML content
        config_content = f"""# WingScribe config
# Generated by configuration wizard

paths:
  base_dir: "{self.config['base_dir']}"
  references_path: "data/references"
  sources:
    - path: "."
      recursive: true
      enabled: true
  output:
    root_dir: "{self.config['output_dir']}"
    structure_template: "{{source_structure}}/{{filename}}_{{species_cn}}_{{confidence}}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"

processing:
  device: "{self.config['device']}"
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
  host: "{self.config['web_host']}"
  port: {self.config['web_port']}
  log_level: "info"
"""

        config_path.write_text(config_content, encoding='utf-8')

        # Create secrets template if it doesn't exist
        secrets_path = app_root / "config" / "secrets.yaml"
        if not secrets_path.exists():
            secrets_content = """# WingScribe secrets
# 请填入您的 API 密钥

# 顶层 API 密钥
hf_api_key: ""
dongniao_api_key: ""

# 云端识别配置
cloud:
  huggingface:
    api_token: ""
    model_id: "imageomics/bioclip-2"
  modelscope:
    api_token: ""
  baidu:
    api_key: ""
    secret_key: ""
  aliyun:
    access_key_id: ""
    access_key_secret: ""
"""
            secrets_path.write_text(secrets_content, encoding='utf-8')

    def create_welcome_page(self):
        """Create welcome page."""
        page = tk.Frame(self.content_frame)

        tk.Label(
            page,
            text="欢迎使用 WingScribe",
            font=("Microsoft YaHei UI", 18, "bold")
        ).pack(pady=(0, 20))

        tk.Label(
            page,
            text="🕊️ 飞羽志 | AI 鸟类照片管理系统",
            font=("Microsoft YaHei UI", 12),
            fg="#667eea"
        ).pack(pady=(0, 30))

        info_text = """本向导将帮助您配置 WingScribe。

配置内容包括：
• 照片源目录（包含待处理的鸟类照片）
• 输出目录（处理后的照片保存位置）
• Web 服务配置（访问地址和端口）

预计用时：2 分钟"""

        tk.Label(
            page,
            text=info_text,
            font=("Microsoft YaHei UI", 10),
            justify=tk.LEFT
        ).pack(pady=20)

        self.pages.append(page)

    def create_photo_dir_page(self):
        """Create photo directory selection page."""
        page = tk.Frame(self.content_frame)

        tk.Label(
            page,
            text="步骤 1/3: 选择照片目录",
            font=("Microsoft YaHei UI", 14, "bold")
        ).pack(pady=(0, 10))

        tk.Label(
            page,
            text="选择包含鸟类照片的目录",
            font=("Microsoft YaHei UI", 10),
            fg="gray"
        ).pack(pady=(0, 30))

        # Directory selection
        dir_frame = tk.Frame(page)
        dir_frame.pack(fill=tk.X, pady=20)

        self.photo_dir_var = tk.StringVar(value=self.config['base_dir'])

        tk.Entry(
            dir_frame,
            textvariable=self.photo_dir_var,
            width=50,
            font=("Microsoft YaHei UI", 10)
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(
            dir_frame,
            text="浏览...",
            command=lambda: self.browse_directory(self.photo_dir_var)
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Instructions
        help_text = """建议的目录结构：
  年份/日期_地点/照片.jpg

例如：
  2024/20240101_北京天坛/IMG_001.jpg
  2024/20240102_颐和园/IMG_002.jpg"""

        tk.Label(
            page,
            text=help_text,
            font=("Microsoft YaHei UI", 9),
            justify=tk.LEFT,
            bg="#f5f5f5",
            padx=15,
            pady=15
        ).pack(fill=tk.X, pady=20)

        self.pages.append(page)

    def create_output_dir_page(self):
        """Create output directory selection page."""
        page = tk.Frame(self.content_frame)

        tk.Label(
            page,
            text="步骤 2/3: 选择输出目录",
            font=("Microsoft YaHei UI", 14, "bold")
        ).pack(pady=(0, 10))

        tk.Label(
            page,
            text="处理后的照片将保存到此目录",
            font=("Microsoft YaHei UI", 10),
            fg="gray"
        ).pack(pady=(0, 30))

        # Directory selection
        dir_frame = tk.Frame(page)
        dir_frame.pack(fill=tk.X, pady=20)

        self.output_dir_var = tk.StringVar(value=self.config['output_dir'])

        tk.Entry(
            dir_frame,
            textvariable=self.output_dir_var,
            width=50,
            font=("Microsoft YaHei UI", 10)
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(
            dir_frame,
            text="浏览...",
            command=lambda: self.browse_directory(self.output_dir_var)
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Tip
        tk.Label(
            page,
            text="💡 提示：可以设置为与照片目录相同的位置",
            font=("Microsoft YaHei UI", 9),
            fg="#667eea"
        ).pack(pady=20)

        self.pages.append(page)

    def create_web_config_page(self):
        """Create web service configuration page."""
        page = tk.Frame(self.content_frame)

        tk.Label(
            page,
            text="步骤 3/3: Web 服务配置",
            font=("Microsoft YaHei UI", 14, "bold")
        ).pack(pady=(0, 10))

        tk.Label(
            page,
            text="配置 Web 管理界面",
            font=("Microsoft YaHei UI", 10),
            fg="gray"
        ).pack(pady=(0, 30))

        # Host configuration
        host_frame = tk.Frame(page)
        host_frame.pack(fill=tk.X, pady=10)

        tk.Label(
            host_frame,
            text="监听地址：",
            font=("Microsoft YaHei UI", 10),
            width=15,
            anchor=tk.W
        ).pack(side=tk.LEFT)

        self.host_var = tk.StringVar(value=self.config['web_host'])
        host_combo = ttk.Combobox(
            host_frame,
            textvariable=self.host_var,
            values=["0.0.0.0", "127.0.0.1", "localhost"],
            width=30,
            font=("Microsoft YaHei UI", 10)
        )
        host_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Port configuration
        port_frame = tk.Frame(page)
        port_frame.pack(fill=tk.X, pady=10)

        tk.Label(
            port_frame,
            text="端口号：",
            font=("Microsoft YaHei UI", 10),
            width=15,
            anchor=tk.W
        ).pack(side=tk.LEFT)

        self.port_var = tk.StringVar(value=str(self.config['web_port']))
        tk.Spinbox(
            port_frame,
            from_=1024,
            to=65535,
            textvariable=self.port_var,
            width=28,
            font=("Microsoft YaHei UI", 10)
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Info
        info_frame = tk.Frame(page, bg="#e8f4fd", padx=15, pady=15)
        info_frame.pack(fill=tk.X, pady=20)

        tk.Label(
            info_frame,
            text="📌 默认配置说明",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg="#e8f4fd"
        ).pack(anchor=tk.W)

        tk.Label(
            info_frame,
            text="""• 0.0.0.0 = 允许局域网访问
• 127.0.0.1 = 仅本机访问
• 端口 8000 = 常用端口，一般无需修改""",
            font=("Microsoft YaHei UI", 9),
            justify=tk.LEFT,
            bg="#e8f4fd"
        ).pack(anchor=tk.W, pady=(5, 0))

        self.pages.append(page)

    def create_complete_page(self):
        """Create completion page."""
        page = tk.Frame(self.content_frame)

        tk.Label(
            page,
            text="🎉 配置完成！",
            font=("Microsoft YaHei UI", 16, "bold"),
            fg="#28a745"
        ).pack(pady=(0, 30))

        # Summary
        summary_frame = tk.Frame(page, bg="#f5f5f5", padx=20, pady=20)
        summary_frame.pack(fill=tk.X, pady=20)

        tk.Label(
            summary_frame,
            text="配置摘要",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg="#f5f5f5"
        ).pack(anchor=tk.W, pady=(0, 10))

        summary_labels = [
            ("照片目录", self.photo_dir_var),
            ("输出目录", self.output_dir_var),
            ("访问地址", self.host_var),
            ("端口号", self.port_var),
        ]

        for label, var in summary_labels:
            row = tk.Frame(summary_frame, bg="#f5f5f5")
            row.pack(fill=tk.X, pady=5)
            tk.Label(
                row,
                text=label + "：",
                font=("Microsoft YaHei UI", 9),
                bg="#f5f5f5",
                width=15,
                anchor=tk.W
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=var.get(),
                font=("Microsoft YaHei UI", 9),
                bg="#f5f5f5",
                fg="#333"
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Next steps
        next_steps = """下一步：
  1. 点击"完成"保存配置
  2. 启动 WingScribe Web 服务
  3. 在浏览器中访问管理界面
  4. 首次使用时，AI 模型将自动下载"""

        tk.Label(
            page,
            text=next_steps,
            font=("Microsoft YaHei UI", 10),
            justify=tk.LEFT,
            fg="#667eea"
        ).pack(pady=20)

        self.pages.append(page)

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
        self.root.mainloop()


def main():
    """Main entry point."""
    wizard = ConfigWizard()
    wizard.run()


if __name__ == "__main__":
    main()
