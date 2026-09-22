# StarDist + Ilastik Segmentation Pipeline

This repository provides a streamlined and robust image analysis pipeline for **nuclei-based cell segmentation** and **quantification of cell type proportions** in fluorescence microscopy images.  
The workflow integrates a fine-tuned **StarDist** model—used for deep learning–based nuclei detection in dense and complex tissues—with **Ilastik** for interactive **object classification**.  
Together, these tools enable accurate and reproducible analysis of immunostained samples across a wide variety of tissues and model organisms, including **human**, **mouse**, and **Drosophila**.

By combining automation with flexibility, this pipeline makes it easier to extract meaningful quantitative data from microscopy images with minimal manual intervention.

---
## Overview

This repository includes all resources needed to train, apply, and analyze results from the StarDist + Ilastik segmentation workflow:

- Scripts and notebooks for **fine-tuning a StarDist model** on manually annotated images.
- **134 manually annotated images** from human cortical organoids.
	- See _Pigeon et al._ (doi: https://doi.org/10.1101/2025.10.27.684791) for details on dataset generation and annotation.
- **447 pretraining images** from the **DSB2018** dataset used by the original StarDist authors.
- The resulting **fine-tuned model weights**, compatible with **ImageJ**, **QuPath**, and **Python**.
- Scripts for **batch segmentation** of fluorescence images using the fine-tuned model.
- Jupyter notebooks to:
    - Select representative images for training the **Ilastik** object classifier.
    - Aggregate and analyze **Ilastik** output tables for quantitative downstream analysis of cell-type proportions.

---
## Associated Publication

The image analysis pipeline was **assembled and adapted** by _Julien Pigeon_ in the Hassan Lab at the Paris Brain Institute, integrating existing open-source tools including **StarDist** and **Ilastik**. It was used in:

> **Pigeon J.**, et al. Post-translational Tuning of Human Cortical Progenitor Neuronal output.
> [Preprint, BioRxiv, doi: https://doi.org/10.1101/2025.10.27.684791]

If you use this repository or any derivative models, please cite the above paper with the original publications for [StarDist](https://github.com/stardist/stardist) and [Ilastik](https://github.com/ilastik/ilastik) as the pipeline is built upon these frameworks.  on these two powerful tools. For details on their underlying methods and implementation, refer to their respective GitHub repositories and documentation.

---
## Installation

The pipeline needs a TensorFlow/CUDA combination that's easy to get wrong by hand, so a Docker image is
provided. It works the same whether your computer has an NVIDIA GPU or not.

**Requirements:** [Docker](https://docs.docker.com/get-docker/), and for GPU use, the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

```bash
./run_container.sh build              # once
./run_container.sh jupyter            # notebooks, with GPU -> http://localhost:8888
./run_container.sh jupyter_cpu        # notebooks, no GPU needed
./run_container.sh exec python scripts/01_segmentation.py   # run a script directly
./run_container.sh stop               # stop the Jupyter server
```

No GPU on your machine? Every `exec`/`jupyter` mode has a `_cpu` variant — same image, no extra setup.

Prefer to install without Docker? Exact package versions are pinned in `pyproject.toml`.

---
## Usage

This repository includes a modified Jupyter notebook based on the official [StarDist](https://github.com/stardist/stardist) implementation to **fine-tune a StarDist model** for accurate **nuclei segmentation in dense tissues**, such as the developing mammalian brain.  

The resulting model, named **`stardist_haug2`**, was used in the study referenced above (_Pigeon et al._, 2025).

### Model availability

The **`stardist_haug2`** model can be used directly without retraining. It has been exported in multiple formats for compatibility with different platforms:

- **Python** – ready-to-use model for analysis scripts and notebooks.
- **ImageJ / Fiji** – exported TensorFlow model.
    - Check the TensorFlow version used in your ImageJ/Fiji installation and select the corresponding model export. It seems that new verisons of ImageJ or FIJI don't include TF1.15 anymore.
- **QuPath** – exported as `stardist_haug2.pb` for direct import.
    - Refer to the official StarDist–QuPath integration guide for usage instructions here: [Stardist_Qupath](https://qupath.readthedocs.io/en/stable/docs/deep/stardist.html)

### Segmentation script:
All input images must be in **TIFF format**. In Pigeon,. et al we had images with **four channels** (DAPI, 488, 555, and 647). Place these images in a dedicated folder, then specify this path when running `segmentation.py`.  

The script will segment nuclei using the **fine-tuned StarDist model**, stardist_haug2, and generate the following outputs within your image folder:
- Labeled images stored in a subfolder named `lbl/`
- ImageJ-compatible ROI files stored in a subfolder named `rois/`

### Image selection for Ilastik training

Because staining and imaging conditions can produce variable signal intensities across samples, the next step involves **selecting representative images** to train a robust classifier in **Ilastik**.  Machine learning approaches, such as Random Forest, can accommodate these differences if trained on a diverse range of intensities.

Run the provided Jupyter notebook to compute **average image intensities** and identify **three representative images** (low, medium, and high intensity) for the fluorescence channel of interest in each clone or condition.  For instance, in _Pigeon et al._, five CRISPR/Cas9 clones were analyzed, resulting in **15 training images** (3 intensity levels × 5 conditions).

After selection, copy and paste the representative images into another folder and crop them to speed up Ilastik loading and training. You must then **re-segment** the cropped regions using the StarDist model to ensure consistency between training and full-image predictions.

### Preparing data for Ilastik

Since Ilastik handles `.h5` masks more efficiently than TIFF label files, it is recommended to convert:
- All segmentation masks from the cropped images
- All segmentation masks from the full dataset

to **HDF5 (.h5)** format.

Conversion scripts are provided for this step.

### Object classification in Ilastik

Load the cropped images and their corresponding `.h5` masks into Ilastik to train an **object classifier**. In **Step 2** of the Ilastik workflow, select image features that yield the best separation between your predefined categories. The optimal feature set is somewhat empirical. You can see _Pigeon et al._, the features selected for accurate organoid data.

Each staining panel usually defines biologically relevant **categories** to the user (e.g., specific cell types or marker-positive populations).  
In addition, include two other categories:
- A **“dead cells”** category (common in organoids with necrotic cores)
- An **“unstained cells”** category to capture cells lacking a marker signal

Note: In the absence of a fluorescence signal, classification accuracy decreases because Ilastik relies heavily on intensity-based features.

Once the classifier performs satisfactorily, launch the **batch object classification** over all segmented images. Save the resulting quantitative data as `.csv` files for downstream aggregation.

### Quantification

The final Jupyter notebook aggregates all `.csv` files generated by Ilastik and counts the number of cells per category. It outputs a single **Excel file** summarizing cell-type proportions, suitable for direct use in statistical analyses.

This notebook is tailored for **human cortical organoids** or similar **3D tissue models** sectioned into multiple slices (typically 4–6 per organoid). In its second step, the notebook automatically **sums the proportions** of each cell category across slices, providing an integrated view of the cellular composition for each 3D organoid.

Furthermore, in this script we also incorporated a decomposition of the file names as we used them to store metadata for better storage of critical informations as developed in the materials and methods section of Pigeon et al.,. Modify the code to fit your image name

---
###  Workflow Summary

1. **Prepare images**
    - Convert raw microscopy images to **TIFF** format with 4 channels (DAPI, 488, 555, 647).
    - Organize them into a single directory.
2. **Segment nuclei (StarDist)**
    - Run `segmentation.py` with the path to your image folder.
    - Outputs:
        - Labeled masks (`/lbl/`)
        - ROI files for ImageJ (`/rois/`)
3. **Select training images for Ilastik**
    - Use the Jupyter notebook to compute mean intensity per image.
    - Choose **three representative images** (low, medium, high intensity) per condition or clone.
    - Crop these images and **re-segment** the cropped areas.
4. **Convert masks for Ilastik**
    - Convert all TIFF masks (full images and crops) to **HDF5 (.h5)** format.
5. **Train the Ilastik object classifier**
    - Load cropped images and their `.h5` masks.
    - Define biological categories (e.g., marker-positive, dead cells, unstained).
    - Select optimal features and train the model.
6. **Batch classify all images (Ilastik)**
    - Apply the trained classifier to all full-size segmented images.
    - Export object-level quantification as **CSV files**.
7. **Quantify and aggregate results**
    - Run the final Jupyter notebook to combine all CSV files.
    - Output: one **Excel summary file** with cell-type proportions per condition.
    - For organoids, values are **summed across 4–6 slices** to represent full 3D composition.

---

