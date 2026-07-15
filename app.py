from __future__ import annotations

from datetime import datetime
import hashlib
from math import asin, cos, radians, sin, sqrt
import os

import pandas as pd
import pydeck as pdk
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from supabase import create_client


st.set_page_config(
    page_title="PKP Live",
    page_icon="🚴",
    layout="wide",
)

REFRESH_SECONDS = 5
DELAYED_SIGNAL_SECONDS = 20
TRACK_SESSION_GAP_SECONDS = 120
DEFAULT_TRAINING_CODE = "PKP-DEMO"
DEFAULT_MAP_LATITUDE = 52.2297
DEFAULT_MAP_LONGITUDE = 21.0122
DEFAULT_MAP_ZOOM = 6
OSM_TILE_URL = "https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.png"
EARTH_RADIUS_M = 6_371_000
RIDER_COLORS = [
    [230, 57, 70, 230],
    [29, 185, 84, 230],
    [0, 122, 255, 230],
    [255, 149, 0, 230],
    [156, 39, 176, 230],
    [0, 188, 212, 230],
    [255, 64, 129, 230],
    [124, 179, 66, 230],
]


@st.cache_resource
def get_supabase():
    supabase_url = get_config_value("SUPABASE_URL")
    supabase_key = get_config_value("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Brakuje konfiguracji Supabase."
        )

    return create_client(
        supabase_url,
        supabase_key,
    )


def init_state():
    if "selected_rider_id" not in st.session_state:
        st.session_state.selected_rider_id = None

    if "preview_rider_id" not in st.session_state:
        st.session_state.preview_rider_id = None

    if "preview_session_id" not in st.session_state:
        st.session_state.preview_session_id = None


def get_config_value(key, default=None):
    env_value = os.getenv(key)

    if env_value:
        return env_value

    try:
        return st.secrets[key]

    except (
        KeyError,
        StreamlitSecretNotFoundError,
        FileNotFoundError,
    ):
        return default


def has_supabase_config():
    return bool(
        get_config_value("SUPABASE_URL")
        and get_config_value("SUPABASE_KEY")
    )


def get_tracking_code():
    return get_config_value(
        "TRACKING_CODE",
        DEFAULT_TRAINING_CODE,
    ).strip().upper()


def get_mobile_app_url():
    return get_config_value("MOBILE_APP_URL")


def rider_color(rider_id):
    digest = hashlib.md5(
        rider_id.encode("utf-8")
    ).digest()
    color_index = digest[0] % len(RIDER_COLORS)

    return RIDER_COLORS[color_index]


def haversine_m(lat1, lon1, lat2, lon2):
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    value = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    return 2 * EARTH_RADIUS_M * asin(sqrt(value))


def calculate_distance_km(track_df):
    if len(track_df) < 2:
        return 0.0

    distance_m = 0.0
    points = track_df[
        ["latitude", "longitude"]
    ].values.tolist()

    for previous, current in zip(points, points[1:]):
        distance_m += haversine_m(
            float(previous[0]),
            float(previous[1]),
            float(current[0]),
            float(current[1]),
        )

    return distance_m / 1000


def load_riders(training_code):
    response = (
        get_supabase()
        .table("riders")
        .select("*")
        .eq(
            "training_code",
            training_code,
        )
        .execute()
    )

    if not response.data:
        return pd.DataFrame()

    df = pd.DataFrame(response.data)

    df["updated_at"] = pd.to_datetime(
        df["updated_at"],
        utc=True,
        errors="coerce",
    )

    df["seconds_ago"] = (
        pd.Timestamp.now(tz="UTC")
        - df["updated_at"]
    ).dt.total_seconds().round()

    df["status"] = "aktywny"

    df.loc[
        df["seconds_ago"] > DELAYED_SIGNAL_SECONDS,
        "status",
    ] = "opóźniony"

    df.loc[
        df["seconds_ago"] > 60,
        "status",
    ] = "brak sygnału"

    df.loc[
        df["is_active"] == False,
        "status",
    ] = "zakończył"

    df["speed_label"] = df[
        "speed_kmh"
    ].apply(
        lambda value: (
            f"{value:.1f} km/h"
            if pd.notna(value)
            else "brak danych"
        )
    )

    df["accuracy_label"] = df[
        "accuracy_m"
    ].apply(
        lambda value: (
            f"{value:.0f} m"
            if pd.notna(value)
            else "brak danych"
        )
    )

    df["updated_label"] = df[
        "seconds_ago"
    ].apply(
        lambda value: (
            f"{int(value)} s temu"
            if pd.notna(value)
            else "brak danych"
        )
    )

    df["marker_color"] = df.apply(
        lambda row: (
            rider_color(row["rider_id"])
            if row["status"] in ["aktywny", "opóźniony"]
            else [150, 150, 150, 180]
        ),
        axis=1,
    )

    return df.reset_index(drop=True)


