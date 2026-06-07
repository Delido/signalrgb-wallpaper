import os
import torch
import gradio as gr
from diffusers import StableDiffusionXLPipeline, UNet2DConditionModel, EulerDiscreteScheduler
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file
from PIL import Image

# Globaler Speicher für die Pipeline
pipe = None

def init_pipeline():
    global pipe
    print("Initialisiere lokale Breitbild-Pipeline für RTX 4070 Ti...")
    hf_model_id = "ByteDance/SDXL-Lightning"
    unet_file = "sdxl_lightning_4step_unet.safetensors"
    
    unet_path = hf_hub_download(repo_id=hf_model_id, filename=unet_file)
    unet = UNet2DConditionModel.from_config("stabilityai/stable-diffusion-xl-base-1.0", subfolder="unet")
    unet.load_state_dict(load_file(unet_path, device="cpu"))
    unet = unet.to(dtype=torch.float16)

    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        unet=unet,
        torch_dtype=torch.float16,
        variant="fp16"
    )
    
    # ─── HIER SIND DIE ZWEI KORREKTUREN FÜR JEDES BILDMATERIAL ───
    pipe.safety_checker = None  # Schaltet den lokalen Zensur-/Sicherheitsfilter komplett ab
    pipe.requires_safety_checker = False
    
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
    pipe.to("cuda")
    print("Pipeline einsatzbereit (Sicherheitsfilter deaktiviert)!")

# Kernfunktion für das Interface und die API
def generate_asset(prompt, target_size, make_transparent):
    # Wenn Transparenz gewünscht ist, hängen wir den "schwarzen Hintergrund" an den Prompt an
    if make_transparent:
        full_prompt = f"{prompt}, isolated on a solid pitch-black background, high contrast"
    else:
        full_prompt = prompt
    
    # Standardwerte (Quadratisch)
    width, height = 1024, 1024
    
    # Wenn Breitbild gewählt ist, weisen wir die KI an, nativ im 16:9-Verhältnis (1344x768) zu generieren
    if target_size in ["Full HD (1920x1080)", "4K UHD (3840x2160)"]:
        width, height = 1344, 768  # Bestes natives 16:9-Format für SDXL

    # 1. Bild mit korrekten Seitenverhältnissen generieren
    output_images = pipe(
        full_prompt, 
        width=width, 
        height=height, 
        num_inference_steps=4, 
        guidance_scale=0.0
    ).images
    
    # 🔥 KORREKTUR: Nimm das erste Bild aus der Liste heraus!
    single_image = output_images[0]
    
    # In ein Format mit Alpha-Kanal konvertieren
    img = single_image.convert("RGBA")

    # 2. Hintergrund NUR transparent machen, wenn der Haken gesetzt ist
    if make_transparent:
        datas = img.getdata()
        new_data = []
        for item in datas:
            # Stanzt sehr dunkle Pixel aus
            if item[0] < 20 and item[1] < 20 and item[2] < 20:
                new_data.append((255, 255, 255, 0))  # Transparent
            else:
                new_data.append(item)
        img.putdata(new_data)
    
    # 3. Knackscharfes Upscaling auf die echten 16:9 Zielmaße
    if target_size == "Full HD (1920x1080)":
        img = img.resize((1920, 1080), Image.Resampling.LANCZOS)
    elif target_size == "4K UHD (3840x2160)":
        img = img.resize((3840, 2160), Image.Resampling.LANCZOS)
        
    return img

# Pipeline vor dem GUI-Start laden
init_pipeline()

# ─── GRADIO GUI DESIGN ───
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🤖 Cyberpunk Asset & Wallpaper Generator (MIT-Licensed)")
    gr.Markdown("Generiere Bilder in echten 16:9 Breitbild-Auflösungen auf deiner RTX 4070 Ti.")
    
    with gr.Row():
        with gr.Column():
            prompt_input = gr.Textbox(
                label="Dein Prompt", 
                placeholder="z.B. Cyberpunk cityscape, neon lit streets, futuristic cars flying..."
            )
            
            size_dropdown = gr.Dropdown(
                choices=["Standard (1024x1024)", "Full HD (1920x1080)", "4K UHD (3840x2160)"],
                value="Standard (1024x1024)",
                label="Zielauflösung & Format"
            )
            
            transparency_checkbox = gr.Checkbox(
                label="Hintergrund transparent machen (erfordert dunklen Hintergrund im Prompt)", 
                value=False
            )
            
            btn = gr.Button("Bild generieren", variant="primary")
        
        with gr.Column():
            image_output = gr.Image(label="Ausgabe-Bild", type="pil")
            
    btn.click(
        fn=generate_asset, 
        inputs=[prompt_input, size_dropdown, transparency_checkbox], 
        outputs=image_output, 
        api_name="generate"
    )

# Startet die GUI lokal
demo.launch(server_name="127.0.0.1", server_port=7860)
