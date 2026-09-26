"""Human-friendly API errors. Stack traces are logged server-side, never returned."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


# Friendly copy for pipeline / job failures (shown on the processing page).
JOB_ERRORS = {
    "AI_NOT_CONNECTED": "AI analysis engine abhi connected nahi hai. Aapka video process ho gaya, lekin technique analysis abhi available nahi hai — isliye koi score nahi banaya gaya.",
    "VIDEO_PROCESSING_FAILED": "Video process nahi ho paya. Koi dusra clip try karein (MP4/MOV, 5–20 second).",
    "PLAYER_NOT_FOUND": "Video mein player saaf nahi dikh raha. Poora body frame mein rakhkar dobara record karein.",
    "AI_FAILED": "AI analysis beech mein ruk gaya. Thodi der baad dobara try karein.",
    "TIMEOUT": "Analysis mein zyada time lag gaya aur ise rok diya gaya. Dobara try karein.",
    "INTERNAL": "Kuch gadbad ho gayi. Thodi der baad dobara try karein.",
}
