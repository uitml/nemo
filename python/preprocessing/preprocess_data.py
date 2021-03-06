"""
Usage:
  preprocess_data.py [options] <source> <output>

Options:
  --border-threshold=<scalar>  Threshold used for border detection.
                               [default: 70]
  --object-threshold=<scalar>  Threshold used for object detection.
                               [default: 120]
  --image-margin=<pixels>      Margin outside the detection region.
                               [default: 122]
  -h, --help                   Show this screen.
"""

from docopt import docopt

import shutil
from pathlib import Path

import cv2 as cv
import numpy as np

OVERLAY_ALPHA = 0.5
OVERLAY_COLOR = [127, 0, 255]


def _output_path(orig_path, suffix=None):
    file_name = orig_path.stem
    if suffix:
        file_name = "{}-{}".format(file_name, suffix)

    return output_dir / "{}.png".format(file_name)


def _imread(path):
    return cv.imread(str(path), cv.IMREAD_COLOR)


def _imwrite(path, image, suffix=None):
    return cv.imwrite(str(_output_path(path, suffix)), image)


def blur(image, size):
    image = cv.medianBlur(image, size)

    return image


def binary(image, blur_size, threshold=127):
    if image.ndim == 3:
        image = cv.cvtColor(image, cv.COLOR_BGR2GRAY)

    image = blur(image, blur_size)
    _, image = cv.threshold(image, threshold, 255, cv.THRESH_BINARY)

    return image


def _add_bbox(stats, image):
    top = stats[cv.CC_STAT_TOP]
    left = stats[cv.CC_STAT_LEFT]
    width = stats[cv.CC_STAT_WIDTH]
    height = stats[cv.CC_STAT_HEIGHT]

    top_left = (left, top)
    bottom_right = (left + width, top + height)

    # Add bounding box for object.
    bbox_color = (0, 0, 255)
    bbox_thickness = 2
    updated_image = cv.rectangle(image, top_left, bottom_right, bbox_color, bbox_thickness)

    return updated_image


if __name__ == "__main__":
    args = docopt(__doc__)
    source_dir = Path(args["<source>"])
    output_dir = Path(args["<output>"])
    border_threshold = int(args["--border-threshold"])
    object_threshold = int(args["--object-threshold"])
    image_margin = int(args["--image-margin"])

    # Recreate target directory on every execution.
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)

    print("Source directory:", source_dir)
    print("-" * 72)

    # TODO: Make patch size configurable or dynamic?
    patch_dims = np.array([224, 224])
    patch_height, patch_width = patch_dims

    for image_file in sorted(source_dir.rglob("*.tiff")):
        print(image_file)

        output_file = output_dir / "{}.png".format(image_file.stem)
        image = _imread(image_file)

        # Binary mask for finding the "metal border".
        # TODO: Make blur size configurable?
        image_binary = binary(image, blur_size=75, threshold=border_threshold)

        # Find the "metal border" component based on area.
        _, image_cc, stats, _ = cv.connectedComponentsWithStats(image_binary)
        # Assume that the metal border is the component with the largest area,
        # after ignoring the "background" that is always labeled as 0.
        border_label = np.argmax(stats[1:, cv.CC_STAT_AREA]) + 1

        # Binary mask used for finding objects.
        # TODO: Make blur size configurable?
        image_binary = binary(image, blur_size=31, threshold=object_threshold)

        # Remove the "metal border" from the object mask.
        image_binary[image_cc == border_label] = 0

        # Remove objects too close to the edges; they are likely to overlap with objects
        # in neighboring source images, so this approach should remove all duplicates.
        image_binary[:image_margin] = 0
        image_binary[-image_margin:-1] = 0
        image_binary[:, :image_margin] = 0
        image_binary[:, -image_margin:-1] = 0

        # Find all regions of interest.
        n_labels, image_cc, stats, centroids = cv.connectedComponentsWithStats(image_binary)
        centroids = centroids.astype(int)

        # Remove objects with fewer than specified number of pixels.
        labels, pixel_counts = np.unique(image_cc[image_cc > 0], return_counts=True)
        image_binary[np.isin(image_cc, labels[pixel_counts < 1024])] = 0

        # Save object mask image.
        _imwrite(image_file, image_binary, suffix="binary")

        # Create an image with mask overlays. Useful for visual debugging.
        image_seg = image.copy()
        image_seg[image_binary == 255] = OVERLAY_COLOR
        image_overlay = cv.addWeighted(image_seg, OVERLAY_ALPHA, image, 1 - OVERLAY_ALPHA, 0)
        _imwrite(image_file, image_overlay, suffix="overlay")

        # Create an image with bounding boxes. Useful for visual debugging.
        image_bbox = image.copy()

        patch_num = 0
        for i in range(1, n_labels):
            # Ignore patch candidates below defined pixel count threshold.
            if np.isin(i, labels[pixel_counts < 1024]):
                continue

            patch_num += 1

            # Add bounding box for object to bounding box image.
            image_bbox = _add_bbox(stats[i], image_bbox)

            # Extract and save image patch from object.
            cx, cy = centroids[i]

            # TODO: Extract cropping dimension stuff into a function.
            if cx - patch_width // 2 < 0:
                cx += cx - patch_width // 2
                cx = max(cx, patch_width // 2)
            elif cx + patch_width // 2 > image.shape[1]:
                cx -= image.shape[1] - (cx + patch_width // 2)
                cx = min(cx, image.shape[1] - patch_width // 2)
            col_crop = slice(cx - patch_width // 2, cx + patch_width // 2)

            # TODO: Extract cropping dimension stuff into a function.
            if cy - patch_height // 2 < 0:
                cy += cy - patch_height // 2
                cy = max(cy, patch_height // 2)
            elif cy + patch_height // 2 > image.shape[0]:
                cy -= image.shape[0] - (cy + patch_height // 2)
                cy = min(cy, image.shape[0] - patch_height // 2)
            row_crop = slice(cy - patch_height // 2, cy + patch_height // 2)

            _imwrite(image_file, image[row_crop, col_crop], suffix="patch{:02d}".format(patch_num))

        _imwrite(image_file, image_bbox, suffix="bbox")
