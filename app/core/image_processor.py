"""
image_processor.py
==================
Production-grade image pre-processing pipeline optimised for architecture
diagram OCR on AMD Ryzen 7 7730U / 16 GB RAM (CPU-only).

Speed optimisations (v2.1):
  - Reduced preprocessing candidates from 5 → 2 (clahe_otsu + raw_gray).
    The extra 3 strategies rarely beat these two and triple OCR time.
  - Lowered MIN_LONG_EDGE_FOR_OCR from 2400 → 1600 px.  EasyOCR reads
    diagram text reliably at 1600 px; 2400 px increases inference time ~2.25×
    with marginal accuracy gain on typical architecture diagrams.
  - MAX_LONG_EDGE capped at 2200 px (was 4000 px).
  - _select_best_candidate now skips the probe scan when only 1 candidate
    is available and falls back immediately.
  - pin_memory warning suppressed via workers=0 (already set).

All other logic (denoising, CLAHE, normalisation, sharpening) is unchanged.
"""

import os
import cv2
import numpy as np


class ImageProcessor:

    # ------------------------------------------------------------------ #
    # Constants                                                            #
    # ------------------------------------------------------------------ #

    # Lowered from 2400 → 1600.  EasyOCR handles 1600 px reliably and
    # runs ~2× faster than at 2400 px for typical diagram images.
    MIN_LONG_EDGE_FOR_OCR: int = 1600

    # Lowered from 4000 → 2200 to avoid slow inference on large exports.
    MAX_LONG_EDGE: int = 2200

    # ------------------------------------------------------------------ #
    # Basic I/O                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def load_image(image_path: str):
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(
                f"Cannot load image: {image_path}"
            )
        return image

    # ------------------------------------------------------------------ #
    # Resizing                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def smart_resize(image):
        """
        Upscale small diagrams so OCR text is at least 20-30 px tall,
        then hard-cap at MAX_LONG_EDGE to avoid slow inference.
        """
        height, width = image.shape[:2]
        long_edge = max(height, width)

        if long_edge < ImageProcessor.MIN_LONG_EDGE_FOR_OCR:
            scale = ImageProcessor.MIN_LONG_EDGE_FOR_OCR / long_edge
            new_w = int(width * scale)
            new_h = int(height * scale)
            image = cv2.resize(
                image,
                (new_w, new_h),
                interpolation=cv2.INTER_CUBIC
            )
            height, width = new_h, new_w
            long_edge = max(height, width)

        if long_edge > ImageProcessor.MAX_LONG_EDGE:
            scale = ImageProcessor.MAX_LONG_EDGE / long_edge
            image = cv2.resize(
                image,
                (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_AREA
            )

        return image

    # ------------------------------------------------------------------ #
    # Individual enhancement primitives                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def to_gray(image):
        if len(image.shape) == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def normalise_background(gray):
        """
        Remove shadows / gradients with a large-kernel morphological
        background estimate and normalize to uniform white background.
        """
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (51, 51)
        )
        background = cv2.morphologyEx(
            gray, cv2.MORPH_DILATE, kernel
        )
        normalised = cv2.divide(gray, background, scale=255)
        return normalised

    @staticmethod
    def enhance_contrast_clahe(gray):
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    @staticmethod
    def unsharp_mask(gray, kernel_size=(3, 3), strength=1.5):
        """Mild sharpening to recover edges blurred by JPEG compression."""
        blurred = cv2.GaussianBlur(gray, kernel_size, 0)
        sharpened = cv2.addWeighted(gray, 1 + strength, blurred, -strength, 0)
        return sharpened

    @staticmethod
    def denoise(gray):
        return cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

    @staticmethod
    def threshold_otsu(gray):
        _, binary = cv2.threshold(
            gray, 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        return binary

    @staticmethod
    def threshold_adaptive(gray):
        return cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31, 11
        )

    @staticmethod
    def threshold_adaptive_mean(gray):
        return cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY,
            15, 8
        )

    # ------------------------------------------------------------------ #
    # Multi-pass strategy builder  (SPEED-OPTIMISED: 2 candidates only)   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_candidates(gray):
        """
        Return a list of (label, processed_image) tuples.

        Speed note: reduced from 5 candidates to 2.
          - clahe_otsu  : best for clean white-background diagrams (most common)
          - raw_gray    : EasyOCR handles greyscale natively; good fallback
        The three removed strategies (norm_adaptive, sharp_adaptive_mean,
        inverted_clahe) add ~3× more OCR time for marginal gains on typical
        architecture diagram exports.
        """
        candidates = []

        # Strategy 1 – light denoise + CLAHE + Otsu (best for white-bg diagrams)
        g1 = ImageProcessor.denoise(gray)
        g1 = ImageProcessor.enhance_contrast_clahe(g1)
        candidates.append(("clahe_otsu", ImageProcessor.threshold_otsu(g1)))

        # Strategy 2 – raw gray (EasyOCR handles greyscale well; fast fallback)
        candidates.append(("raw_gray", gray))

        return candidates

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def process_image(image_path: str):
        """
        Full pipeline.  Returns the single best preprocessed image
        (as a numpy array) for EasyOCR consumption.
        """
        image = ImageProcessor.load_image(image_path)
        image = ImageProcessor.smart_resize(image)
        gray  = ImageProcessor.to_gray(image)

        candidates = ImageProcessor._build_candidates(gray)
        best_image = ImageProcessor._select_best_candidate(candidates)

        if os.getenv("DEBUG", "false").lower() in ("1", "true", "yes"):
            cv2.imwrite("debug_processed.png", best_image)

        return best_image

    @staticmethod
    def _select_best_candidate(candidates):
        """
        Run EasyOCR on each candidate and pick the one that yields
        the highest (character_count * average_confidence) score.

        Speed note: with only 2 candidates this is fast; if there is
        exactly 1 candidate we skip the probe entirely.
        """
        if len(candidates) == 1:
            return candidates[0][1]

        try:
            import easyocr as _easyocr

            if not hasattr(ImageProcessor, "_probe_reader"):
                ImageProcessor._probe_reader = _easyocr.Reader(
                    ["en"],
                    gpu=False,
                    verbose=False
                )

            reader = ImageProcessor._probe_reader

            best_image = candidates[0][1]
            best_score = -1.0

            for label, img in candidates:
                try:
                    results = reader.readtext(
                        img,
                        detail=1,
                        paragraph=False,
                        width_ths=0.7,
                        height_ths=0.7,
                        decoder="greedy"
                    )
                    chars = sum(len(r[1]) for r in results if r[2] >= 0.10)
                    avg_conf = (
                        sum(r[2] for r in results if r[2] >= 0.10) / len(results)
                        if results else 0.0
                    )
                    score = chars * avg_conf
                    if score > best_score:
                        best_score = score
                        best_image = img
                except Exception:
                    continue

            return best_image

        except Exception:
            return candidates[0][1]

    @staticmethod
    def get_all_candidates(image_path: str):
        """
        Return all preprocessing candidates.  Used by OCREngine for
        multi-pass extraction.
        """
        image = ImageProcessor.load_image(image_path)
        image = ImageProcessor.smart_resize(image)
        gray  = ImageProcessor.to_gray(image)
        return ImageProcessor._build_candidates(gray)