#!/usr/bin/env python3
"""
WingScribe TUI 主界面

使用 rich 和 questionary 库提供交互式终端界面。
"""

import os
import sys
import subprocess
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent

# 添加项目路径
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.style import Style
    from rich import print as rprint
    import questionary
except ImportError:
    print("错误: 缺少 TUI 依赖。请运行: pip install -r scripts/requirements_tui.txt")
    sys.exit(1)

# 颜色主题
console = Console()


def print_header():
    """打印标题"""
    console.clear()
    title = Text()
    title.append("🪶 WingScribe\n", style="bold cyan")
    title.append("  AI 驱动的鸟类照片智能管理系统", style="italic white")
    console.print(Panel(title, style="cyan", subtitle="按 q 退出"))


def print_menu(options, title="菜单"):
    """打印菜单并返回选择"""
    console.print(f"\n[bold cyan]┌────────────────────────────────────────┐[/]")
    console.print(f"[bold cyan]│[/]  [white]{title}[/]")
    console.print("[bold cyan]├────────────────────────────────────────┤[/]")

    for i, option in enumerate(options, 1):
        icon, text = option
        console.print(f"[bold cyan]│[/]    [{i}] {icon} {text}")

    console.print("[bold cyan]└────────────────────────────────────────┘[/]")
    return Prompt.ask("[bold cyan]请输入选项 (1-{0})[/]: ".format(len(options)))


