"""Split a stereo mix into a vocal and an instrumental with a source-separation model.

Optional: it needs `pip install -e ".[separate]"` (PyTorch and Demucs). The model's weights
(about 80 MB) download the first time it runs; after that it works offline. The audio never
leaves this computer.

The split is an estimate. It leaves some of the beat in the vocal, takes some of the vocal's
low end and reverb with it, and gates quiet gaps. vocal.py measures what's left, so its
numbers are rougher than the same measurements on stems exported from the session.
"""
import importlib.util
import os
from math import gcd

import numpy as np
from scipy.signal import resample_poly

MODEL_NAME = "htdemucs"
MODEL_RATE = 44100  # the rate the model works at; the vocal and instrumental come back at it
_model = {}


class SeparationUnavailable(RuntimeError):
    """The split can't run right now; the message says why, in plain words."""


def available():
    """(True, "") when a mix can be split, else (False, reason)."""
    if os.environ.get("MIXCHECK_SEPARATION", "").lower() in ("0", "off", "false", "no"):
        return False, "Vocal splitting is turned off (MIXCHECK_SEPARATION=off)."
    if any(importlib.util.find_spec(pkg) is None for pkg in ("torch", "demucs")):
        return False, 'Vocal splitting needs the optional packages: pip install -e ".[separate]"'
    return True, ""


def _device(torch):
    wanted = os.environ.get("MIXCHECK_DEVICE")
    if wanted:
        return wanted
    # CPU unless there is a CUDA card: the model's Apple GPU (mps) support is still patchy.
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_model():
    if "model" not in _model:
        from demucs.pretrained import get_model
        try:
            model = get_model(MODEL_NAME)
        except Exception as exc:  # the first run downloads the weights
            raise SeparationUnavailable(
                "Couldn't load the vocal-splitting model. The first run downloads it (about 80 MB), "
                "so check your internet connection and try again."
            ) from exc
        model.eval()
        _model["model"] = model
    return _model["model"]


def _resample(x, fs):
    """(samples, channels) at fs -> (samples, 2) at MODEL_RATE."""
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    if fs != MODEL_RATE:
        g = gcd(int(fs), MODEL_RATE)
        x = resample_poly(x, MODEL_RATE // g, int(fs) // g, axis=0)
    return x


def separate_vocals(x, fs):
    """(vocals, instrumental, rate): both (samples, 2) float64 at `rate` (MODEL_RATE)."""
    ok, why = available()
    if not ok:
        raise SeparationUnavailable(why)
    import torch
    from demucs.apply import apply_model

    model = _load_model()
    mix = _resample(x, fs)
    wav = torch.from_numpy(np.ascontiguousarray(mix.T, dtype=np.float32))
    # The same loudness normalization Demucs applies itself, undone afterwards.
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        sources = apply_model(model, ((wav - mean) / std)[None], device=_device(torch),
                              shifts=0, split=True, overlap=0.25, progress=False)[0]
    vocals = (sources[model.sources.index("vocals")] * std + mean).cpu().numpy().T.astype(np.float64)
    return vocals, mix - vocals, MODEL_RATE
