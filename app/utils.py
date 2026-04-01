from PIL import Image
import os
import uuid

# Map PIL formats to appropriate file extensions
EXT_MAP = {
    'JPEG': '.jpg',
    'PNG': '.png',
    'WEBP': '.webp',
    'GIF': '.gif',
}

def compress_image(upload_file, output_dir, prefix="", max_size=(1200, 1200), quality=85, folder="strangestreet/posts"):
    """
    Compresses an uploaded image file, resizes it if it exceeds max_size,
    converts it to WebP, and uploads it to Cloudinary (if configured)
    or saves it to output_dir.
    Returns the final URL or filename.
    """
    from app.services.cloudinary_service import CloudinaryService
    from config import settings
    import io

    try:
        # Open image using Pillow
        img = Image.open(upload_file.file)
        
        # Convert to RGBA for WebP consistency
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGBA')
        else:
            img = img.convert('RGB')
            
        # Resize if too large
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Generate hash name
        out_ext = '.webp'
        fname = f"{prefix}{uuid.uuid4().hex}{out_ext}"

        # 1. Try Cloudinary first if configured
        if settings.CLOUDINARY_CLOUD_NAME:
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='WebP', quality=quality, method=4)
            img_byte_arr.seek(0)
            
            url = CloudinaryService.upload_image(img_byte_arr, folder=folder)
            if url:
                return url

        # 2. Local Fallback
        os.makedirs(output_dir, exist_ok=True)
        fpath = os.path.join(output_dir, fname)
        img.save(fpath, format='WebP', quality=quality, method=4)
        return fname
        
    except Exception as e:
        print(f"[Utils] Image processing failed: {e}")
        return None
