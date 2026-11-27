"""Localized screen copy for the LAN photo invitation."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import features

WELCOME_LANGUAGE_ENV = "INKY_STUDIO_WELCOME_LANGUAGE"
DEFAULT_WELCOME_LANGUAGE = "fr"
FONT_DIR = Path(__file__).with_name("fonts")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WelcomeCopy:
    headline: tuple[str, str]
    instructions: tuple[str, str, str]
    compact: tuple[str, str]
    subset: bool = False
    direction: str | None = None


WELCOME_COPY = {
    "ar": WelcomeCopy(
        ("جاهز", "لعرض صورك"), ("افتح Inky Studio", "على iPhone", "وامسح رمز QR."),
        ("امسح رمز QR", "باستخدام iPhone"), subset=True, direction="rtl",
    ),
    "de": WelcomeCopy(
        ("Bereit für", "deine Fotos"), ("Öffne Inky Studio", "auf deinem iPhone", "und scanne den QR-Code."),
        ("QR-Code scannen", "mit deinem iPhone"),
    ),
    "en": WelcomeCopy(
        ("Ready for", "your photos"), ("Open Inky Studio", "on your iPhone", "and scan this QR code."),
        ("Scan this QR code", "with your iPhone"),
    ),
    "es": WelcomeCopy(
        ("Listo para", "tus fotos"), ("Abre Inky Studio", "en tu iPhone", "y escanea este código QR."),
        ("Escanea este QR", "con tu iPhone"),
    ),
    "fr": WelcomeCopy(
        ("Prêt pour", "vos photos"), ("Ouvrez Inky Studio", "sur votre iPhone", "et scannez ce QR."),
        ("Scannez ce QR", "avec votre iPhone"),
    ),
    "it": WelcomeCopy(
        ("Pronto per", "le tue foto"), ("Apri Inky Studio", "sul tuo iPhone", "e scansiona il QR."),
        ("Scansiona il QR", "con il tuo iPhone"),
    ),
    "ja": WelcomeCopy(
        ("写真を表示", "できます"), ("iPhoneで", "Inky Studioを開き", "QRコードを読み取ります。"),
        ("QRコードを", "iPhoneで読み取る"), subset=True,
    ),
    "ko": WelcomeCopy(
        ("사진을 표시할", "준비가 됐어요"), ("iPhone에서", "Inky Studio를 열고", "QR 코드를 스캔하세요."),
        ("iPhone으로", "QR 코드 스캔"), subset=True,
    ),
    "pt": WelcomeCopy(
        ("Pronto para", "as suas fotos"), ("Abra o Inky Studio", "no seu iPhone", "e digitalize este QR."),
        ("Digitalize este QR", "com o seu iPhone"),
    ),
    "zh-Hans": WelcomeCopy(
        ("准备好", "展示你的照片"), ("在 iPhone 上", "打开 Inky Studio", "然后扫描二维码。"),
        ("用 iPhone", "扫描二维码"), subset=True,
    ),
    "zh-Hant": WelcomeCopy(
        ("準備好", "展示你的照片"), ("在 iPhone 上", "開啟 Inky Studio", "然後掃描 QR 碼。"),
        ("用 iPhone", "掃描 QR 碼"), subset=True,
    ),
}


EXPIRED_COPY = {
    "ar": "انتهت صلاحية رمز QR",
    "de": "QR-Code abgelaufen",
    "en": "QR code expired",
    "es": "Código QR caducado",
    "fr": "QR expiré",
    "it": "Codice QR scaduto",
    "ja": "QRコードの有効期限切れ",
    "ko": "QR 코드 만료",
    "pt": "Código QR expirado",
    "zh-Hans": "二维码已过期",
    "zh-Hant": "QR 碼已過期",
}


def welcome_font(language: str, *, bold: bool) -> Path | None:
    if not WELCOME_COPY[language].subset:
        return None
    style = "Bold" if bold else "Regular"
    return FONT_DIR / f"InkyWelcome-{language}-{style}.ttf"


def resolve_welcome_language(requested: str | None) -> str:
    """Accept canonical, known tags only. Retain French for old images."""
    if requested is None or requested not in WELCOME_COPY:
        return DEFAULT_WELCOME_LANGUAGE
    copy = WELCOME_COPY[requested]
    if copy.direction == "rtl" and not all(features.check_feature(name) for name in ("raqm", "fribidi")):
        logger.warning("Welcome language unavailable, using French: Arabic shaping libraries are missing")
        return DEFAULT_WELCOME_LANGUAGE
    if copy.subset and not all((font := welcome_font(requested, bold=bold)) and font.is_file() for bold in (False, True)):
        logger.warning("Welcome language unavailable, using French: packaged font for %s is missing", requested)
        return DEFAULT_WELCOME_LANGUAGE
    return requested
