"""Numbers the browser preview must share with the server mix graph."""

EQ_HZ = {"low": 120, "mid": 1000, "high": 8000}
EQ_Q = {"low": 1.5, "mid": 2.5, "high": 4.0}
LIVE_LU_TOLERANCE = 0.5
APPROX_LU_TOLERANCE = 1.5

FIDELITY = {
    "eq": "live",
    "highpass": "live",
    "lowpass": "live",
    "widen": "live",
    "pan": "live",
    "delay": "live",
    "reverb": "live",
    "compress": "approx",
    "limiter": "approx",
    "loudness": "approx",
    "pitch": "render",
    "tempo": "render",
    "ai_denoise": "render",
    "ai_vocal": "render",
    "ai_remaster": "render",
    "regen_extend": "render",
    "regen_remelt": "render",
    "regen_same_style": "render",
}
