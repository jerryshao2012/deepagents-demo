"""Frontend Slides Skill.

This package contains the frontend-slides skill implementation including:
- HTML presentation generation tool
- CSS/JS asset parsing logic
- Export and deployment scripts
"""

from .pipeline import (
    frontend_slides,
    frontend_slides_export_pdf,
    frontend_slides_deploy,
    frontend_slides_extract_pptx,
)

__all__ = [
    "frontend_slides",
    "frontend_slides_export_pdf",
    "frontend_slides_deploy",
    "frontend_slides_extract_pptx",
]
