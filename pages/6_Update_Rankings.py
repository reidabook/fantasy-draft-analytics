"""
Page 6: Update Rankings
Upload FantasyPros "Draft ALL Rankings" CSV exports — one per scoring format
(PPR / Half-PPR / Standard), plus an optional shared bye-week export.
FantasyPros ranks players differently per format (e.g. a pass-catching RB
moves up in PPR vs standard), so each format needs its own upload to get its
own correct rank/ADP — uploading one format never overwrites another's.
"""
import tempfile
from pathlib import Path

import streamlit as st

from src.data.pipeline import import_fantasypros_local, SCORING_TYPES
from src.data.cache import get_adp, get_projections

st.set_page_config(page_title="Update Rankings", layout="wide")
st.title("📥 Update Rankings")

st.markdown(
    "Download FantasyPros' **Draft ALL Rankings** CSV (the stat-line export, with a "
    "FANTASYPTS column) once per scoring format you draft with, and upload each below. "
    "They're stored separately — uploading Half-PPR rankings won't touch your PPR ones."
)

FORMAT_LABELS = {"ppr": "PPR", "half_ppr": "Half-PPR", "standard": "Standard"}


def _save_upload(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    return tmp.name


def _source_status(scoring_type: str) -> str:
    source = f"fantasypros_local_{scoring_type}"
    rows = [a for a in get_adp(season=2026, source=source)]
    if not rows:
        return "⚫ never uploaded"
    updated = max(r["updated_at"] for r in rows)
    return f"🟢 {len(rows)} players · updated {updated[:16].replace('T', ' ')}"


st.markdown("---")
st.subheader("Rankings by format")

cols = st.columns(3)
uploads = {}
for col, scoring_type in zip(cols, SCORING_TYPES):
    with col:
        st.markdown(f"**{FORMAT_LABELS[scoring_type]}**")
        st.caption(_source_status(scoring_type))
        uploads[scoring_type] = st.file_uploader(
            f"{FORMAT_LABELS[scoring_type]} rankings CSV",
            type="csv",
            key=f"upload_{scoring_type}",
            label_visibility="collapsed",
        )

st.markdown("---")
st.subheader("Bye weeks (optional, shared across all formats)")
bye_upload = st.file_uploader(
    "FantasyPros cheat-sheet CSV export (has a BYE WEEK column)",
    type="csv",
    key="upload_bye",
)

st.markdown("---")

if st.button("Import uploaded files", type="primary", use_container_width=False):
    any_upload = any(uploads.values()) or bye_upload
    if not any_upload:
        st.warning("Upload at least one rankings CSV or the bye-week CSV first.")
    else:
        logs = []
        bye_path = _save_upload(bye_upload) if bye_upload else None
        bye_applied = False
        try:
            for scoring_type, uploaded_file in uploads.items():
                if not uploaded_file:
                    continue
                stats_path = _save_upload(uploaded_file)
                try:
                    with st.spinner(f"Importing {FORMAT_LABELS[scoring_type]} rankings..."):
                        result = import_fantasypros_local(
                            stats_path,
                            # only need to apply the bye CSV once across the loop
                            bye_csv_path=None if bye_applied else bye_path,
                            scoring_type=scoring_type,
                            log_cb=logs.append,
                        )
                    st.success(
                        f"{FORMAT_LABELS[scoring_type]}: {result['projections']} projections, "
                        f"{result['adp']} ADP entries"
                        + (f", {result['bye_weeks']} bye weeks" if bye_path and not bye_applied else "")
                    )
                    bye_applied = True
                finally:
                    Path(stats_path).unlink(missing_ok=True)

            if bye_path and not bye_applied:
                # Only the bye CSV was uploaded, no rankings — still worth applying.
                with st.spinner("Importing bye weeks..."):
                    result = import_fantasypros_local(bye_csv_path=bye_path, log_cb=logs.append)
                st.success(f"{result['bye_weeks']} bye weeks cached")
        except Exception as e:
            st.error(f"Import failed: {e}")
        finally:
            if bye_path:
                Path(bye_path).unlink(missing_ok=True)

        for msg in logs:
            st.caption(msg)

        st.info(
            "Go to **VBD Rankings** and click ↺ Recalc for each league to pick up the new data "
            "(or run `python prefetch.py --vbd`)."
        )
