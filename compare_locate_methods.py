import argparse
import time
import os
import sys
from typing import Optional, Tuple

import numpy as np
from PIL import Image
import pyautogui
import pyscreeze
import cv2
import imutils

# Ensure project root is on sys.path for "utils" imports when run directly
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.image_recognition import locate_center_on_phone, BEST_SCALES  # noqa: E402


def parse_region(region_str: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    if not region_str:
        return None
    parts = [p.strip() for p in region_str.split(",")]
    if len(parts) != 4:
        raise ValueError("Region must be in the form 'x,y,w,h'")
    x, y, w, h = map(int, parts)
    return x, y, w, h


def get_screenshot_rgb() -> np.ndarray:
    """Get a screenshot as an RGB numpy array.

    Uses ADB phone screenshot if available; otherwise falls back to desktop.
    """
    # Lazy import to avoid hard dependency if not needed
    try:
        from utils.adb_utils import get_adb_controller  # type: ignore

        controller = get_adb_controller()
        if controller and controller.is_connected():
            shot = controller.take_screenshot()  # expected RGB numpy array
            shot = cv2.cvtColor(shot, cv2.COLOR_RGB2BGR)
            cv2.imwrite("shot.png", shot)

            if shot is not None:
                return shot
    except Exception:
        # Fall through to desktop screenshot
        pass

    # Desktop screenshot via pyautogui (PIL Image) -> numpy RGB
    desktop_img = pyautogui.screenshot()
    return np.array(desktop_img.convert("RGB"))


def compute_opencv_max_confidence(
    template_path: str,
    haystack_rgb: np.ndarray,
    region: Optional[Tuple[int, int, int, int]] = None,
    scale: float = 1.0,
) -> Optional[float]:
    """Compute TM_CCOEFF_NORMED max confidence using OpenCV.

    - Expects haystack in RGB; converts to BGR for OpenCV
    - Crops to region if provided
    - Optionally rescales haystack by `scale` (like phone method)
    """
    try:
        template_bgr = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template_bgr is None:
            return None

        haystack_bgr = cv2.cvtColor(haystack_rgb, cv2.COLOR_RGB2BGR)
        if region:
            x, y, w, h = region
            haystack_bgr = haystack_bgr[y : y + h, x : x + w]

        if scale != 1.0:
            new_width = max(1, int(haystack_bgr.shape[1] * scale))
            haystack_bgr = imutils.resize(haystack_bgr, width=new_width)

        tH, tW = template_bgr.shape[:2]
        if haystack_bgr.shape[0] < tH or haystack_bgr.shape[1] < tW:
            return None

        result = cv2.matchTemplate(haystack_bgr, template_bgr, cv2.TM_CCOEFF_NORMED)
        minVal, maxVal, minLoc, maxLoc = cv2.minMaxLoc(result)
        return float(maxVal)
    except Exception:
        return None


def run_pyautogui_locate(
    template_path: str,
    haystack_rgb: np.ndarray,
    confidence: float,
    region: Optional[Tuple[int, int, int, int]] = None,
):
    """Run pyautogui.locate on the provided screenshot and template.

    Returns (box, center, elapsed_seconds) where box is (left, top, width, height)
    or None if not found; center is a tuple or None.
    """
    start = time.perf_counter()

    # Prepare images for pyautogui (PIL)
    haystack_pil = Image.fromarray(haystack_rgb)
    template_pil = Image.open(template_path).convert("RGB")

    origin_x = 0
    origin_y = 0
    if region:
        x, y, w, h = region
        haystack_pil = haystack_pil.crop((x, y, x + w, y + h))
        origin_x, origin_y = x, y

    try:
        match = pyautogui.locate(template_path, haystack_rgb, confidence=confidence)
    except pyscreeze.ImageNotFoundException:
        match = None
    elapsed = time.perf_counter() - start

    if match is None:
        return None, None, elapsed

    left, top, width, height = match.left + origin_x, match.top + origin_y, match.width, match.height
    center = (left + width // 2, top + height // 2)
    return (left, top, width, height), center, elapsed


def run_phone_method(
    template_path: str,
    confidence: float,
    min_search_time: float,
    region: Optional[Tuple[int, int, int, int]] = None,
):
    """Call current locate_center_on_phone() and time it.

    Returns (center, elapsed_seconds) where center is (x, y) or None.
    """
    start = time.perf_counter()
    center_point = locate_center_on_phone(
        template_path=template_path,
        confidence=confidence,
        min_search_time=min_search_time,
        region=region,
    )
    elapsed = time.perf_counter() - start

    if center_point is None:
        return None, elapsed

    return (center_point.x, center_point.y), elapsed


def main():
    parser = argparse.ArgumentParser(
        description="Compare pyautogui.locate vs current locate_center_on_phone()"
    )
    parser.add_argument("template", help="Path to the template image to find")
    parser.add_argument(
        "--confidence", type=float, default=0.8, help="Template match confidence (0-1)"
    )
    parser.add_argument(
        "--min-search-time",
        type=float,
        default=0.5,
        help="Minimum search time for phone method (seconds)",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Optional search region as 'x,y,w,h'",
    )

    args = parser.parse_args()
    region = parse_region(args.region)

    if not os.path.isfile(args.template):
        print(f"[ERROR] Template not found: {args.template}")
        sys.exit(1)

    # 1) Phone method (current implementation)
    # phone_center, phone_elapsed = run_phone_method(
    #     template_path=args.template,
    #     confidence=args.confidence,
    #     min_search_time=args.min_search_time,
    #     region=region,
    # )

    # 2) pyautogui.locate on the same scene (single screenshot)
    scene_rgb = get_screenshot_rgb()
    pya_box, pya_center, pya_elapsed = run_pyautogui_locate(
        template_path=args.template,
        haystack_rgb=scene_rgb,
        confidence=args.confidence,
        region=region,
    )

    # Output summary
    print("\n=== Comparison ===")
    print("- Template:", args.template)
    print(f"- Confidence: {args.confidence}")
    print(f"- Region: {region if region else 'full image'}")

    # print("\nCurrent phone method (locate_center_on_phone):")
    # if phone_center is None:
    #     print(f"  Result: NOT FOUND  | Time: {phone_elapsed:.3f}s")
    # else:
    #     print(f"  Center: {phone_center} | Time: {phone_elapsed:.3f}s")

    print("\npyautogui.locate (searching in single captured screenshot):")
    if pya_center is None:
        print(f"  Result: NOT FOUND  | Time: {pya_elapsed:.3f}s")
    else:
        print(
            f"  Box: {pya_box} | Center: {pya_center} | Time: {pya_elapsed:.3f}s"
        )

    # Compute confidences on the single captured screenshot
    # phone_like_conf = compute_opencv_max_confidence(
    #     template_path=args.template,
    #     haystack_rgb=scene_rgb,
    #     region=region,
    #     scale=BEST_SCALES if isinstance(BEST_SCALES, (int, float)) else 1.0,
    # )
    # pya_conf = compute_opencv_max_confidence(
    #     template_path=args.template,
    #     haystack_rgb=scene_rgb,
    #     region=region,
    #     scale=1.0,
    # )

    # if phone_center and pya_center:
    #     dx = abs(phone_center[0] - pya_center[0])
    #     dy = abs(phone_center[1] - pya_center[1])
    #     print(f"\nCenter delta: dx={dx}, dy={dy}")

    # Confidence reporting
    # print("\nConfidences (single screenshot analysis):")
    # if phone_like_conf is not None:
    #     print(f"  Phone-like (OpenCV, scale={BEST_SCALES}): {phone_like_conf:.3f}")
    # else:
    #     print("  Phone-like (OpenCV): N/A")
    # if pya_conf is not None:
    #     print(f"  PyAutoGUI (OpenCV, native scale): {pya_conf:.3f}")
    # else:
    #     print("  PyAutoGUI confidence: N/A")


if __name__ == "__main__":
    main()


