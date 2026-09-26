"""
This script segments TIFF images on channel 0 using a fine-tuned StarDist model.
Pass the folder containing the TIFF images with --images (see --help for all options).
Segmented label images are saved in 'lbl/' and ImageJ ROIs in 'roi/' subfolders of the input directory.
WARNING: Existing files in 'lbl/' and 'roi/' will be overwritten

The NucleiQuant app (V2) does this as part of its workflow; this script is
kept for the V1 workflow (segmentation only, then ilastik).
"""


import argparse
import os
import sys
from zipfile import ZIP_DEFLATED

from stardist import export_imagej_rois

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from nucleiquant import io, segmentation  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Segment nuclei in TIFF images with the fine-tuned StarDist model.")
    parser.add_argument("--images", required=True, help="Path to the folder containing the TIFF images to segment.")
    parser.add_argument("--model-dir", default="models", help="Path to the folder containing the stardist_haug2 model (default: models).")
    parser.add_argument("--channel", type=int, default=0, help="Nuclear channel, counting from 0 (default: 0, e.g. DAPI).")
    parser.add_argument("--yes", action="store_true", help="Overwrite existing outputs without asking.")
    return parser.parse_args()


args = parse_args()
dir_img = args.images
os.environ.setdefault("NQ_MODEL_DIR", args.model_dir)

# Output directory for labels and ROIs
output_lbl = os.path.join(dir_img, 'lbl')
output_roi = os.path.join(dir_img, 'roi')

# Check and create output directories
if not os.path.exists(output_lbl):
    os.makedirs(output_lbl)
    os.makedirs(output_roi, exist_ok=True)
    print(f"'{output_lbl}' has been created.\n")
elif not args.yes:
    user_response = input(f"\n'{output_lbl}' and/or '{output_roi}' already exists and will be overwrite. Do you want to proceed? (y/n) -> ")
    if user_response.lower() != 'y':
        print("Exiting script.")
        exit()
os.makedirs(output_roi, exist_ok=True)

# Get a list of TIFF files in the directory
tif_images = io.list_tiffs(dir_img)
if not tif_images:
    print(f"No tiff images found in {dir_img} -> Exiting")
    exit()

# Loop through TIFF files
for index, filename in enumerate(tif_images, 1):
    print(f"Processing ({index}/{len(tif_images)}): {filename}")
    try:
        # Read the nuclear channel (e.g., DAPI is often the first channel)
        img = io.read_image(os.path.join(dir_img, filename), channel=args.channel)
        # Normalisation percentiles 0.2-99.8 (vs. 1 used in training) are deliberate:
        # darker images oversegment the background at pmin=1.
        lo, hi = segmentation.normalization_range(img, 0.2, 99.8)

        # Segmentation
        labels, polys = segmentation.segment(img, lo, hi, return_polygons=True)

        # Save the label image as tif and h5
        stem = os.path.splitext(filename)[0]
        io.write_labels(os.path.join(output_lbl, f"{stem}_labels"), labels)

        # Save ImageJ ROIs
        export_imagej_rois(os.path.join(output_roi, f"{stem}_rois.zip"), polys['coord'], compression=ZIP_DEFLATED)

    except Exception as e:
        print(f"\nError with {filename}: {str(e)}")
        continue

print("Processing complete.")
