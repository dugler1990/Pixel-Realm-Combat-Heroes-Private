from PIL import Image
from pathlib import Path

src = Path("/home/fresh/projects/Pixel-Realm-Combat-Heroes-public/Graphics/barb/up_idle/0.png")

dst_dir = Path("/home/fresh/projects/Pixel-Realm-Combat-Heroes-public/Graphics/misc")
dst_dir.mkdir(parents=True, exist_ok=True)

img = Image.open(src).convert("RGBA")

# create white background
bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
img = Image.alpha_composite(bg, img).convert("RGB")

# upscale
img = img.resize((1024, 1024), Image.NEAREST)

dst = dst_dir / "0_upscaled.png"
img.save(dst)

print(dst)