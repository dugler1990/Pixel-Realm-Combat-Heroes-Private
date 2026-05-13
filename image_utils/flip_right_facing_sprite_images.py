import cv2
import os
import sys


def flip_images_in_right_prefixed_directories(root_directory):
    if not os.path.exists(root_directory):
        print(f"The directory {root_directory} does not exist.")
        return

    for folder_name in sorted(os.listdir(root_directory)):
        if not folder_name.startswith("right_"):
            continue

        folder_path = os.path.join(root_directory, folder_name)
        if not os.path.isdir(folder_path):
            continue

        suffix = folder_name[len("right_") :]
        left_folder_name = "left_" + suffix
        left_folder_path = os.path.join(root_directory, left_folder_name)
        os.makedirs(left_folder_path, exist_ok=True)

        for filename in sorted(os.listdir(folder_path)):
            if not filename.lower().endswith(".png"):
                continue
            file_path = os.path.join(folder_path, filename)
            image = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)

            if image is not None:
                flipped_image = cv2.flip(image, 1)
                out_path = os.path.join(left_folder_path, filename)
                cv2.imwrite(out_path, flipped_image)
                print(f"Flipped and saved {out_path}")
            else:
                print(f"Failed to load the image {file_path}.")


def flip_images_in_right_facing_directories(root_directory):
    """Backwards-compatible alias."""
    flip_images_in_right_prefixed_directories(root_directory)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: python flip_right_facing_sprite_images.py <path_to_parent_directory>"
        )
        print(
            "  Each subfolder right_<rest> -> mirrored PNGs in left_<rest> (same filenames)."
        )
    else:
        directory_path = sys.argv[1]
        flip_images_in_right_prefixed_directories(directory_path)