def load_tracks(training_code):
    response = (
        get_supabase()
        .table("rider_positions")
        .select(
            "rider_id,"
            "nickname,"
            "training_code,"
            "latitude,"
            "longitude,"
            "speed_kmh,"
            "accuracy_m,"
            "recorded_at"
        )
        .eq(
            "training_code",
            training_code,
        )
        .order("recorded_at")
        .limit(10000)
        .execute()
    )

    if not response.data:
        return pd.DataFrame()

    df = pd.DataFrame(response.data)
    df["recorded_at"] = pd.to_datetime(
        df["recorded_at"],
        utc=True,
        errors="coerce",
    )

    return df.dropna(
        subset=[
            "recorded_at",
            "latitude",
            "longitude",
        ]
    ).reset_index(drop=True)


def build_active_paths(
    track_df,
    riders_df,
):
    if riders_df.empty:
        return pd.DataFrame()

    active_rider_ids = riders_df["rider_id"].tolist()
    track_parts = []

    if not track_df.empty:
        track_parts.append(
            track_df[
                track_df["rider_id"].isin(active_rider_ids)
            ]
        )

    current_positions = riders_df[
        [
            "rider_id",
            "nickname",
            "latitude",
            "longitude",
            "updated_at",
        ]
    ].rename(
        columns={
            "updated_at": "recorded_at",
        }
    )
    track_parts.append(current_positions)

    all_tracks = pd.concat(
        track_parts,
        ignore_index=True,
    )
    all_tracks = all_tracks.dropna(
        subset=[
            "latitude",
            "longitude",
        ]
    ).copy()
    all_tracks["latitude"] = pd.to_numeric(
        all_tracks["latitude"],
        errors="coerce",
    )
    all_tracks["longitude"] = pd.to_numeric(
        all_tracks["longitude"],
        errors="coerce",
    )
    all_tracks = all_tracks.dropna(
        subset=[
            "latitude",
            "longitude",
        ]
    )

    if all_tracks.empty:
        return pd.DataFrame()

    rows = []

    for rider_id, group in all_tracks.groupby(
        "rider_id",
        sort=False,
    ):
        group = group.sort_values("recorded_at")

        time_gaps = (
            group["recorded_at"]
            .diff()
            .dt.total_seconds()
        )
        session_numbers = (
            time_gaps > TRACK_SESSION_GAP_SECONDS
        ).cumsum()
        group = group[
            session_numbers == session_numbers.iloc[-1]
        ]

        if len(group) < 2:
            continue

        rows.append(
            {
                "rider_id": rider_id,
                "nickname": group[
                    "nickname"
                ].iloc[-1],
                "path": group[
                    ["longitude", "latitude"]
                ].values.tolist(),
                "path_color": rider_color(
                    rider_id
                ),
            }
        )

    return pd.DataFrame(rows)


