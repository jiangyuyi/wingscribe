import os
import platform
import sys
from dataclasses import dataclass

import torch


def _rss_mb() -> float | None:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return None


@dataclass(frozen=True)
class HardwareMeasurement:
    device: str
    rss_start_mb: float | None


def begin_hardware_measurement(device: str) -> HardwareMeasurement:
    normalized = str(device)
    if normalized.startswith("cuda") and torch.cuda.is_available():
        torch_device = torch.device(normalized)
        torch.cuda.synchronize(torch_device)
        torch.cuda.reset_peak_memory_stats(torch_device)
    return HardwareMeasurement(device=normalized, rss_start_mb=_rss_mb())


def finish_hardware_measurement(measurement: HardwareMeasurement) -> dict:
    rss_end = _rss_mb()
    result = {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "device": measurement.device,
        "rss_start_mb": measurement.rss_start_mb,
        "rss_end_mb": rss_end,
        "rss_delta_mb": (
            rss_end - measurement.rss_start_mb
            if rss_end is not None and measurement.rss_start_mb is not None
            else None
        ),
    }

    if measurement.device.startswith("cuda") and torch.cuda.is_available():
        device = torch.device(measurement.device)
        torch.cuda.synchronize(device)
        properties = torch.cuda.get_device_properties(device)
        result.update(
            {
                "gpu_name": properties.name,
                "gpu_total_memory_mb": properties.total_memory / (1024 * 1024),
                "gpu_peak_allocated_mb": torch.cuda.max_memory_allocated(device) / (1024 * 1024),
                "gpu_peak_reserved_mb": torch.cuda.max_memory_reserved(device) / (1024 * 1024),
            }
        )
    return result
