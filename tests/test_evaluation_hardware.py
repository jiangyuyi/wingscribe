from types import SimpleNamespace

import pytest

from src.evaluation import hardware


def test_cpu_hardware_measurement_records_runtime(monkeypatch):
    rss_values = iter([100.0, 112.5])
    monkeypatch.setattr(hardware, "_rss_mb", lambda: next(rss_values))

    measurement = hardware.begin_hardware_measurement("cpu")
    result = hardware.finish_hardware_measurement(measurement)

    assert result["device"] == "cpu"
    assert result["rss_start_mb"] == 100.0
    assert result["rss_end_mb"] == 112.5
    assert result["rss_delta_mb"] == 12.5
    assert result["python_version"]
    assert "gpu_name" not in result


def test_cuda_hardware_measurement_records_peak_memory(monkeypatch):
    calls = []
    monkeypatch.setattr(hardware, "_rss_mb", lambda: None)
    monkeypatch.setattr(hardware.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(hardware.torch.cuda, "synchronize", lambda device: calls.append(("sync", str(device))))
    monkeypatch.setattr(
        hardware.torch.cuda,
        "reset_peak_memory_stats",
        lambda device: calls.append(("reset", str(device))),
    )
    monkeypatch.setattr(
        hardware.torch.cuda,
        "get_device_properties",
        lambda device: SimpleNamespace(name="RTX 5060 Laptop GPU", total_memory=8 * 1024**3),
    )
    monkeypatch.setattr(hardware.torch.cuda, "max_memory_allocated", lambda device: 3 * 1024**3)
    monkeypatch.setattr(hardware.torch.cuda, "max_memory_reserved", lambda device: 4 * 1024**3)

    measurement = hardware.begin_hardware_measurement("cuda:0")
    result = hardware.finish_hardware_measurement(measurement)

    assert calls == [("sync", "cuda:0"), ("reset", "cuda:0"), ("sync", "cuda:0")]
    assert result["gpu_name"] == "RTX 5060 Laptop GPU"
    assert result["gpu_total_memory_mb"] == pytest.approx(8192)
    assert result["gpu_peak_allocated_mb"] == pytest.approx(3072)
    assert result["gpu_peak_reserved_mb"] == pytest.approx(4096)


def test_rss_failure_is_optional(monkeypatch):
    monkeypatch.setattr(hardware, "_rss_mb", lambda: None)

    result = hardware.finish_hardware_measurement(hardware.begin_hardware_measurement("cpu"))

    assert result["rss_start_mb"] is None
    assert result["rss_delta_mb"] is None