def get_rider_session_tracks(
    track_df,
    riders_df,
    rider_id,
):
    if not rider_id or track_df.empty:
        return pd.DataFrame()

    selected_tracks = track_df[
        track_df["rider_id"] == rider_id
    ].copy()

    if selected_tracks.empty:
        return pd.DataFrame()

    if riders_df is not None and not riders_df.empty:
        current_position = riders_df[
            riders_df["rider_id"] == rider_id
        ]

        if not current_position.empty:
            row = current_position.iloc[0]
            selected_tracks = pd.concat(
                [
                    selected_tracks,
                    pd.DataFrame(
                        [
                            {
                                "rider_id": rider_id,
                                "nickname": row["nickname"],
                                "latitude": row["latitude"],
                                "longitude": row["longitude"],
                                "recorded_at": row["updated_at"],
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )

    selected_tracks = selected_tracks.dropna(
        subset=[
            "latitude",
            "longitude",
        ]
    ).copy()
    selected_tracks["latitude"] = pd.to_numeric(
        selected_tracks["latitude"],
        errors="coerce",
    )
    selected_tracks["longitude"] = pd.to_numeric(
        selected_tracks["longitude"],
        errors="coerce",
    )
    selected_tracks = (
        selected_tracks
        .dropna(subset=["latitude", "longitude"])
        .sort_values("recorded_at")
    )

    if selected_tracks.empty:
        return pd.DataFrame()

    time_gaps = (
        selected_tracks["recorded_at"]
        .diff()
        .dt.total_seconds()
    )
    session_numbers = (
        time_gaps > TRACK_SESSION_GAP_SECONDS
    ).cumsum()
    selected_tracks["session_number"] = session_numbers.values
    selected_tracks["session_id"] = (
        selected_tracks["rider_id"].astype(str)
        + "_"
        + selected_tracks["session_number"].astype(str)
    )

    return selected_tracks


def get_last_session_tracks(
    track_df,
    riders_df,
    rider_id,
):
    selected_tracks = get_rider_session_tracks(
        track_df,
        riders_df,
        rider_id,
    )

    if selected_tracks.empty:
        return pd.DataFrame()

    last_session_id = selected_tracks[
        "session_id"
    ].iloc[-1]

    selected_tracks = selected_tracks[
        selected_tracks["session_id"] == last_session_id
    ]

    return selected_tracks


def build_preview_path(
    track_df,
    riders_df,
    rider_id,
    session_id=None,
):
    selected_tracks = get_rider_session_tracks(
        track_df,
        riders_df,
        rider_id,
    )

    if session_id:
        selected_tracks = selected_tracks[
            selected_tracks["session_id"] == session_id
        ]
    elif not selected_tracks.empty:
        last_session_id = selected_tracks[
            "session_id"
        ].iloc[-1]
        selected_tracks = selected_tracks[
            selected_tracks["session_id"] == last_session_id
        ]

    if len(selected_tracks) < 2:
        return pd.DataFrame()

    return pd.DataFrame(
        [
            {
                "rider_id": rider_id,
                "nickname": selected_tracks[
                    "nickname"
                ].iloc[-1],
                "path": selected_tracks[
                    ["longitude", "latitude"]
                ].values.tolist(),
                "path_color": [20, 20, 20, 240],
            }
        ]
    )


def add_active_track_stats(active_riders, tracks):
    if active_riders.empty:
        return active_riders

    rows = []

    for _, rider in active_riders.iterrows():
        rider_data = rider.to_dict()
        session_tracks = get_last_session_tracks(
            tracks,
            active_riders,
            rider["rider_id"],
        )
        point_count = len(session_tracks)

        if point_count < 2:
            distance_km = 0.0
            average_speed_kmh = None
            duration_seconds = 0
        else:
            distance_km = calculate_distance_km(
                session_tracks
            )
            duration_seconds = (
                session_tracks["recorded_at"].iloc[-1]
                - session_tracks["recorded_at"].iloc[0]
            ).total_seconds()
            duration_hours = duration_seconds / 3600
            average_speed_kmh = (
                distance_km / duration_hours
                if duration_hours > 0
                else None
            )

        rider_data["active_distance_label"] = (
            f"{distance_km:.2f} km"
        )
        rider_data["active_average_speed_label"] = (
            f"{average_speed_kmh:.1f} km/h"
            if average_speed_kmh is not None
            else "brak danych"
        )
        rider_data["active_duration_label"] = (
            f"{int(duration_seconds // 60)} min"
            if duration_seconds >= 60
            else f"{int(duration_seconds)} s"
        )
        rider_data["active_points_label"] = str(point_count)
        rows.append(rider_data)

    return pd.DataFrame(rows)


def build_recent_activity_sessions(riders, tracks):
    if riders.empty or tracks.empty:
        return pd.DataFrame()

    rows = []

    for _, rider in riders.iterrows():
        sessions = get_rider_session_tracks(
            tracks,
            riders,
            rider["rider_id"],
        )

        if sessions.empty:
            continue

        last_session_id = sessions[
            "session_id"
        ].iloc[-1]

        for session_id, session_tracks in sessions.groupby(
            "session_id",
            sort=False,
        ):
            session_tracks = session_tracks.sort_values(
                "recorded_at"
            )

            if len(session_tracks) < 2:
                continue

            distance_km = calculate_distance_km(
                session_tracks
            )
            duration_hours = (
                session_tracks["recorded_at"].iloc[-1]
                - session_tracks["recorded_at"].iloc[0]
            ).total_seconds() / 3600
            average_speed_kmh = (
                distance_km / duration_hours
                if duration_hours > 0
                else None
            )
            seconds_ago = (
                pd.Timestamp.now(tz="UTC")
                - session_tracks["recorded_at"].iloc[-1]
            ).total_seconds()

            rows.append(
                {
                    "session_id": session_id,
                    "rider_id": rider["rider_id"],
                    "nickname": session_tracks[
                        "nickname"
                    ].iloc[-1],
                    "status": (
                        rider["status"]
                        if session_id == last_session_id
                        else "zakończony"
                    ),
                    "speed_label": rider["speed_label"],
                    "average_speed_label": (
                        f"{average_speed_kmh:.1f} km/h"
                        if average_speed_kmh is not None
                        else "brak danych"
                    ),
                    "distance_label": f"{distance_km:.2f} km",
                    "updated_label": (
                        f"{int(seconds_ago)} s temu"
                        if pd.notna(seconds_ago)
                        else "brak danych"
                    ),
                    "session_end": session_tracks[
                        "recorded_at"
                    ].iloc[-1],
                }
            )

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values("session_end", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )


def get_points_bounds(riders_df, preview_path=None):
    points = []

    if not riders_df.empty:
        points.extend(
            riders_df[
                ["longitude", "latitude"]
            ].dropna().values.tolist()
        )

    if preview_path is not None and not preview_path.empty:
        points.extend(preview_path.iloc[0]["path"])

    if not points:
        return None

    longitudes = [float(point[0]) for point in points]
    latitudes = [float(point[1]) for point in points]

    return {
        "latitude": (min(latitudes) + max(latitudes)) / 2,
        "longitude": (min(longitudes) + max(longitudes)) / 2,
        "lat_span": max(latitudes) - min(latitudes),
        "lon_span": max(longitudes) - min(longitudes),
    }


def get_zoom_for_bounds(bounds):
    span = max(bounds["lat_span"], bounds["lon_span"])

    if span <= 0.002:
        return 15

    if span <= 0.01:
        return 13

    if span <= 0.05:
        return 11

    if span <= 0.2:
        return 9

    if span <= 1:
        return 7

    return 5


def get_map_view(riders_df, preview_path=None):
    selected_id = st.session_state.selected_rider_id

    if selected_id and not riders_df.empty:
        selected = riders_df[
            riders_df["rider_id"] == selected_id
        ]

        if not selected.empty:
            row = selected.iloc[0]

            return pdk.ViewState(
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                zoom=15,
                pitch=0,
            )

    bounds = get_points_bounds(
        riders_df,
        preview_path,
    )

    if bounds:
        return pdk.ViewState(
            latitude=float(bounds["latitude"]),
            longitude=float(bounds["longitude"]),
            zoom=get_zoom_for_bounds(bounds),
            pitch=0,
        )

    if riders_df.empty:
        return pdk.ViewState(
            latitude=DEFAULT_MAP_LATITUDE,
            longitude=DEFAULT_MAP_LONGITUDE,
            zoom=DEFAULT_MAP_ZOOM,
            pitch=0,
        )

    return pdk.ViewState(
        latitude=float(riders_df["latitude"].mean()),
        longitude=float(riders_df["longitude"].mean()),
        zoom=11,
        pitch=0,
    )


def make_map(riders_df, tracks_df, preview_path=None):
    layers = [
        pdk.Layer(
            "TileLayer",
            data=OSM_TILE_URL,
            min_zoom=0,
            max_zoom=19,
            tile_size=256,
            render_sub_layers={
                "@@type": "BitmapLayer",
                "data": None,
                "image": "@@=data",
                "bounds": (
                    "@@=[bbox.west, bbox.south, "
                    "bbox.east, bbox.north]"
                ),
            },
        )
    ]

    active_paths = build_active_paths(
        tracks_df,
        riders_df,
    )

    if not active_paths.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=active_paths,
                id="active_tracks",
                get_path="path",
                get_color="path_color",
                get_width=8,
                width_min_pixels=5,
                rounded=True,
                pickable=False,
            )
        )

    if preview_path is not None and not preview_path.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=preview_path,
                id="preview_track",
                get_path="path",
                get_color="path_color",
                get_width=12,
                width_min_pixels=7,
                rounded=True,
                pickable=False,
            )
        )

    if not riders_df.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=riders_df,
                id="riders",
                get_position="[longitude, latitude]",
                get_radius=55,
                get_fill_color="marker_color",
                get_line_color=[255, 255, 255],
                line_width_min_pixels=2,
                stroked=True,
                pickable=True,
            )
        )

        layers.append(
            pdk.Layer(
                "TextLayer",
                data=riders_df,
                id="labels",
                get_position="[longitude, latitude]",
                get_text="nickname",
                get_size=16,
                get_alignment_baseline="'bottom'",
                get_pixel_offset=[0, -14],
                get_color=[20, 20, 20],
                pickable=False,
            )
        )

    return pdk.Deck(
        layers=layers,
        initial_view_state=get_map_view(
            riders_df,
            preview_path,
        ),
        tooltip={
            "html": (
                "<b>{nickname}</b><br/>"
                "Prędkość: {speed_label}<br/>"
                "Dokładność: {accuracy_label}<br/>"
                "Status: {status}<br/>"
                "Aktualizacja: {updated_label}"
            )
        },
        map_style=None,
    )


