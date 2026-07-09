from idms_modernizer.services.metadata_service import (
    MetadataService
)

from idms_modernizer.services.validation_service import (
    ValidationService
)

from idms_modernizer.ui.metadata_page import (
    render_metadata
)

from idms_modernizer.ui.upload_page import (
    render_upload_page
)

metadata_service = MetadataService()

validator = ValidationService()

pdf_path = render_upload_page()

if pdf_path:

    metadata = (
        metadata_service.build_metadata(
            pdf_path
        )
    )

    validator.validate_metadata(
        metadata
    )

    render_metadata(
        metadata
    )