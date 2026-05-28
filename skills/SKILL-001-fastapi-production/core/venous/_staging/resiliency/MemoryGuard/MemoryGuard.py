from __future__ import annotations


class MemoryGuard:
    """Check GPU memory utilisation before allowing inference.

    Attributes:
        threshold: Maximum fractional utilisation (0.0–1.0) before
            inference is blocked.  Configurable via
            ``settings.GPU_MEMORY_THRESHOLD_PCT``.
    """

    def __init__(self, threshold: float | None=None) -> None:
        """Initialise the guard with a memory threshold.

        Args:
            threshold: Override for ``settings.GPU_MEMORY_THRESHOLD_PCT``.
                When ``None``, reads from settings at call time.
        """
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        """Active threshold (0.0–1.0)."""
        if self._threshold is not None:
            return self._threshold
        return settings.GPU_MEMORY_THRESHOLD_PCT

    def check(self, device=None) -> None:
        """Assert GPU memory utilisation is below threshold.

        No-op on CPU or when torch is absent.  Raises ``RuntimeError``
        when utilisation exceeds ``self.threshold``.

        Args:
            device: A ``torch.device`` to check.  When ``None`` the
                check is a no-op.

        Raises:
            RuntimeError: When GPU memory utilisation exceeds the
                configured threshold.
        """
        if device is None:
            return
        try:
            if not hasattr(device, 'type') or device.type != 'cuda':
                return
            import torch
            reserved = torch.cuda.memory_reserved(device)
            if reserved == 0:
                return
            allocated = torch.cuda.memory_allocated(device)
            utilisation = allocated / reserved
            logger.debug('GPU memory utilisation', extra={'utilisation_pct': round(utilisation * 100, 2)})
            if utilisation > self.threshold:
                raise RuntimeError(f'GPU memory utilisation {utilisation:.1%} exceeds threshold {self.threshold:.1%} — inference blocked')
        except RuntimeError:
            raise
        except Exception:
            pass
