import os
import argparse
from PIL import Image

def scale_images_in_folder(folder_path, scaling_factor, output_mode="prefixed", prefix="modified_"):
    # Get a list of all image files in the folder
    image_files = [file for file in os.listdir(folder_path) if file.endswith(('.png', '.jpg', '.jpeg', '.bmp'))]

    # Iterate over each image file
    for image_file in image_files:
        # Load the image
        image_path = os.path.join(folder_path, image_file)
        image = Image.open(image_path)

        # Get the original width and height
        original_width, original_height = image.size
        print(f"Original Width: {original_width}, Height: {original_height}")

        # Calculate the new width and height
        new_width = int(original_width * scaling_factor)
        new_height = int(original_height * scaling_factor)
        print(f"New Width: {new_width}, Height: {new_height}")

        # Resize the image
        scaled_image = image.resize((new_width, new_height))

        # Save image using selected output behavior
        if output_mode == "overwrite":
            output_path = image_path
        elif output_mode == "renamed":
            name, ext = os.path.splitext(image_file)
            output_path = os.path.join(folder_path, f"{name}_scaled{ext}")
        else:
            output_path = os.path.join(folder_path, f"{prefix}{image_file}")

        scaled_image.save(output_path)
        print(f"Saved: {output_path}")

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Scale images in a folder.")
    parser.add_argument("folder_path", type=str, help="Path to the folder containing images.")
    parser.add_argument("--scaling_factor", type=float, default=0.5, help="Scaling factor for images.")
    parser.add_argument(
        "--output_mode",
        choices=["prefixed", "overwrite", "renamed"],
        default="prefixed",
        help="Output naming mode: prefixed (default), overwrite original, or renamed with _scaled suffix.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="modified_",
        help="Prefix used when --output_mode prefixed.",
    )
    args = parser.parse_args()

    # Call the function to scale images
    scale_images_in_folder(
        args.folder_path,
        args.scaling_factor,
        output_mode=args.output_mode,
        prefix=args.prefix,
    )
