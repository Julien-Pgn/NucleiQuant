"""
This script segments TIFF images on channel 0 using a fine-tuned StarDist model.
Pass the folder containing the TIFF images with --images (see --help for all options).
Segmented label images are saved in 'lbl/' and ImageJ ROIs in 'roi/' subfolders of the input directory.
WARNING: Existing files in 'lbl/' and 'roi/' will be overwritten
"""


import argparse
import os
import h5py
import numpy as np
from tifffile import imread, imwrite
from stardist import export_imagej_rois
from stardist.models import StarDist2D
from zipfile import ZIP_DEFLATED
from csbdeep.utils import normalize


def parse_args():
    parser = argparse.ArgumentParser(description="Segment nuclei in TIFF images with the fine-tuned StarDist model.")
    parser.add_argument("--images", required=True, help="Path to the folder containing the TIFF images to segment.")
    parser.add_argument("--model-dir", default="models", help="Path to the folder containing the stardist_haug2 model (default: models).")
    return parser.parse_args()


args = parse_args()
dir_img = args.images

# Output directory for labels and ROIs
output_lbl = os.path.join(dir_img, 'lbl')
output_roi = os.path.join(dir_img, 'roi')

# Check and create output directories
if not os.path.exists(output_lbl):
    os.makedirs(output_lbl)
    os.makedirs(output_roi)
    print(f"'{output_lbl}' has been created.\n")
else:
    user_response = input(f"\n'{output_lbl}' and/or '{output_roi}' already exists and will be overwrite. Do you want to proceed? (y/n) -> ")
    if user_response.lower() != 'y':
        print("Exiting script.")
        exit()

# Get a list of TIFF files in the directory
tif_images = [f for f in os.listdir(dir_img) if f.lower().endswith((".tif", ".tiff")) and not f.startswith("._")]
if not tif_images:
    print(f"No tiff images found in {dir_img} -> Exiting")
    exit()

# Load the Stardist model: StarDist Haug2 is located in the /models folder (from the github repo)
model = StarDist2D(None, name='stardist_haug2', basedir=args.model_dir)

# Loop through TIFF files
for index, filename in enumerate(tif_images, 1):
    print(f"Processing ({index}/{len(tif_images)}): {filename}")
    try:
        # Read the first channel of the image using tifffile.imread (e.g., DAPI is often the first channel thus 'key = 0')
        img = imread(os.path.join(dir_img, filename), key=0)
        # Normalize the images. pmin=0.2 (vs. 1 used in training) is deliberate:
        # darker images oversegment the background at pmin=1. Can be modified
        # to segment noisy images.
        img = normalize(img, 0.2, 99.8)

        # Segmentation
        labels, polys = model.predict_instances(img, axes='YX', normalizer=None, n_tiles= (3,3))

        # Count the number of unique labels in the lbl images
        unique_labels = np.unique(labels)
        num_unique_labels = len(unique_labels)

        # Optimisation of the disk space based on the format of label images (encoded in 32 bits if there are more than 65536 nuclei in your image)
        if num_unique_labels < 2**16:
            labels = labels.astype(np.uint16)
        else:
            labels = labels.astype(np.uint32)

        # Save the label image as tif and h5 (To be modified later on)
        label_output_path = os.path.join(output_lbl, f'{filename[:-4]}_labels.tif')
        imwrite(label_output_path, labels)
        label_output_path2 = os.path.join(output_lbl, f"{os.path.splitext(filename)[0]}_labels.h5")
        with h5py.File(label_output_path2, 'w') as f:
            f.create_dataset('labels', data = labels)

        # Save ImageJ ROIs
        roi_output_path = os.path.join(output_roi, f'{filename[:-4]}_rois.zip')
        export_imagej_rois(roi_output_path, polys['coord'], compression=ZIP_DEFLATED)
    
    except Exception as e:
        print(f"\nError with {filename}: {str(e)}")
        continue 

print("Processing complete.")