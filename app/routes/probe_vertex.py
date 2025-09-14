import vertexai
from vertexai.preview.vision_models import ImageGenerationModel

def main():
    vertexai.init(project="azure-vertex", location="us-central1")

    # Usa Imagen 4
    model = ImageGenerationModel.from_pretrained("imagen-4.0-generate")

    prompt = "Un cubo 3D blu su sfondo bianco"
    images = model.generate_images(prompt=prompt, number_of_images=1)

    for i, img in enumerate(images):
        img.save(f"imagen4_test_{i}.png")

    print("✅ Immagine generata con Imagen 4")

if __name__ == "__main__":
    main()

