# Image Assets — Provenance & Usage Notice

The images in this folder (and its subfolders) are **AI-generated** and are **not**
covered by the project's MIT `LICENSE` (MIT applies to the source code only).
This notice documents how they were produced and the terms that apply.

## How the images were generated

| Stage | Tool / Model | License |
|-------|--------------|---------|
| Image generation | **Juggernaut XL v9** (RunDiffusionPhoto v2), an SDXL fine-tune | CreativeML Open RAIL-M (+ RunDiffusion addendum) |
| Upscaling to 3840×2160 | **4xNomos8kDAT** by Philip Hofmann (Phips) | CC-BY-4.0 (attribution required) |
| Transparency (alpha) | ComfyUI core nodes (luminance → alpha mask); **no model involved** | — |
| Runtime | ComfyUI | GPL-3.0 (software only — does not bind outputs) |

All images are RGBA PNG at 3840×2160 with a luminance-based alpha channel
(bright/glowing areas are transparent, dark areas opaque).

## Terms of use

These images are provided **as-is**. Because they are outputs of a model
licensed under the **CreativeML Open RAIL-M**, the license's **use-based
restrictions (Section II / Attachment A)** travel with the outputs: you may use,
copy, and redistribute the images freely, but **not** for any of the purposes
prohibited by that license (e.g. unlawful, harmful, deceptive, or rights-
infringing uses). See: https://huggingface.co/spaces/CompVis/stable-diffusion-license

Before **commercial** redistribution, also confirm the model's per-model
permission flags on its source page (Civitai/Hugging Face), in particular
whether selling generated images is permitted for Juggernaut XL v9.

## Copyright note

These images are produced primarily by an automated process. In several
jurisdictions (e.g. the United States) purely AI-generated works without
sufficient human authorship are **not eligible for copyright protection**.
No copyright claim is asserted over them beyond what applicable law provides.

## What is intentionally NOT included here

The following were excluded to keep this asset set free of restrictive terms:

- **Anime character cut-outs** — were matted with BRIA **RMBG-2.0**, which is
  free for non-commercial use only (commercial use requires a BRIA license).
- **Animations (GIF/WebP)** — out of scope for this image set.
- **4x-UltraSharp upscales** — that upscaler is CC BY-NC-SA 4.0 (non-commercial);
  replaced by 4xNomos8kDAT (CC-BY-4.0) so the set stays usable commercially.

## Required attribution

The upscaler **4xNomos8kDAT** is licensed CC-BY-4.0 and requires credit:

> Upscaling model "4xNomos8kDAT" by Philip Hofmann (Phips), licensed under
> CC-BY-4.0 — https://huggingface.co/Phips/4xNomos8kDAT

---
*Generated with Juggernaut XL v9 (CreativeML Open RAIL-M) · upscaled with 4xNomos8kDAT by Philip Hofmann (CC-BY-4.0).*
