"""CJA Audit Log Monitor - CLI tool for Adobe CJA audit logs."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cja-audit-log-monitor")
except PackageNotFoundError:  # pragma: no cover - source tree without install metadata
    __version__ = "0.0.0"
