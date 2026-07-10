"""验证码图片校验与 OCR 识别。"""

import logging
import re
from collections import Counter
from collections.abc import Callable
from io import BytesIO
from typing import Protocol

import ddddocr
from PIL import Image, ImageSequence, UnidentifiedImageError

CAPTCHA_LENGTH = 4
CAPTCHA_RE = re.compile(r"^[A-Za-z0-9]{4}$")
OCR_CORRECTIONS = str.maketrans({"y": "7", "9": "r", "E": "F"})

log = logging.getLogger(__name__)


class OCRClassifier(Protocol):
    def classification(self, img: bytes) -> str: ...


CaptchaSolver = Callable[[bytes], str]


def verify_image_bytes(image_bytes: bytes) -> bool:
    """验证字节内容是否为 Pillow 可读取的完整图片。"""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError):
        return False
    return True


class CaptchaRecognizer:
    """组合整图、分割字符和动画帧结果识别四位验证码。"""

    def __init__(self, classifier: OCRClassifier | None = None) -> None:
        self._classifier = classifier

    def _get_classifier(self) -> OCRClassifier:
        if self._classifier is None:
            self._classifier = ddddocr.DdddOcr(show_ad=False, beta=True)
        return self._classifier

    @staticmethod
    def normalize(text: str) -> str:
        corrected = text.strip().replace(" ", "").translate(OCR_CORRECTIONS)
        return "".join(
            character
            for character in corrected
            if character.isascii() and character.isalnum()
        ).lower()

    def _ocr_image(self, image: Image.Image) -> str:
        enlarged = image.resize(
            (image.width * 2, image.height * 2),
            Image.Resampling.NEAREST,
        )
        buffer = BytesIO()
        enlarged.save(buffer, format="PNG")
        result = self._get_classifier().classification(buffer.getvalue())
        return self.normalize(result)

    def _split_characters(self, image: Image.Image) -> list[str]:
        width, height = image.size
        character_width = width // CAPTCHA_LENGTH
        characters: list[str] = []
        for index in range(CAPTCHA_LENGTH):
            right = (
                width if index == CAPTCHA_LENGTH - 1 else (index + 1) * character_width
            )
            crop = image.crop((index * character_width, 0, right, height))
            result = self._ocr_image(crop)
            characters.append(result[:1])
        return characters

    def _recover_first_character(
        self,
        frames: list[Image.Image],
        characters: list[str],
    ) -> None:
        if characters[0]:
            return

        candidates: list[str] = []
        for frame in frames[:3]:
            width, height = frame.size
            for ratio in (4, 3):
                crop = frame.crop((0, 0, width // ratio, height))
                result = self._ocr_image(crop)
                if result:
                    candidates.append(result[0])
        if candidates:
            characters[0] = Counter(candidates).most_common(1)[0][0]

    @staticmethod
    def select_result(full_code: str, split_code: str) -> str:
        if CAPTCHA_RE.fullmatch(full_code) is not None:
            return full_code
        if CAPTCHA_RE.fullmatch(split_code) is not None:
            return split_code
        return ""

    def __call__(self, image_bytes: bytes) -> str:
        with Image.open(BytesIO(image_bytes)) as image:
            frames = [frame.convert("L") for frame in ImageSequence.Iterator(image)]
        if not frames:
            return ""

        full_code = self._ocr_image(frames[0])
        split_characters = self._split_characters(frames[0])
        self._recover_first_character(frames, split_characters)
        split_code = "".join(split_characters)
        selected = self.select_result(full_code, split_code)
        log.debug(
            "验证码 OCR：full=%r split=%r selected=%r",
            full_code,
            split_code,
            selected,
        )
        return selected
