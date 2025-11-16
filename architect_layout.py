# app.py — Complete 3D Architectural Layout Generator
import streamlit as st
import numpy as np
import plotly.graph_objects as go
import io
import os

# Detect Streamlit Cloud (prevents Kaleido errors)
IS_CLOUD = os.environ.get("STREAMLIT_SERVER_STATUS", "") != ""

st.set_page_config(layout="wide", page_title="3D Architectural Layout Generator — Pro")
st.title("🏠 3D Architectural Layout Generator — Pro")

# ---------------- Sidebar Inputs ----------------
with st.sidebar:
    st.header("Site & Grid")
    PLOT_WIDTH = st.number_input("Plot width (m)", value=14.0, min_value=1.0, step=0.5)
    PLOT_DEPTH = st.number_input("Plot depth (m)", value=24.0, min_value=1.0, step=0.5)
    front_setback = st.number_input("Front setback (m)", value=4.5, min_value=0.0, step=0.1)
    rear_setback = st.number_input("Rear setback (m)", value=3.0, min_value=0.0, step=0.1)
    left_setback = st.number_input("Left setback (m)", value=2.0, min_value=0.0, step=0.1)
    right_setback = st.number_input("Right setback (m)", value=2.0, min_value=0.0, step=0.1)
    grid_snap_cm = st.number_input("Grid snap (cm)", value=50, min_value=10)

    st.markdown("---")
    st.subheader("Rooms")
    car_w = st.number_input("Car porch width (m)", value=3.2, step=0.1)
    car_d = st.number_input("Car porch depth (m)", value=5.5, step=0.1)
    bedroom_area = st.number_input("Bedroom min area (m²)", value=12.0, step=0.5)
    bedrooms_count = st.number_input("Bedrooms count", value=3, step=1, min_value=0)
    bath_area = st.number_input("Bathroom area (m²)", value=4.0, step=0.5)
    lounge_area = st.number_input("Lounge area (m²)", value=20.0, step=0.5)

    st.markdown("---")
    st.subheader("Appearance")
    wall_thickness = st.number_input("Wall thickness (m)", value=0.2, step=0.05)
    room_height = st.number_input("Room height (m)", value=3.0, step=0.1)
    show_2d = st.checkbox("Show 2D floor plan", value=True)
    generate_btn = st.button("Generate Layout")

# ---------------- Utility functions ----------------
def to_grid(meters, snap_cm):
    cell = snap_cm / 100.0
    return max(1, int(round(meters / cell))), cell

def area_to_dims(area, aspect_ratio=1.3):
    w = (area * aspect_ratio) ** 0.5
    h = area / w
    return round(w, 3), round(h, 3)

def cuboid_coords(x, y, dx, dy, dz):
    X = [x, x+dx, x+dx, x, x, x+dx, x+dx, x]
    Y = [y, y, y+dy, y+dy, y, y, y+dy, y+dy]
    Z = [0, 0, 0, 0, dz, dz, dz, dz]
    I = [0,0,0,4,4,7,1,1,2,3,5,6]
    J = [1,2,3,5,6,4,5,2,6,7,6,7]
    K = [2,3,1,6,7,5,2,3,7,4,7,5]
    return X, Y, Z, I, J, K

def add_wall_mesh(fig, x, y, dx, dy, h, color="#888888", opacity=0.95):
    X, Y, Z, I, J, K = cuboid_coords(x, y, dx, dy, h)
    fig.add_trace(go.Mesh3d(
        x=X, y=Y, z=Z, i=I, j=J, k=K,
        color=color, opacity=opacity, flatshading=True,
        lighting=dict(ambient=0.8, diffuse=0.5, specular=0.1, roughness=0.9),
        hoverinfo="skip", showscale=False
    ))

def room_center_text(x, y, dx, dy, h, name, area):
    cx, cy, cz = x + dx/2, y + dy/2, h + 0.05
    text = f"{name}<br>{area:.1f} m²<br>{dx:.2f} × {dy:.2f} m"
    return cx, cy, cz, text

def add_door_marker(fig2d, x, y, w, orientation="horizontal", color="#3b3b3b"):
    if orientation == "horizontal":
        xs = [x - w/2, x + w/2]
        ys = [y, y]
    else:
        xs = [x, x]
        ys = [y - w/2, y + w/2]
    fig2d.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=6, color=color), hoverinfo="none", showlegend=False))

def add_window_marker(fig2d, x, y, w, orientation="horizontal", color="#7FB3D5"):
    if orientation == "horizontal":
        xs = [x - w/2, x + w/2]
        ys = [y, y]
    else:
        xs = [x, x]
        ys = [y - w/2, y + w/2]
    fig2d.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=3, dash="dash", color=color), hoverinfo="none", showlegend=False))

