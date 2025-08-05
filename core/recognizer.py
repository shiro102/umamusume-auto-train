import json

import cv2
import numpy as np
from PIL import ImageGrab, ImageStat

from utils.screenshot import capture_region
from utils.adb_utils import get_adb_controller


def match_template(template_path, region=None, threshold=0.85, debug=False):
    # Check if usePhone is enabled
    try:
        with open("config.json", "r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError:
        config = {"usePhone": False}

    USE_PHONE = config.get("usePhone", False)

    if USE_PHONE:
        # Use ADB screenshot for phone mode
        try:
            controller = get_adb_controller()
            if controller and controller.is_connected():
                # Take full screenshot from phone
                screen = controller.take_screenshot()

                if screen is not None:
                    # Convert RGB to BGR for OpenCV
                    screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

                    # Extract region if specified
                    if region:
                        x, y, w, h = region
                        screen = screen[y : y + h, x : x + w]
                        # Load template
                    template = cv2.imread(
                        template_path, cv2.IMREAD_COLOR
                    )  # safe default
                    if template.shape[2] == 4:
                        template = cv2.cvtColor(template, cv2.COLOR_BGRA2BGR)

                    if debug:
                        print(f"[DEBUG] Template loaded: {template_path}")
                        print(f"[DEBUG] Template size: {template.shape}")
                        print(f"[DEBUG] Screen size: {screen.shape}")

                    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)

                    # Get confidence levels for debugging
                    if debug:
                        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                        print(f"[DEBUG] Max confidence: {max_val:.4f}")
                        print(f"[DEBUG] Min confidence: {min_val:.4f}")
                        print(f"[DEBUG] Threshold: {threshold}")

                        # Save confidence map for debugging
                        cv2.imwrite(
                            "debug_confidence_map.png", (result * 255).astype(np.uint8)
                        )

                        # Save template for debugging
                        cv2.imwrite("debug_template.png", template)

                    loc = np.where(result >= threshold)
                    h, w = template.shape[:2]
                    boxes = [(x, y, w, h) for (x, y) in zip(*loc[::-1])]

                    if debug:
                        print(f"[DEBUG] Found {len(boxes)} matches above threshold")
                        for i, (x, y, w, h) in enumerate(boxes):
                            print(
                                f"[DEBUG] Match {i+1}: ({x}, {y}) with size ({w}, {h})"
                            )

                    return deduplicate_boxes(boxes)
                else:
                    print(
                        "[WARNING] Could not take ADB screenshot, falling back to desktop"
                    )
            else:
                print("[WARNING] ADB not connected, falling back to desktop screenshot")
        except Exception as e:
            print(f"[WARNING] ADB screenshot failed: {e}, falling back to desktop")

    # Fallback to desktop screenshot
    # Get screenshot
    if region:
        screen = np.array(ImageGrab.grab(bbox=region))  # (left, top, right, bottom)
    else:
        screen = np.array(ImageGrab.grab())

    screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

    cv2.imwrite("screen-match-template.png", screen)
    # Load template
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)  # safe default
    if template.shape[2] == 4:
        template = cv2.cvtColor(template, cv2.COLOR_BGRA2BGR)
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(result >= threshold)

    h, w = template.shape[:2]
    boxes = [(x, y, w, h) for (x, y) in zip(*loc[::-1])]

    return deduplicate_boxes(boxes)


def deduplicate_boxes(boxes, min_dist=5):
    filtered = []
    for x, y, w, h in boxes:
        cx, cy = x + w // 2, y + h // 2
        if all(
            abs(cx - (fx + fw // 2)) > min_dist or abs(cy - (fy + fh // 2)) > min_dist
            for fx, fy, fw, fh in filtered
        ):
            filtered.append((x, y, w, h))
    return filtered


def is_infirmary_active(REGION):
    screenshot = capture_region(REGION)
    grayscale = screenshot.convert("L")
    stat = ImageStat.Stat(grayscale)
    avg_brightness = stat.mean[0]

    # print(f"[DEBUG] Avg brightness: {avg_brightness}")

    # Treshold infirmary btn
    return avg_brightness > 150
