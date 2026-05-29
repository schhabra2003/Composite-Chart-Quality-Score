"""CCQS embeddable entry point.

This module exposes `render_ccqs_page()` so the CCQS dashboard can be
embedded as a page inside a parent Streamlit multi-page app (e.g.
adfundmgmt.streamlit.app/CCQS).

Standalone usage is unchanged — `streamlit run app/streamlit_app.py`
still works exactly as before. This module is only needed when CCQS is
imported by another Streamlit app.

Parent-app usage example
------------------------
Place this in `pages/07_CCQS.py` of the parent app, assuming CCQS is
importable on sys.path (e.g. via pip install, git submodule, or
vendored copy):

    from app.streamlit_app_entry import render_ccqs_page
    render_ccqs_page()

The parent page is re-executed by Streamlit on every interaction, so
render_ccqs_page() is called fresh on each rerun and the full CCQS
dashboard renders with the latest filters / selection state.
"""

from pathlib import Path
import runpy

_SCRIPT_PATH = Path(__file__).resolve().parent / "streamlit_app.py"


def render_ccqs_page() -> None:
    """Render the CCQS dashboard in the current Streamlit context.

    Internally re-executes `app/streamlit_app.py` via runpy.run_path so
    every top-level statement (data loading, sidebar widgets, tables,
    stock detail panel, footer) runs fresh on each call. This matches
    Streamlit's per-interaction script-rerun model.

    Safe to call from a parent multi-page app — the underlying script's
    `st.set_page_config()` is guarded against a double-call exception
    (see `app/streamlit_app.py` page-config block).
    """
    runpy.run_path(str(_SCRIPT_PATH), run_name="__ccqs_embedded__")


if __name__ == "__main__":
    # Allow `streamlit run app/streamlit_app_entry.py` for testing the
    # embedded path locally — behaves identically to standalone.
    render_ccqs_page()
