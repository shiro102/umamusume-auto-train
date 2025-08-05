import cv2
import numpy as np
from PIL import Image
import json
import pyautogui
import os
import time
from datetime import datetime

# Load config
try:
    with open("config.json", "r", encoding="utf-8") as file:
        config = json.load(file)
except FileNotFoundError:
    config = {"usePhone": False}

USE_PHONE = config.get("usePhone", False)


def save_debug_image(
    screenshot,
    template,
    match_location,
    confidence,
    template_path,
    debug_dir="debug_images",
):
    """Save debug images for manual verification"""
    try:
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save the screenshot with detection area highlighted
        debug_screenshot = screenshot.copy()
        if match_location:
            x, y, w, h = match_location
            cv2.rectangle(debug_screenshot, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(
                debug_screenshot,
                f"Conf: {confidence:.3f}",
                (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

        screenshot_path = os.path.join(debug_dir, f"debug_screenshot_{timestamp}.png")
        cv2.imwrite(screenshot_path, debug_screenshot)

        # Save the template
        template_path_debug = os.path.join(debug_dir, f"debug_template_{timestamp}.png")
        cv2.imwrite(template_path_debug, template)

        print(f"[DEBUG] Saved debug images: {screenshot_path}, {template_path_debug}")

    except Exception as e:
        print(f"[DEBUG] Failed to save debug images: {e}")


def locate_center_on_screen(
    template_path, confidence=0.8, min_search_time=0.2, region=None
):
    """
    Locate template image on screen, works with both desktop and phone screenshots
    """
    if USE_PHONE:
        return locate_center_on_phone(
            template_path, confidence, min_search_time, region
        )
    else:
        return locate_center_on_desktop(
            template_path, confidence, min_search_time, region
        )


def locate_center_on_phone(
    template_path, confidence=0.8, min_search_time=1, region=None
):
    """Locate template image on phone screenshot using improved OpenCV + imutils"""
    try:
        from utils.adb_utils import get_adb_controller
        import imutils

        controller = get_adb_controller()

        if not controller or not controller.is_connected():
            print("[WARNING] ADB not connected, falling back to desktop")
            return locate_center_on_desktop(
                template_path, confidence, min_search_time, region
            )

        start_time = time.time()
        max_search_time = min_search_time

        while time.time() - start_time < max_search_time:
            # Take phone screenshot
            screenshot = controller.take_screenshot()

            # Convert RGB to BGR for cv2.imwrite
            if screenshot is None:
                print(
                    "[WARNING] Could not take phone screenshot, falling back to desktop"
                )
                return locate_center_on_desktop(
                    template_path, confidence, min_search_time, region
                )

            # Convert to OpenCV format
            screenshot_cv = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)

            # Load template
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is None:
                print(f"[ERROR] Could not load template: {template_path}")
                return None

            # Crop screenshot to region if specified
            if region:
                x, y, w, h = region
                screenshot_cv = screenshot_cv[y : y + h, x : x + w]

            # Use imutils for better template matching with multiple scales
            # This improves detection accuracy significantly
            (tH, tW) = template.shape[:2]

            # Try multiple scales for better detection
            scales = [0.8, 0.9, 1.0, 1.1, 1.2]
            best_match = None
            best_confidence = 0
            best_scale = 1.0

            for scale in scales:
                # Resize the image according to the scale
                resized = imutils.resize(
                    screenshot_cv, width=int(screenshot_cv.shape[1] * scale)
                )
                r = screenshot_cv.shape[1] / float(resized.shape[1])

                # If the resized image is smaller than the template, break
                if resized.shape[0] < tH or resized.shape[1] < tW:
                    break

                # Apply template matching
                result = cv2.matchTemplate(resized, template, cv2.TM_CCOEFF_NORMED)
                (_, maxVal, _, maxLoc) = cv2.minMaxLoc(result)

                # If we have found a new maximum correlation value, then update
                if maxVal > best_confidence:
                    best_confidence = maxVal
                    best_scale = scale
                    best_match = maxLoc
                    best_r = r

            # If we found a match above our confidence threshold
            if best_confidence >= confidence:
                # Calculate the center point
                (startX, startY) = (
                    int(best_match[0] * best_r),
                    int(best_match[1] * best_r),
                )
                (endX, endY) = (
                    int((best_match[0] + tW) * best_r),
                    int((best_match[1] + tH) * best_r),
                )

                center_x = startX + (endX - startX) // 2
                center_y = startY + (endY - startY) // 2

                # Adjust coordinates if region was specified
                if region:
                    center_x += region[0]
                    center_y += region[1]

                # print(
                #     f"[PHONE] Found {template_path} at ({center_x}, {center_y}) with confidence {best_confidence:.3f} (scale: {best_scale})"
                # )

                # Save debug images for manual verification
                if config.get("saveDebugImages", False):
                    match_location = (startX, startY, endX - startX, endY - startY)
                    save_debug_image(
                        screenshot_cv,
                        template,
                        match_location,
                        best_confidence,
                        template_path,
                    )

                return pyautogui.Point(center_x, center_y)

            # If no match found and we still have time, wait a bit before retrying
            if time.time() - start_time < max_search_time:
                time.sleep(0.05)  # Small delay between retries

        # If we reach here, no match was found within the time limit
        # print(f"[PHONE] {template_path} not found within {min_search_time}s (best confidence: {best_confidence:.3f})")
        return None

    except Exception as e:
        print(f"[PHONE] Image recognition error: {e}, falling back to desktop")
        return locate_center_on_desktop(
            template_path, confidence, min_search_time, region
        )


def locate_center_on_desktop(
    template_path, confidence=0.8, min_search_time=0.2, region=None
):
    """Locate template image on desktop screenshot using pyautogui"""
    try:
        if region:
            return pyautogui.locateCenterOnScreen(
                template_path,
                confidence=confidence,
                minSearchTime=min_search_time,
                region=region,
            )
        else:
            return pyautogui.locateCenterOnScreen(
                template_path, confidence=confidence, minSearchTime=min_search_time
            )
    except Exception as e:
        print(f"[DESKTOP] Image recognition error: {e}")
        return None


def locate_on_screen(template_path, confidence=0.8, min_search_time=0.2, region=None):
    """
    Locate template image on screen (returns full location), works with both desktop and phone screenshots
    """
    if USE_PHONE:
        return locate_on_phone(template_path, confidence, min_search_time, region)
    else:
        return locate_on_desktop(template_path, confidence, min_search_time, region)


def locate_on_phone(template_path, confidence=0.8, min_search_time=0.2, region=None):
    """Locate template image on phone screenshot using improved OpenCV + imutils"""
    try:
        from utils.adb_utils import get_adb_controller
        import imutils

        controller = get_adb_controller()

        if not controller or not controller.is_connected():
            print("[WARNING] ADB not connected, falling back to desktop")
            return locate_on_desktop(template_path, confidence, min_search_time, region)

        start_time = time.time()
        max_search_time = min_search_time

        while time.time() - start_time < max_search_time:
            # Take phone screenshot
            screenshot = controller.take_screenshot()
            if screenshot is None:
                print(
                    "[WARNING] Could not take phone screenshot, falling back to desktop"
                )
                return locate_on_desktop(
                    template_path, confidence, min_search_time, region
                )

            # Convert to OpenCV format
            screenshot_cv = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)

            # Load template
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is None:
                print(f"[ERROR] Could not load template: {template_path}")
                return None

            # Crop screenshot to region if specified
            if region:
                x, y, w, h = region
                screenshot_cv = screenshot_cv[y : y + h, x : x + w]

            # Use imutils for better template matching with multiple scales
            (tH, tW) = template.shape[:2]

            # Try multiple scales for better detection
            scales = [0.8, 0.9, 1.0, 1.1, 1.2]
            best_match = None
            best_confidence = 0
            best_scale = 1.0

            for scale in scales:
                # Resize the image according to the scale
                resized = imutils.resize(
                    screenshot_cv, width=int(screenshot_cv.shape[1] * scale)
                )
                r = screenshot_cv.shape[1] / float(resized.shape[1])

                # If the resized image is smaller than the template, break
                if resized.shape[0] < tH or resized.shape[1] < tW:
                    break

                # Apply template matching
                result = cv2.matchTemplate(resized, template, cv2.TM_CCOEFF_NORMED)
                (_, maxVal, _, maxLoc) = cv2.minMaxLoc(result)

                # If we have found a new maximum correlation value, then update
                if maxVal > best_confidence:
                    best_confidence = maxVal
                    best_scale = scale
                    best_match = maxLoc
                    best_r = r

            # If we found a match above our confidence threshold
            if best_confidence >= confidence:
                # Calculate the location
                (startX, startY) = (
                    int(best_match[0] * best_r),
                    int(best_match[1] * best_r),
                )
                (endX, endY) = (
                    int((best_match[0] + tW) * best_r),
                    int((best_match[1] + tH) * best_r),
                )

                left = startX
                top = startY
                width = endX - startX
                height = endY - startY

                # Adjust coordinates if region was specified
                if region:
                    left += region[0]
                    top += region[1]

                # print(
                #     f"[PHONE] Found {template_path} at ({left}, {top}, {width}, {height}) with confidence {best_confidence:.3f} (scale: {best_scale})"
                # )

                # Create a mock object similar to pyautogui's locate result
                class MockLocation:
                    def __init__(self, left, top, width, height):
                        self.left = left
                        self.top = top
                        self.width = width
                        self.height = height
                        self.x = left + width // 2
                        self.y = top + height // 2

                return MockLocation(left, top, width, height)

            # If no match found and we still have time, wait a bit before retrying
            if time.time() - start_time < max_search_time:
                time.sleep(0.05)  # Small delay between retries

        # If we reach here, no match was found within the time limit
        # print(f"[PHONE] {template_path} not found within {min_search_time}s (best confidence: {best_confidence:.3f})")
        return None

    except Exception as e:
        print(f"[PHONE] Image recognition error: {e}, falling back to desktop")
        return locate_on_desktop(template_path, confidence, min_search_time, region)


def locate_on_desktop(template_path, confidence=0.8, min_search_time=0.2, region=None):
    """Locate template image on desktop screenshot using pyautogui"""
    try:
        if region:
            return pyautogui.locateOnScreen(
                template_path,
                confidence=confidence,
                minSearchTime=min_search_time,
                region=region,
            )
        else:
            return pyautogui.locateOnScreen(
                template_path, confidence=confidence, minSearchTime=min_search_time
            )
    except Exception as e:
        print(f"[DESKTOP] Image recognition error: {e}")
        return None
