from pathlib import Path

import streamlit as st

from idms_modernizer.core.config import (
    settings
)


def render_upload_page():

    st.subheader(
        "Upload IDMS Schema PDF"
    )

    uploaded_file = (
        st.file_uploader(
            "Schema PDF",
            type=["pdf"]
        )
    )

    if uploaded_file:

        save_path = (
            Path(
                settings.input_dir
            )
            / uploaded_file.name
        )

        with open(
            save_path,
            "wb"
        ) as file:

            file.write(
                uploaded_file.read()
            )

        st.success(
            f"Saved: {save_path}"
        )

        return str(save_path)

    return None