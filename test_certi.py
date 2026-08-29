import io
import os
import subprocess
import platform
from datetime import datetime

import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

from config import (
    CERTIFICATE_TEMPLATE_PATH,
    CERT_FONT_PATH,
    CERT_FONT_SIZE,
    CERT_TEXT_COLOR
)


# ---------------------------------------------------------
# SAMPLE DATA FOR TESTING
# ---------------------------------------------------------

SAMPLE_NAME = "Vijay Sarathi R S"
SAMPLE_COURSE = "Agentic AI Workshop"
SAMPLE_DATE = datetime.now().strftime("%B %d, %Y")
SAMPLE_CODE = "1234567890"


# ---------------------------------------------------------
# OPEN PDF AUTOMATICALLY
# ---------------------------------------------------------

def open_pdf(pdf_path):
    """Open the generated PDF using the system's default viewer."""

    try:
        if platform.system() == "Windows":
            os.startfile(pdf_path)

        elif platform.system() == "Darwin":
            subprocess.run(["open", pdf_path])

        else:
            subprocess.run(["xdg-open", pdf_path])

    except Exception as e:
        print(f"Could not automatically open PDF: {e}")


# ---------------------------------------------------------
# DRAW CENTERED TEXT
# ---------------------------------------------------------

def draw_centered(draw, text, pos, font, fill):

    bbox = draw.textbbox((0, 0), text, font=font)

    text_width = bbox[2] - bbox[0]

    x = pos[0] - (text_width // 2)

    draw.text(
        (x, pos[1]),
        text,
        fill=fill,
        font=font
    )


# ---------------------------------------------------------
# CREATE PREVIEW CERTIFICATE
# ---------------------------------------------------------

def create_preview(coords):

    img = Image.open(CERTIFICATE_TEMPLATE_PATH).convert("RGB")

    draw = ImageDraw.Draw(img)

    # Load fonts
    try:
        # Name — largest, the visual focal point (increased)
        font = ImageFont.truetype(
            str(CERT_FONT_PATH),
            int(CERT_FONT_SIZE * 1.50)
        )

        # Course — increased, but smaller than the name
        course_font = ImageFont.truetype(
            str(CERT_FONT_PATH),
            int(CERT_FONT_SIZE * 1.00)
        )

        # Date — unchanged, same size as original
        small_font = ImageFont.truetype(
            str(CERT_FONT_PATH),
            int(CERT_FONT_SIZE * 0.70)
        )

        # Verification code — unchanged, same size as original
        code_font = ImageFont.truetype(
            str(CERT_FONT_PATH),
            int(CERT_FONT_SIZE * 0.70)
        )

    except Exception:
        font = ImageFont.load_default()
        course_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        code_font = ImageFont.load_default()

    # -----------------------------------------
    # DRAW SAMPLE CERTIFICATE
    # -----------------------------------------

    draw_centered(
        draw,
        SAMPLE_NAME,
        coords["name"],
        font,
        CERT_TEXT_COLOR
    )

    draw_centered(
        draw,
        f"{SAMPLE_COURSE}",
        coords["course"],
        course_font,
        CERT_TEXT_COLOR
    )

    draw_centered(
        draw,
        f"Date of Issue: {SAMPLE_DATE}",
        coords["date"],
        small_font,
        CERT_TEXT_COLOR
    )

    draw_centered(
        draw,
        f"Verification Code: {SAMPLE_CODE}",
        coords["code"],
        code_font,
        CERT_TEXT_COLOR
    )

    return img


# ---------------------------------------------------------
# SAVE IMAGE AS PDF
# ---------------------------------------------------------

def save_pdf(img, output_path):

    img.save(
        output_path,
        "PDF",
        resolution=100.0
    )

    print(f"\nPDF saved to:")
    print(output_path)


# ---------------------------------------------------------
# CALIBRATION
# ---------------------------------------------------------

def calibrate():

    img = Image.open(CERTIFICATE_TEMPLATE_PATH)

    print("\n==========================================")
    print("       CERTIFICATE TEMPLATE CALIBRATOR")
    print("==========================================\n")

    print("Template size:")
    print(f"Width  : {img.width}px")
    print(f"Height : {img.height}px\n")

    print("You will click the CENTER of each text area.")
    print()
    print("Click in this order:")
    print("1. Student Name")
    print("2. Course")
    print("3. Date")
    print("4. Verification Code")
    print()

    # -----------------------------------------------------
    # CREATE FIGURE
    # -----------------------------------------------------

    fig, ax = plt.subplots(figsize=(14, 9))

    ax.imshow(img)

    ax.set_title(
        "Click: 1) Name   2) Course   3) Date   4) Verification Code",
        fontsize=14
    )

    ax.axis("on")

    # -----------------------------------------------------
    # GET 4 CLICKS
    # -----------------------------------------------------

    coords_list = plt.ginput(
        4,
        timeout=0
    )

    plt.close(fig)

    if len(coords_list) != 4:

        print("\nERROR: You must click exactly 4 positions.")

        return

    coords = {
        "name": coords_list[0],
        "course": coords_list[1],
        "date": coords_list[2],
        "code": coords_list[3]
    }

    # -----------------------------------------------------
    # PRINT POSITIONS
    # -----------------------------------------------------

    print("\n==========================================")
    print("             SELECTED POSITIONS")
    print("==========================================\n")

    print(f"Name             : {coords['name']}")
    print(f"Course           : {coords['course']}")
    print(f"Date             : {coords['date']}")
    print(f"Verification Code: {coords['code']}")

    # -----------------------------------------------------
    # CREATE PREVIEW
    # -----------------------------------------------------

    print("\nGenerating preview certificate...")

    preview = create_preview(coords)

    # -----------------------------------------------------
    # SHOW PREVIEW WITH POSITION MARKERS
    # -----------------------------------------------------

    preview_with_markers = preview.copy()

    marker_draw = ImageDraw.Draw(preview_with_markers)

    labels = [
        ("NAME", coords["name"]),
        ("COURSE", coords["course"]),
        ("DATE", coords["date"]),
        ("CODE", coords["code"])
    ]

    for label, position in labels:

        x, y = position

        # Crosshair
        marker_draw.line(
            [(x - 15, y), (x + 15, y)],
            fill="red",
            width=2
        )

        marker_draw.line(
            [(x, y - 15), (x, y + 15)],
            fill="red",
            width=2
        )

        marker_draw.text(
            (x + 10, y - 25),
            label,
            fill="red"
        )

    # -----------------------------------------------------
    # DISPLAY RESULT
    # -----------------------------------------------------

    plt.figure(figsize=(14, 9))

    plt.imshow(preview_with_markers)

    plt.title(
        "Certificate Preview — Red Crosses Show Text Centers",
        fontsize=14
    )

    plt.axis("off")

    plt.show()

    # -----------------------------------------------------
    # SAVE TEST PDF
    # -----------------------------------------------------

    output_path = "certificate_test.pdf"

    save_pdf(
        preview,
        output_path
    )

    # -----------------------------------------------------
    # OPEN PDF
    # -----------------------------------------------------

    open_pdf(output_path)

    # -----------------------------------------------------
    # PRINT CONFIG VALUES
    # -----------------------------------------------------

    print("\n==========================================")
    print("       COPY THESE INTO config.py")
    print("==========================================\n")

    print(
        f"CERT_NAME_POS   = ({coords['name'][0]:.2f}, "
        f"{coords['name'][1]:.2f})"
    )

    print(
        f"CERT_COURSE_POS = ({coords['course'][0]:.2f}, "
        f"{coords['course'][1]:.2f})"
    )

    print(
        f"CERT_DATE_POS   = ({coords['date'][0]:.2f}, "
        f"{coords['date'][1]:.2f})"
    )

    print(
        f"CERT_CODE_POS   = ({coords['code'][0]:.2f}, "
        f"{coords['code'][1]:.2f})"
    )

    print("\n==========================================")
    print("             CALIBRATION DONE")
    print("==========================================\n")


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

if __name__ == "__main__":
    calibrate()