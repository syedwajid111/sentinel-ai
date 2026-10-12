"""
Lets the user define restricted-zone polygons by clicking directly on a
captured reference frame — one click per corner, in order around the
boundary. Uses streamlit-image-coordinates, a small independent component
that (unlike streamlit-drawable-canvas) doesn't depend on Streamlit's
internal image APIs, so it won't break across Streamlit versions.
"""
import json
import os

import cv2
import numpy as np
import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates

import config


def _capture_reference_frame(source):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return None
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    frame = cv2.resize(frame, (config.FRAME_WIDTH, config.FRAME_HEIGHT))
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def _render_overlays(frame, zones, draft_points):
    out = frame.copy()

    # Previously saved zones — cyan
    for name, polygon in (zones or {}).items():
        if len(polygon) >= 3:
            pts = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(out, [pts], isClosed=True, color=(0, 255, 255), thickness=2)
            cv2.putText(out, name, tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (0, 255, 255), 2, cv2.LINE_AA)

    # Zone currently being drawn — magenta, with numbered corners
    if draft_points:
        pts = np.array(draft_points, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [pts], isClosed=len(draft_points) >= 3, color=(255, 0, 255), thickness=2)
        for i, (x, y) in enumerate(draft_points):
            cv2.circle(out, (int(x), int(y)), 5, (255, 0, 255), -1)
            cv2.putText(out, str(i + 1), (int(x) + 8, int(y) - 8), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def load_zones():
    if os.path.isfile(config.ZONES_PATH):
        with open(config.ZONES_PATH, "r") as f:
            return json.load(f)
    return {}


def save_zones(zones):
    with open(config.ZONES_PATH, "w") as f:
        json.dump(zones, f, indent=2)


def render_zone_editor(source):
    st.subheader("Restricted zone setup")
    st.caption("Capture a reference frame, then click each corner of your restricted area in order. "
               "3+ clicks make a zone.")

    if st.button("Capture reference frame"):
        frame = _capture_reference_frame(source)
        if frame is None:
            st.error("Could not read from the selected video source. Check the webcam index or file path.")
        else:
            st.session_state["zone_ref_frame"] = frame
            st.session_state["zone_draft_points"] = []
            st.session_state["zone_last_click"] = None

    frame = st.session_state.get("zone_ref_frame")
    if frame is None:
        st.info("No reference frame captured yet.")
        return load_zones()

    zones = load_zones()
    st.session_state.setdefault("zone_draft_points", [])
    st.session_state.setdefault("zone_last_click", None)

    display_img = _render_overlays(frame, zones, st.session_state.zone_draft_points)
    coords = streamlit_image_coordinates(
        Image.fromarray(display_img),
        key="zone_click_canvas",
        width=config.FRAME_WIDTH,
    )

    if coords is not None:
        click = (coords["x"], coords["y"])
        if click != st.session_state.zone_last_click:
            st.session_state.zone_draft_points.append([click[0], click[1]])
            st.session_state.zone_last_click = click
            st.rerun()

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Undo last point") and st.session_state.zone_draft_points:
            st.session_state.zone_draft_points.pop()
            st.session_state.zone_last_click = None
            st.rerun()
    with col2:
        if st.button("Clear points"):
            st.session_state.zone_draft_points = []
            st.session_state.zone_last_click = None
            st.rerun()

    n_points = len(st.session_state.zone_draft_points)
    zone_name = st.text_input("Zone name", value=f"restricted_area_{len(zones) + 1}")
    can_save = n_points >= 3

    if st.button("Save this zone", type="primary", disabled=not can_save):
        zones[zone_name] = st.session_state.zone_draft_points.copy()
        save_zones(zones)
        st.session_state.zone_draft_points = []
        st.session_state.zone_last_click = None
        st.success(f"Saved zone '{zone_name}' with {len(zones[zone_name])} points.")
        st.rerun()

    if not can_save:
        st.caption(f"Click at least 3 points on the image above to define a zone (currently {n_points}).")

    st.divider()
    if zones:
        st.write("Current zones:", {name: f"{len(pts)} points" for name, pts in zones.items()})
        zone_to_delete = st.selectbox("Delete a zone", ["—"] + list(zones.keys()))
        if zone_to_delete != "—" and st.button(f"Delete '{zone_to_delete}'"):
            zones.pop(zone_to_delete, None)
            save_zones(zones)
            st.success(f"Deleted zone '{zone_to_delete}'.")
            st.rerun()
    else:
        st.caption("No zones defined yet — monitoring will run with detection/tracking only, no zone rules.")

    with st.expander("Advanced: type exact coordinates instead"):
        st.caption("Format: one 'x,y' pair per line, at least 3 points.")
        manual_name = st.text_input("Zone name", value="restricted_area_manual", key="manual_zone_name")
        manual_text = st.text_area("Polygon points", value="100,100\n400,100\n400,350\n100,350", height=120)
        if st.button("Save manual polygon"):
            manual_points = _parse_manual_coords(manual_text)
            if len(manual_points) >= 3:
                zones[manual_name] = manual_points
                save_zones(zones)
                st.success(f"Saved zone '{manual_name}'.")
                st.rerun()
            else:
                st.warning("Need at least 3 valid 'x,y' points.")

    return zones


def _parse_manual_coords(text):
    points = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.replace(" ", "").split(",")
        if len(parts) != 2:
            continue
        try:
            x, y = int(float(parts[0])), int(float(parts[1]))
            points.append([x, y])
        except ValueError:
            continue
    return points