# ---------------- Main logic ----------------
if generate_btn:
    grid_w, cell_m = to_grid(PLOT_WIDTH, grid_snap_cm)
    grid_h, _ = to_grid(PLOT_DEPTH, grid_snap_cm)
    left_c, _ = to_grid(left_setback, grid_snap_cm)
    right_c, _ = to_grid(right_setback, grid_snap_cm)
    front_c, _ = to_grid(front_setback, grid_snap_cm)
    rear_c, _ = to_grid(rear_setback, grid_snap_cm)

    build_w = grid_w - left_c - right_c
    build_h = grid_h - front_c - rear_c

    if build_w <= 0 or build_h <= 0:
        st.error("Setbacks too large — no buildable space.")
        st.stop()

    # Rooms
    rooms = [("Car Porch", car_w, car_d)]
    lw, lh = area_to_dims(lounge_area)
    rooms.append(("Lounge", lw, lh))
    for i in range(1, int(bedrooms_count)+1):
        bw, bh = area_to_dims(bedroom_area)
        rooms.append((f"Bedroom {i}", bw, bh))
    bw, bh = area_to_dims(bath_area)
    rooms.append(("Bath", bw, bh))
    rooms.sort(key=lambda x: x[1]*x[2], reverse=True)

    layout = {}
    cursor_x, cursor_y, max_row_height = 0, 0, 0
    for name, w_m, h_m in rooms:
        w_cells = max(1, int(round(w_m/cell_m)))
        h_cells = max(1, int(round(h_m/cell_m)))
        if cursor_x + w_cells > build_w:
            cursor_x = 0
            cursor_y += max_row_height
            max_row_height = 0
        if cursor_y + h_cells > build_h:
            st.warning(f"{name} cannot fit in buildable area!")
            continue
        layout[name] = (cursor_x, cursor_y, w_cells, h_cells)
        cursor_x += w_cells
        max_row_height = max(max_row_height, h_cells)

    built_area = sum(w*h*cell_m*cell_m for (_, _, w, h) in layout.values())
    total_area = PLOT_WIDTH*PLOT_DEPTH
    coverage = built_area / total_area * 100
    st.success(f"Coverage Achieved: **{coverage:.1f}%**")

    # ---------------- 3D Visualization ----------------
    cmap = {"Car Porch": "#c7c9cc", "Lounge": "#f4a261", "Bath": "#9b2226"}
    for i in range(1, int(bedrooms_count)+1):
        cmap[f"Bedroom {i}"] = "#bde0fe"

    fig3d = go.Figure()
    h = room_height
    wall_h = h
    wall_color = "#333333"
    floor_color_map = {"Car Porch": "#d1d5d9", "Lounge": "#e7c8a9", "Bath": "#e6eef6"}
    for k in cmap.keys():
        if k not in floor_color_map:
            floor_color_map[k] = cmap[k]

    add_wall_mesh(fig3d, 0.0, 0.0, PLOT_WIDTH, PLOT_DEPTH, 0.02, color="#222222", opacity=0.3)

    build_x0, build_y0 = left_setback, front_setback
    build_dx, build_dy = build_w*cell_m, build_h*cell_m
    bx = [build_x0, build_x0+build_dx, build_x0+build_dx, build_x0, build_x0]
    by = [build_y0, build_y0, build_y0+build_dy, build_y0+build_dy, build_y0]
    bz = [0.02]*len(bx)
    fig3d.add_trace(go.Scatter3d(x=bx, y=by, z=bz, mode="lines",
                                 line=dict(dash="dash", width=4, color="#555555"),
                                 showlegend=False, hoverinfo="none"))

    label_xs, label_ys, label_zs, label_texts = [], [], [], []
    for name, (gx, gy, gw, gh) in layout.items():
        ox = left_setback + gx*cell_m
        oy = front_setback + gy*cell_m
        dxm, dym = gw*cell_m, gh*cell_m

        add_wall_mesh(fig3d, ox, oy, dxm, dym, 0.02, color=floor_color_map.get(name, "#cccccc"), opacity=1.0)
        add_wall_mesh(fig3d, ox-wall_thickness/2, oy-wall_thickness/2, wall_thickness, dym+wall_thickness, wall_h, color=wall_color, opacity=0.95)
        add_wall_mesh(fig3d, ox+dxm-wall_thickness/2, oy-wall_thickness/2, wall_thickness, dym+wall_thickness, wall_h, color=wall_color, opacity=0.95)
        add_wall_mesh(fig3d, ox-wall_thickness/2, oy-wall_thickness/2, dxm+wall_thickness, wall_thickness, wall_h, color=wall_color, opacity=0.95)
        add_wall_mesh(fig3d, ox-wall_thickness/2, oy+dym-wall_thickness/2, dxm+wall_thickness, wall_thickness, wall_h, color=wall_color, opacity=0.95)

        door_w = min(0.9, dxm*0.3)
        add_wall_mesh(fig3d, ox+dxm/2-door_w/2, oy-wall_thickness/2-0.001, door_w, 0.01, 0.05, color="#5D4037", opacity=1.0)

        win_w = min(1.2, dxm*0.25)
        if dxm > 3.0:
            add_wall_mesh(fig3d, ox+dxm*0.15-win_w/2, oy+dym-wall_thickness/2+0.001, win_w, 0.01, 0.02, color="#9AD0E5", opacity=0.8)
            add_wall_mesh(fig3d, ox+dxm*0.85-win_w/2, oy+dym-wall_thickness/2+0.001, win_w, 0.01, 0.02, color="#9AD0E5", opacity=0.8)

        cx, cy, cz, txt = room_center_text(ox, oy, dxm, dym, h, name, dxm*dym)
        label_xs.append(cx)
        label_ys.append(cy)
        label_zs.append(cz)
        label_texts.append(txt)

    if label_texts:
        fig3d.add_trace(go.Scatter3d(
            x=label_xs, y=label_ys, z=label_zs,
            mode="text",
            text=label_texts,
            textfont=dict(size=11, color="#111"),
            hoverinfo="none",
            showlegend=False
        ))

    # Compass
    compass_x = left_setback + build_dx - 0.6
    compass_y = front_setback + build_dy - 0.6
    fig3d.add_trace(go.Cone(x=[compass_x], y=[compass_y], z=[h+0.2], u=[0], v=[1], w=[0.2], showscale=False, sizemode="absolute", sizeref=0.5, anchor="tail", hoverinfo="none"))
    fig3d.add_trace(go.Scatter3d(x=[compass_x], y=[compass_y], z=[h+0.35], mode="text", text=["N"], textfont=dict(size=12, color="#111"), showlegend=False, hoverinfo="none"))

    fig3d.update_layout(
        scene=dict(
            xaxis_title='Width (m)', yaxis_title='Depth (m)', zaxis_title='Height (m)',
            aspectmode='data', xaxis=dict(showgrid=False), yaxis=dict(showgrid=False),
            zaxis=dict(showgrid=False), bgcolor="white",
            camera=dict(eye=dict(x=1.7, y=-2.2, z=1.2))
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="#fbfbfb"
    )

    # ---------------- 2D Floor Plan ----------------
    fig2d = None
    if show_2d:
        fig2d = go.Figure()
        fig2d.add_shape(type="rect", x0=0, y0=0, x1=PLOT_WIDTH, y1=PLOT_DEPTH,
                        line=dict(color="#222222", width=2))
        fig2d.add_shape(type="rect", x0=left_setback, y0=front_setback, x1=left_setback + build_dx, y1=front_setback + build_dy,
                        line=dict(color="#666666", width=1, dash="dash"))

        for name, (gx, gy, gw, gh) in layout.items():
            ox = left_setback + gx * cell_m
            oy = front_setback + gy * cell_m
            dxm = gw * cell_m
            dym = gh * cell_m
            color = floor_color_map.get(name, "#dddddd")
            fig2d.add_shape(type="rect", x0=ox, y0=oy, x1=ox + dxm, y1=oy + dym,
                            fillcolor=color, line=dict(color="#333333", width=2))
            area_m2 = dxm * dym
            fig2d.add_trace(go.Scatter(x=[ox + dxm/2], y=[oy + dym/2], mode="text",
                                       text=[f"{name}\n{area_m2:.1f} m²\n{dxm:.2f}×{dym:.2f} m"],
                                       textfont=dict(size=11, color="#222"), showlegend=False, hoverinfo="none"))

            door_w = min(0.9, dxm * 0.3)
            add_door_marker(fig2d, ox + dxm/2, oy, door_w, orientation="horizontal")
            if dxm > 3.0:
                win_w = min(1.2, dxm * 0.25)
                add_window_marker(fig2d, ox + dxm*0.15, oy + dym, win_w, orientation="horizontal")
                add_window_marker(fig2d, ox + dxm*0.85, oy + dym, win_w, orientation="horizontal")

        fig2d.update_xaxes(range=[-0.5, PLOT_WIDTH + 0.5], constrain="domain", showgrid=False, zeroline=False, mirror=True)
        fig2d.update_yaxes(range=[-0.5, PLOT_DEPTH + 0.5], scaleanchor="x", scaleratio=1, showgrid=False, zeroline=False, autorange=False)
        fig2d.update_layout(width=600, height=600, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="#ffffff")
        fig2d.add_annotation(dict(x= PLOT_WIDTH - 0.5, y= PLOT_DEPTH - 0.2, text="N", showarrow=True, ax=0, ay=-20, font=dict(size=12)))

    # ---------------- Render UI ----------------
    if fig2d is not None:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("3D View")
            st.plotly_chart(fig3d, use_container_width=True, height=700)
            st.markdown("**Tips:** Rotate with mouse / pinch-zoom. Use the 3D view to visualize walls, windows, and doors.")
        with col2:
            st.subheader("2D Floor Plan")
            st.plotly_chart(fig2d, use_container_width=True, height=700)
    else:
        st.plotly_chart(fig3d, use_container_width=True, height=700)