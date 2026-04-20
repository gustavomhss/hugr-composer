from __future__ import annotations
from pathlib import Path
from typing import Any


def load_model(path_or_url: str) -> Any:
    """Load a model from a local path or HTTP URL.

    Dispatch is based on file extension:

    * ``.pt`` / ``.pth`` → ``torch.load``
    * ``.onnx`` → ``onnxruntime.InferenceSession``
    * ``.pkl`` / ``.joblib`` → ``joblib.load``
    * anything else → ``joblib.load`` (generic pickle fallback)

    All ML framework imports are lazy — this function is the ONLY place
    they are imported.

    Args:
        path_or_url: Absolute local path or HTTP(S) URL to the model
            artefact.

    Returns:
        The loaded model object (framework-specific).

    Raises:
        ValueError: If the URL scheme or file extension is unsupported.
        ImportError: If the required ML framework is not installed.
        FileNotFoundError: If a local path does not exist.
    """
    resolved_path = _resolve_path(path_or_url)
    ext = Path(resolved_path).suffix.lower()
    if ext in ('.pt', '.pth'):
        return _load_torch(resolved_path)
    if ext == '.onnx':
        return _load_onnx(resolved_path)
    return _load_joblib(resolved_path)
