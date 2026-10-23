from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from services.s3 import upload_image
from models.user import User
from api import deps
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/image")
async def upload_image_endpoint(
    file: UploadFile = File(...),
    folder: str = Form("general"),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Upload an image to S3.
    folder: 'profiles' | 'movies' | 'general'
    Returns the public S3 URL.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: {', '.join(ALLOWED_TYPES)}"
        )

    contents = await file.read()

    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB.")

    try:
        url = upload_image(
            file_bytes=contents,
            filename=file.filename or "image.jpg",
            folder=folder,
            content_type=file.content_type,
        )
        return {"url": url, "filename": file.filename, "folder": folder}
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