def check_environment():
    """检查环境"""
    checks = []

    # 检查 Python
    try:
        result = subprocess.run(
            ["python", "--version"] if os.name == "nt" else ["python3", "--version"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            checks.append(("Python", "✓", "green"))
        else:
            checks.append(("Python", "✗", "red"))
    except:
        checks.append(("Python", "✗", "red"))

    # 检查 Git
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            checks.append(("Git", "✓", "green"))
        else:
            checks.append(("Git", "✗", "red"))
    except:
        checks.append(("Git", "✗", "red"))

    # 检查 ExifTool
    try:
        result = subprocess.run(["exiftool", "-ver"], capture_output=True, text=True)
        if result.returncode == 0:
            checks.append(("ExifTool", "✓", "green"))
        else:
            checks.append(("ExifTool", "✗", "yellow"))
    except:
        checks.append(("ExifTool", "✗", "yellow"))

    return checks


def show_status():
    """显示环境状态"""
    print_header()

    console.print("\n[bold cyan]┌────────────────────────────────────────┐[/]")
    console.print("[bold cyan]│[/]  [white]📊 环境状态[/]")
    console.print("[bold cyan]├────────────────────────────────────────┤[/]")

    checks = check_environment()
    for name, status, color in checks:
        console.print(f"[bold cyan]│[/]    {name}: [bold {color}]{status}[/]")

    console.print("[bold cyan]└────────────────────────────────────────┘[/]")

    # 检查配置文件
    config_file = PROJECT_ROOT / "config" / "settings.yaml"
    if config_file.exists():
        console.print("\n[green]✓ 配置文件已存在[/]")
    else:
        console.print("\n[yellow]⚠ 需要配置项目[/]")


def show_help():
    """显示帮助信息"""
    console.clear()
    help_text = """
[bold cyan]📖 飞羽志使用帮助[/]

[bold]功能介绍:[/]
  • YOLOv8 鸟类检测 - 自动识别照片中的鸟类
  • BioCLIP 物种识别 - AI 智能分类物种
  • EXIF 元数据注入 - 自动写入识别结果
  • Web 界面管理 - 浏览器浏览和修正

[bold]快速开始:[/]
  1. 选择 [1] 开始部署 - 安装依赖和配置
  2. 配置照片源目录 - 你的鸟片所在位置
  3. 启动 Web 服务 - 浏览器访问管理

[bold]目录结构要求:[/]
  📁 年/
     └── yyyyMMdd_地点/
          └── *.jpg/*.png

[bold]技术支持:[/]
  GitHub: https://github.com/jiangyuyi/wingscribe
    """
    console.print(Panel(help_text, title="帮助", style="cyan"))


def run_deploy():
    """运行部署流程"""
    show_status()

    console.print("\n[bold cyan]🚀 开始部署流程[/]")

    # 检查依赖
    console.print("\n[yellow]检查系统依赖...[/]")

    # 检测 Python
    try:
        subprocess.run(["python", "--version"] if os.name == "nt" else ["python3", "--version"],
                       capture_output=True)
        console.print("  [green]✓[/] Python")
    except:
        console.print("  [red]✗[/] Python 未安装")
        console.print("\n[yellow]请先安装 Python 3.8+: https://www.python.org/downloads/[/]")
        return

    # 检测 Git
    try:
        subprocess.run(["git", "--version"], capture_output=True)
        console.print("  [green]✓[/] Git")
    except:
        console.print("  [yellow]⚠[/] Git 未安装 (可选)")

    # 配置
    console.print("\n[bold]配置项目[/]")

    source_dir = Prompt.ask("\n[cyan]照片源目录 (你的鸟片所在位置)[/]")
    if not source_dir:
        source_dir = str(Path.home() / "Pictures")
        console.print(f"使用默认目录: {source_dir}")

    output_dir = Prompt.ask("[cyan]输出目录[/]", default=str(PROJECT_ROOT / "data" / "processed"))
    if not output_dir:
        output_dir = str(PROJECT_ROOT / "data" / "processed")

    console.print(f"\n[green]✓[/] 配置完成:")
    console.print(f"  照片源: {source_dir}")
    console.print(f"  输出目录: {output_dir}")

    # 计算相对于 base_dir 的输出目录
    relative_output_dir = output_dir
    if source_dir and output_dir.startswith(source_dir):
        relative_output_dir = output_dir[len(source_dir):].lstrip('/').lstrip('\\')

    # 生成配置
    config_content = f'''
paths:
  base_dir: "{source_dir.replace('\\', '/')}"

  sources:
    - path: "."
      recursive: true
      enabled: true

  output:
    root_dir: "{relative_output_dir.replace('\\', '/')}"
    structure_template: "{{source_structure}}/{{filename}}_{{species_cn}}_{{confidence}}"
    write_back_to_source: false

  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"

processing:
  device: "auto"
  yolo_model: "yolo26n.pt"
  confidence_threshold: 0.5

recognition:
  mode: "local"
  region_filter: "auto"
  top_k: 5

web:
  host: "0.0.0.0"
  port: 8000
'''

    config_file = PROJECT_ROOT / "config" / "settings.yaml"
    config_file.parent.mkdir(exist_ok=True)
    config_file.write_text(config_content)

    console.print(f"\n[green]✓[/] 配置文件已生成: {config_file}")
    console.print(f"\n[bold]下一步:[/]")
    console.print("  1. 运行 [3] 启动服务 → [1] 启动 Web 界面")
    console.print("  2. 浏览器访问 http://localhost:8000")


def run_config():
    """运行配置"""
    console.clear()
    console.print(Panel("[bold]⚙️ 配置向导[/]", style="cyan"))

    source_dir = Prompt.ask("\n[cyan]照片源目录[/]")
    output_dir = Prompt.ask("[cyan]输出目录[/]", default=str(PROJECT_ROOT / "data" / "processed"))
    device = Prompt.ask("[cyan]处理设备[/]", default="auto",
                        choices=["auto", "cuda", "cpu"])

    console.print(f"\n[green]配置完成[/]")
    console.print(f"  照片源: {source_dir}")
    console.print(f"  输出目录: {output_dir}")
    console.print(f"  处理设备: {device}")


def start_web():
    """启动 Web 服务"""
    console.print("\n[bold]🌐 启动 Web 服务...[/]")
    console.print("按 Ctrl+C 停止服务\n")

    web_script = PROJECT_ROOT / "src" / "web" / "app.py"

    if not web_script.exists():
        console.print("[red]错误: 未找到 Web 应用脚本[/]")
        return

    try:
        # 使用虚拟环境或系统 Python
        venv_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe" if os.name == "nt" \
            else PROJECT_ROOT / "venv" / "bin" / "python"

        if venv_python.exists():
            cmd = [str(venv_python), str(web_script)]
        else:
            cmd = ["python", str(web_script)]

        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]服务已停止[/]")
    except Exception as e:
        console.print(f"\n[red]错误: {e}[/]")


def update_project():
    """更新项目"""
    console.print("\n[bold]📦 更新项目...[/]")

    try:
        result = subprocess.run(
            ["git", "pull", "origin", "master"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            console.print("[green]✓[/] 项目已更新")
        else:
            console.print("[yellow]⚠[/] 更新失败，可能有本地修改")
            console.print(result.stdout)
    except Exception as e:
        console.print(f"[red]错误: {e}[/]")


def download_model():
    """下载模型"""
    console.print("\n[bold]⬇️ 下载 BioCLIP 模型 (~500MB)...[/]")

    try:
        # 使用 huggingface_hub
        from huggingface_hub import snapshot_download

        model_dir = PROJECT_ROOT / "data" / "models" / "bioclip"
        model_dir.mkdir(parents=True, exist_ok=True)

        console.print("正在下载...")

        snapshot_download(
            repo_id="imageomics/bioclip",
            local_dir=str(model_dir),
            resume_download=True
        )

        console.print("[green]✓[/] 模型下载完成")
    except Exception as e:
        console.print(f"[red]错误: {e}[/]")
        console.print("\n请手动下载模型: https://huggingface.co/imageomics/bioclip")


def main():
    """主函数"""
    while True:
        print_header()
        show_status()

        options = [
            ("🚀", "开始部署"),
            ("⚙️", "配置选项"),
            ("📦", "更新项目"),
            ("⬇️", "下载模型"),
            ("🌐", "启动 Web 界面"),
            ("📖", "查看帮助"),
            ("❌", "退出"),
        ]

        try:
            choice = print_menu(options, "主菜单")

            if choice == "1":
                run_deploy()
            elif choice == "2":
                run_config()
            elif choice == "3":
                update_project()
            elif choice == "4":
                download_model()
            elif choice == "5":
                start_web()
            elif choice == "6":
                show_help()
            elif choice == "7" or choice.lower() == "q":
                console.print("\n[cyan]感谢使用飞羽志！再见！[/]\n")
                break

            if choice not in ["6", "7"]:
                Prompt.ask("\n[dim]按 Enter 继续...[/]")
        except KeyboardInterrupt:
            console.print("\n\n[cyan]感谢使用羽迹！再见！[/]\n")
            break


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        console.print(f"\n[red]发生错误: {e}[/]")
        sys.exit(1)