def get_selected_rider_from_map(map_event):
    if not map_event or not hasattr(
        map_event,
        "selection",
    ):
        return None

    selection = map_event.selection

    def find_rider_id(value):
        if isinstance(value, dict):
            if value.get("rider_id"):
                return value["rider_id"]

            for nested_value in value.values():
                found = find_rider_id(nested_value)
                if found:
                    return found

        if isinstance(value, list):
            for item in value:
                found = find_rider_id(item)
                if found:
                    return found

        return None

    if isinstance(selection, dict):
        objects = selection.get("objects", {})
    else:
        objects = getattr(selection, "objects", {})

    return find_rider_id(objects)


@st.fragment(run_every=REFRESH_SECONDS)
def render_live_view(training_code):
    try:
        riders = load_riders(training_code)
        tracks = load_tracks(training_code)

    except Exception as exc:
        st.error(
            "Nie udało się pobrać danych z Supabase: "
            f"{exc}"
        )
        st.stop()

    if riders.empty:
        st.info(
            "Brak uczestników dla aktualnego kodu śledzenia."
        )

    if riders.empty:
        active_riders = pd.DataFrame()
    else:
        active_riders = riders[
            riders["status"].isin(["aktywny", "opóźniony"])
        ].reset_index(drop=True)

    if active_riders.empty:
        st.info(
            "Obecnie żaden uczestnik nie udostępnia aktywnie lokalizacji."
        )

    if riders.empty:
        recent_riders = pd.DataFrame()
    else:
        recent_riders = build_recent_activity_sessions(
            riders,
            tracks,
        )

    active_rider_ids = (
        active_riders["rider_id"].tolist()
        if not active_riders.empty
        else []
    )
    if tracks.empty or not active_rider_ids:
        active_tracks = pd.DataFrame()
    else:
        active_tracks = tracks[
            tracks["rider_id"].isin(active_rider_ids)
        ].reset_index(drop=True)

    active_riders = add_active_track_stats(
        active_riders,
        active_tracks,
    )

    selected_id = st.session_state.selected_rider_id
    preview_id = st.session_state.preview_rider_id
    preview_session_id = st.session_state.preview_session_id
    if active_riders.empty or not selected_id:
        selected_rider = pd.DataFrame()
    else:
        selected_rider = active_riders[
            active_riders["rider_id"] == selected_id
        ]

    col1, col2, col3 = st.columns(3)
    col1.metric("Uczestnicy online", len(active_riders))
    col2.metric("Punkty tras", len(active_tracks))
    col3.metric(
        "Wybrany uczestnik",
        (
            selected_rider.iloc[0]["nickname"]
            if not selected_rider.empty
            else "wszyscy"
        ),
    )

    preview_path = build_preview_path(
        tracks,
        riders,
        preview_id,
        preview_session_id,
    )

    map_event = st.pydeck_chart(
        make_map(
            active_riders,
            active_tracks,
            preview_path,
        ),
        height=620,
        use_container_width=True,
        selection_mode="single-object",
        on_select="rerun",
        key=(
            f"tracking_map_"
            f"{selected_id or 'all'}_"
            f"{preview_session_id or preview_id or 'live'}"
        ),
    )

    map_selected_rider_id = get_selected_rider_from_map(
        map_event
    )

    if (
        map_selected_rider_id
        and map_selected_rider_id
        != st.session_state.selected_rider_id
    ):
        st.session_state.selected_rider_id = map_selected_rider_id
        st.rerun()

    if st.session_state.selected_rider_id:
        if tracks.empty:
            selected_tracks = pd.DataFrame()
        else:
            selected_tracks = tracks[
                tracks["rider_id"]
                == st.session_state.selected_rider_id
            ]

        if selected_tracks.empty:
            st.info(
                "Wybrany uczestnik nie ma jeszcze zapisanego śladu."
            )
        else:
            st.caption(
                f"Pokazuję ślad: {len(selected_tracks)} punktów."
            )

    st.subheader("Aktywni uczestnicy")
    if active_riders.empty:
        st.caption(
            "Aktywni uczestnicy pojawią się, gdy ktoś udostępni lokalizację."
        )
    else:
        st.caption(
            "Na mapie widać tylko uczestników aktywnych teraz."
        )

        display_df = active_riders[
            [
                "nickname",
                "speed_label",
                "active_average_speed_label",
                "active_distance_label",
                "active_duration_label",
                "accuracy_label",
                "updated_label",
            ]
        ].rename(
            columns={
                "nickname": "Uczestnik",
                "speed_label": "Prędkość",
                "active_average_speed_label": "Średnia prędkość",
                "active_distance_label": "Dystans",
                "active_duration_label": "Czas aktywności",
                "accuracy_label": "Dokładność GPS",
                "updated_label": "Ostatnia aktualizacja",
            }
        )

        table_event = st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="riders_selection_table",
        )

        selected_rows = table_event.selection.rows

        if selected_rows:
            selected_row_number = selected_rows[0]
            newly_selected_id = active_riders.iloc[
                selected_row_number
            ]["rider_id"]

            if (
                newly_selected_id
                != st.session_state.selected_rider_id
            ):
                st.session_state.selected_rider_id = newly_selected_id
                st.rerun()

    st.subheader("20 ostatnich aktywności")
    if recent_riders.empty:
        st.caption("Brak historii aktywności dla tego kodu.")
    else:
        st.caption(
            "Kliknij wiersz, aby dorysować konkretną aktywność na mapie."
        )

        recent_df = recent_riders[
            [
                "nickname",
                "status",
                "speed_label",
                "average_speed_label",
                "distance_label",
                "updated_label",
            ]
        ].rename(
            columns={
                "nickname": "Uczestnik",
                "status": "Status",
                "speed_label": "Prędkość",
                "average_speed_label": "Średnia prędkość",
                "distance_label": "Dystans",
                "updated_label": "Ostatnia aktualizacja",
            }
        )

        recent_event = st.dataframe(
            recent_df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="recent_riders_table",
        )

        recent_rows = recent_event.selection.rows

        if recent_rows:
            recent_row_number = recent_rows[0]
            preview_rider_id = recent_riders.iloc[
                recent_row_number
            ]["rider_id"]
            preview_session_id = recent_riders.iloc[
                recent_row_number
            ]["session_id"]

            if (
                preview_rider_id
                != st.session_state.preview_rider_id
                or preview_session_id
                != st.session_state.preview_session_id
            ):
                st.session_state.preview_rider_id = preview_rider_id
                st.session_state.preview_session_id = preview_session_id
                st.rerun()

        if st.session_state.preview_session_id:
            preview_rider = recent_riders[
                recent_riders["session_id"]
                == st.session_state.preview_session_id
            ]

            if preview_rider.empty:
                st.caption("Podgląd trasy: brak wybranego uczestnika.")
            elif preview_path.empty:
                st.caption(
                    "Podgląd trasy: wybrany uczestnik nie ma jeszcze "
                    "co najmniej dwóch punktów trasy."
                )
            else:
                st.caption(
                    "Podgląd trasy: "
                    f"{preview_rider.iloc[0]['nickname']}"
                )

    st.caption(
        "Ostatnie odświeżenie: "
        f"{datetime.now().strftime('%H:%M:%S')}"
    )


