from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_gpu_installer_uses_blackwell_compatible_pytorch():
    build_script = (PROJECT_ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "installer" / "requirements-gpu.txt").read_text(
        encoding="utf-8"
    )

    assert 'TorchVersion = "2.10.0"' in build_script
    assert 'TorchvisionVersion = "0.25.0"' in build_script
    assert 'WheelChannel = "cu128"' in build_script
    assert "torch==2.10.0" in requirements
    assert "torchvision==0.25.0" in requirements


def test_cpu_installer_keeps_existing_pytorch_runtime():
    build_script = (PROJECT_ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "installer" / "requirements-cpu.txt").read_text(
        encoding="utf-8"
    )

    assert 'TorchVersion = "2.4.1"' in build_script
    assert 'TorchvisionVersion = "0.19.1"' in build_script
    assert 'WheelChannel = "cpu"' in build_script
    assert "torch==2.4.1" in requirements
    assert "torchvision==0.19.1" in requirements


def test_pytorch_wheel_source_is_configurable():
    build_script = (PROJECT_ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")

    assert '[string]$PyTorchWheelBase = "https://download.pytorch.org/whl"' in build_script
    assert '$PYTORCH_WHEEL_BASE = $PyTorchWheelBase.TrimEnd("/")' in build_script
    assert "$PYTORCH_WHEEL_BASE/$PYTORCH_WHEEL_CHANNEL/torch-$TORCH_VERSION" in build_script


def test_manual_installer_build_does_not_publish_release_by_default():
    workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "build-installer.yml"
    ).read_text(encoding="utf-8")

    assert "publish_release:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "if: github.event_name == 'push' || inputs.publish_release" in workflow
