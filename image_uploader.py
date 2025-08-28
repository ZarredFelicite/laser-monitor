#!/usr/bin/env python3

import requests
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class ImageUploader:
    """Simple image uploader utility that uploads images to temp.sh and returns URLs."""
    
    def __init__(self, upload_url: str = "https://temp.sh/upload"):
        self.upload_url = upload_url
    
    def upload_image(self, image_path: str) -> Optional[str]:
        """
        Upload an image file and return the URL.
        
        Args:
            image_path: Path to the image file to upload
            
        Returns:
            URL string if successful, None if failed
        """
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            return None
            
        try:
            with open(image_path, "rb") as f:
                files_upload = {"file": f}
                response = requests.post(self.upload_url, files=files_upload, timeout=30)
                
            if response.status_code == 200:
                url = response.text.strip()
                logger.info(f"Successfully uploaded {image_path} to {url}")
                return url
            else:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error uploading {image_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading {image_path}: {e}")
            return None

def upload_image(image_path: str) -> Optional[str]:
    """Convenience function to upload an image and return the URL."""
    uploader = ImageUploader()
    return uploader.upload_image(image_path)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] in ['-h', '--help']:
        print("Usage: python image_uploader.py <image_path>")
        print("Upload an image file to temp.sh and print the URL")
        sys.exit(0 if len(sys.argv) == 2 else 1)
    
    image_path = sys.argv[1]
    url = upload_image(image_path)
    if url:
        print(url)
    else:
        print("Upload failed")
        sys.exit(1)