init_state()

training_code = get_tracking_code()
mobile_app_url = get_mobile_app_url()

with st.sidebar:
    st.header("Podgląd")
    st.caption(
        "Panel służy tylko do śledzenia uczestników na mapie."
    )
    st.metric("Kod śledzenia", training_code)

    st.divider()
    st.subheader("Aplikacja mobilna")
    st.caption(
        "Aby udostępnić swój ślad na mapie, pobierz i uruchom "
        "aplikację mobilną PKP Live."
    )

    if mobile_app_url:
        st.link_button(
            "Pobierz aplikację",
            mobile_app_url,
            use_container_width=True,
        )
    else:
        st.caption(
            "Dodaj `MOBILE_APP_URL` w `.streamlit/secrets.toml`, "
            "aby pokazać link do pobrania."
        )

    with st.expander("Instrukcja instalacji"):
        st.markdown(
            """
1. Kliknij **Pobierz aplikację**.
2. Pobierz plik APK na telefon z Androidem.
3. Otwórz pobrany plik.
4. Jeśli telefon zapyta o zgodę, pozwól na instalację z tego źródła.
5. Zainstaluj aplikację i uruchom ją.
6. Wpisz swój pseudonim oraz kod śledzenia.
7. Kliknij **Rozpocznij tracking** i zezwól na lokalizację.
            """.strip()
        )

    if st.session_state.selected_rider_id:
        if st.button(
            "Pokaż wszystkich",
            use_container_width=True,
        ):
            st.session_state.selected_rider_id = None
            st.rerun()

    if st.session_state.preview_session_id:
        if st.button(
            "Ukryj podgląd trasy",
            use_container_width=True,
        ):
            st.session_state.preview_rider_id = None
            st.session_state.preview_session_id = None
            st.rerun()

    st.caption(
        f"Dane odświeżają się co {REFRESH_SECONDS} sekund."
    )

st.title("🚴 PKP Live")
st.caption(
    "Mapa aktywnych uczestników i podgląd ostatnich tras."
)

if not has_supabase_config():
    st.error(
        "Brakuje konfiguracji Supabase. "
        "Dodaj plik `.streamlit/secrets.toml` "
        "albo ustaw zmienne środowiskowe."
    )
    st.code(
        """
SUPABASE_URL = "https://..."
SUPABASE_KEY = "..."
TRACKING_CODE = "PKP-DEMO"
        """.strip(),
        language="toml",
    )
    st.stop()

render_live_view(training_code)
