import cloudinary
import cloudinary.uploader
import cloudinary.api
from config import settings
import os

# Configure Cloudinary
if settings.CLOUDINARY_CLOUD_NAME:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True
    )

class CloudinaryService:
    @staticmethod
    def upload_image(file_content, folder="strangestreet/posts"):
        """
        Uploads a file (bytes or file-like object) to Cloudinary.
        Returns the secure URL.
        """
        if not settings.CLOUDINARY_CLOUD_NAME:
            # Fallback path if not configured (should not happen in prod)
            return None

        try:
            result = cloudinary.uploader.upload(
                file_content,
                folder=folder,
                resource_type="auto"
            )
            return result.get("secure_url")
        except Exception as e:
            print(f"[CloudinaryService] Upload failed: {e}")
            return None

    @staticmethod
    def delete_image(public_id):
        """Deletes an image from Cloudinary by its public_id."""
        if not settings.CLOUDINARY_CLOUD_NAME:
            return
        
        try:
            cloudinary.uploader.destroy(public_id)
        except Exception as e:
            print(f"[CloudinaryService] Delete failed: {e}")

    @staticmethod
    def get_public_id(url: str):
        """Extracts the public_id from a Cloudinary URL."""
        if not url or "res.cloudinary.com" not in url:
            return None
        # Example: https://res.cloudinary.com/cloud/image/upload/v1/folder/id.jpg
        # We need "folder/id"
        parts = url.split("/")
        # The public_id starts after 'upload/v12345/'
        try:
            version_idx = -1
            for i, p in enumerate(parts):
                if p.startswith("v") and p[1:].isdigit():
                    version_idx = i
                    break
            
            if version_idx != -1:
                public_id_with_ext = "/".join(parts[version_idx+1:])
                return public_id_with_ext.split(".")[0]
        except:
            pass
        return None
