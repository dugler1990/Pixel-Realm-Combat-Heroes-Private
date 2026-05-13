from PIL import Image
import numpy as np
import os
import sys

def remove_white_bg(px, tol=35):
    white = (px[:,:,0] > 255 - tol) & (px[:,:,1] > 255 - tol) & (px[:,:,2] > 255 - tol)
    px[white, 3] = 0
    return px

def process_folder(folder_path, tol=35):
    print("📂 Folder:", folder_path)
    if not os.path.exists(folder_path):
        print("❌ Folder does not exist")
        return

    files = os.listdir(folder_path)
    print("📄 Files found:", files)

    out_dir = os.path.join(folder_path, "cleaned")
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for file in files:
        if not file.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        print("🖼 Processing:", file)
        in_path = os.path.join(folder_path, file)
        out_path = os.path.join(out_dir, os.path.splitext(file)[0] + ".png")

        img = Image.open(in_path).convert("RGBA")
        px = np.array(img)
        px = remove_white_bg(px, tol)
        Image.fromarray(px).save(out_path)
        count += 1

    print(f"✅ Done. Processed {count} images.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python remove_bg.py <folder_path>")
    else:
        tol = int(sys.argv[2]) if len(sys.argv) > 2 else 35
        process_folder(sys.argv[1], tol)
