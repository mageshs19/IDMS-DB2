import streamlit as st


def render_metadata(
    metadata
):

    st.subheader(
        "Detected Records"
    )

    for record in metadata.records:

        st.markdown(
            f"### {record.name}"
        )

        st.write(
            f"Fields: {len(record.fields)}"
        )

        field_names = [
            field.name
            for field in record.fields
        ]

        st.dataframe(
            field_names
        )