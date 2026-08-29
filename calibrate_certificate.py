from PIL import Image
import matplotlib.pyplot as plt
from config import CERTIFICATE_TEMPLATE_PATH

def calibrate():
    img = Image.open(CERTIFICATE_TEMPLATE_PATH)
    plt.figure(figsize=(12, 8))
    plt.imshow(img)
    plt.title("Click in order: 1) Name  2) Course  3) Date  4) Verification Code")
    print("Click 4 times on the image, then close the window.")
    coords = plt.ginput(4)
    print("\n# Paste these into config.py:")
    print(f"CERT_NAME_POS   = {coords[0]}")
    print(f"CERT_COURSE_POS = {coords[1]}")
    print(f"CERT_DATE_POS   = {coords[2]}")
    print(f"CERT_CODE_POS   = {coords[3]}")
    plt.show()

if __name__ == "__main__":
    calibrate()