from __future__ import annotations

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
import hashlib
import uuid

import pandas as pd
import pydeck as pdk
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_geolocation import streamlit_geolocation
from supabase import create_client


st.set_page_config(
    page_title="PKP Live",
    page_icon="🚴",
    layout="wide",
)

REFRESH_SECONDS = 5
MIN_POINT_DISTANCE_M = 8
MAX_POINT_INTERVAL_SECONDS = 20


@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def init_state():
    defaults = {
        "tracking": False,
        "nickname": "Łukasz",
        "training_code": "PKP-DEMO",
        "rider_id": str(uuid.uuid4()),
        "last_position": None,
        "last_saved_track_point": None,
        "selected_rider_id": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def normalize_position(raw):
    if not isinstance(raw, dict):
        return None

    coords = (
        raw.get("coords")
        if isinstance(raw.get("coords"), dict)
        else {}
    )

    latitude = raw.get(
        "latitude",
        coords.get("latitude"),
    )

    longitude = raw.get(
        "longitude",
        coords.get("longitude"),
    )

    accuracy = raw.get(
        "accuracy",
        coords.get("accuracy"),
    )

    speed = raw.get(
        "speed",
        coords.get("speed"),
    )

    if latitude is None or longitude is None:
        return None

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    try:
        accuracy_m = (
            round(float(accuracy), 1)
            if accuracy is not None
            else None
        )
    except (TypeError, ValueError):
        accuracy_m = None

    try:
        speed_kmh = (
            round(float(speed) * 3.6, 1)
            if speed is not None
            else None
        )
    except (TypeError, ValueError):
        speed_kmh = None

    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_m": accuracy_m,
        "speed_kmh": speed_kmh,
    }


def haversine_m(
    lat1,
    lon1,
    lat2,
    lon2,
):
    earth_radius_m = 6_371_000

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    value = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    return 2 * earth_radius_m * asin(sqrt(value))


def rider_color(rider_id):
    digest = hashlib.md5(
        rider_id.encode("utf-8")
    ).digest()

    return [
        60 + digest[0] % 170,
        60 + digest[1] % 170,
        60 + digest[2] % 170,
        220,
    ]


def save_current_position(position):
    now_iso = datetime.now(
        timezone.utc
    ).isoformat()

    payload = {
        "rider_id": st.session_state.rider_id,
        "nickname": (
            st.session_state.nickname.strip()
            or "Kolarz"
        ),
        "training_code": (
            st.session_state.training_code
            .strip()
            .upper()
            or "PKP-DEMO"
        ),
        "latitude": position["latitude"],
        "longitude": position["longitude"],
        "speed_kmh": position["speed_kmh"],
        "accuracy_m": position["accuracy_m"],
        "is_active": True,
        "updated_at": now_iso,
    }

    (
        get_supabase()
        .table("riders")
        .upsert(
            payload,
            on_conflict="rider_id,training_code",
        )
        .execute()
    )

    st.session_state.last_position = payload

    save_track_point_if_needed(payload)


def save_track_point_if_needed(position):
    previous = (
        st.session_state
        .last_saved_track_point
    )

    now = datetime.now(timezone.utc)

    should_save = previous is None

    if previous is not None:
        distance_m = haversine_m(
            previous["latitude"],
            previous["longitude"],
            position["latitude"],
            position["longitude"],
        )

        previous_time = datetime.fromisoformat(
            previous["recorded_at"]
        )

        elapsed_seconds = (
            now - previous_time
        ).total_seconds()

        should_save = (
            distance_m >= MIN_POINT_DISTANCE_M
            or elapsed_seconds
            >= MAX_POINT_INTERVAL_SECONDS
        )

    if not should_save:
        return

    track_payload = {
        "rider_id": position["rider_id"],
        "nickname": position["nickname"],
        "training_code": position["training_code"],
        "latitude": position["latitude"],
        "longitude": position["longitude"],
        "speed_kmh": position["speed_kmh"],
        "accuracy_m": position["accuracy_m"],
        "recorded_at": now.isoformat(),
    }

    (
        get_supabase()
        .table("rider_positions")
        .insert(track_payload)
        .execute()
    )

    st.session_state.last_saved_track_point = (
        track_payload
    )


def mark_inactive():
    training_code = (
        st.session_state.training_code
        .strip()
        .upper()
    )

    (
        get_supabase()
        .table("riders")
        .update(
            {
                "is_active": False,
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )
        .eq(
            "rider_id",
            st.session_state.rider_id,
        )
        .eq(
            "training_code",
            training_code,
        )
        .execute()
    )


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
            if row["status"] == "aktywny"
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

    return pd.DataFrame(response.data)


def build_paths(track_df):
    if track_df.empty:
        return pd.DataFrame()

    rows = []

    for rider_id, group in track_df.groupby(
        "rider_id",
        sort=False,
    ):
        group = group.sort_values(
            "recorded_at"
        )

        if len(group) < 2:
            continue

        rows.append(
            {
                "rider_id": rider_id,
                "nickname": (
                    group["nickname"].iloc[-1]
                ),
                "path": group[
                    ["longitude", "latitude"]
                ].values.tolist(),
                "path_color": rider_color(
                    rider_id
                ),
            }
        )

    return pd.DataFrame(rows)


def get_map_view(riders_df):
    selected_id = (
        st.session_state.selected_rider_id
    )

    if selected_id:
        selected = riders_df[
            riders_df["rider_id"]
            == selected_id
        ]

        if not selected.empty:
            row = selected.iloc[0]

            return pdk.ViewState(
                latitude=float(
                    row["latitude"]
                ),
                longitude=float(
                    row["longitude"]
                ),
                zoom=15,
                pitch=0,
            )

    return pdk.ViewState(
        latitude=float(
            riders_df["latitude"].mean()
        ),
        longitude=float(
            riders_df["longitude"].mean()
        ),
        zoom=11,
        pitch=0,
    )


def make_map(
    riders_df,
    tracks_df,
):
    layers = []

    paths_df = build_paths(tracks_df)

    if not paths_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=paths_df,
                get_path="path",
                get_color="path_color",
                get_width=5,
                width_min_pixels=3,
                rounded=True,
                pickable=True,
            )
        )

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=riders_df,
            get_position=(
                "[longitude, latitude]"
            ),
            get_radius=55,
            get_fill_color="marker_color",
            get_line_color=[
                255,
                255,
                255,
            ],
            line_width_min_pixels=2,
            stroked=True,
            pickable=True,
        )
    )

    layers.append(
        pdk.Layer(
            "TextLayer",
            data=riders_df,
            get_position=(
                "[longitude, latitude]"
            ),
            get_text="nickname",
            get_size=16,
            get_alignment_baseline=(
                "'bottom'"
            ),
            get_pixel_offset=[
                0,
                -14,
            ],
            get_color=[
                20,
                20,
                20,
            ],
        )
    )

    return pdk.Deck(
        layers=layers,
        initial_view_state=get_map_view(
            riders_df
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


init_state()

st.title("🚴 PKP Live")

st.caption(
    "Pułtuskie Kolarstwo Przygodowe "
    "— mapa i ślady uczestników"
)


with st.sidebar:
    st.header("Trening")

    st.session_state.nickname = (
        st.text_input(
            "Twój pseudonim",
            value=(
                st.session_state.nickname
            ),
            disabled=(
                st.session_state.tracking
            ),
        )
    )

    st.session_state.training_code = (
        st.text_input(
            "Kod treningu",
            value=(
                st.session_state
                .training_code
            ),
            disabled=(
                st.session_state.tracking
            ),
        )
        .strip()
        .upper()
    )

    if not st.session_state.tracking:
        if st.button(
            "▶ Rozpocznij tracking",
            use_container_width=True,
        ):
            st.session_state.tracking = True

            st.session_state.last_saved_track_point = (
                None
            )

            st.rerun()

    else:
        if st.button(
            "⏹ Zakończ tracking",
            use_container_width=True,
        ):
            try:
                mark_inactive()

            except Exception as exc:
                st.error(
                    "Nie udało się zmienić "
                    f"statusu: {exc}"
                )

            st.session_state.tracking = False

            st.rerun()

    if st.session_state.selected_rider_id:
        if st.button(
            "🌍 Pokaż wszystkich",
            use_container_width=True,
        ):
            st.session_state.selected_rider_id = (
                None
            )

            st.rerun()

    st.caption(
        f"GPS i mapa odświeżają się "
        f"co {REFRESH_SECONDS} sekund."
    )


training_code = (
    st.session_state.training_code
    or "PKP-DEMO"
)


if st.session_state.tracking:
    st_autorefresh(
        interval=(
            REFRESH_SECONDS * 1000
        ),
        key="gps_auto_refresh",
    )

    raw_position = (
        streamlit_geolocation()
    )

    position = normalize_position(
        raw_position
    )

    if position is None:
        st.info(
            "Oczekuję na GPS. "
            "Zezwól przeglądarce "
            "na lokalizację."
        )

    else:
        try:
            save_current_position(
                position
            )

        except Exception as exc:
            st.error(
                f"Błąd zapisu pozycji: {exc}"
            )


try:
    riders = load_riders(
        training_code
    )

    tracks = load_tracks(
        training_code
    )

except Exception as exc:
    st.error(
        "Nie udało się pobrać danych "
        f"z Supabase: {exc}"
    )

    st.stop()


if riders.empty:
    st.info(
        "Brak uczestników dla "
        "tego kodu treningu."
    )

    st.stop()


active_count = int(
    (
        riders["status"] == "aktywny"
    ).sum()
)


col1, col2, col3, col4 = (
    st.columns(4)
)

col1.metric(
    "Uczestnicy",
    len(riders),
)

col2.metric(
    "Aktywni",
    active_count,
)

col3.metric(
    "Punkty tras",
    len(tracks),
)

col4.metric(
    "Kod treningu",
    training_code,
)


selected_id = (
    st.session_state.selected_rider_id
)

map_key = (
    f"tracking_map_"
    f"{selected_id or 'all'}"
)


st.pydeck_chart(
    make_map(
        riders,
        tracks,
    ),
    use_container_width=True,
    key=map_key,
)


st.subheader("Uczestnicy")

st.caption(
    "Kliknij w wiersz uczestnika, "
    "aby wycentrować na nim mapę."
)


display_df = riders[
    [
        "nickname",
        "speed_label",
        "accuracy_label",
        "status",
        "updated_label",
    ]
].rename(
    columns={
        "nickname": "Uczestnik",
        "speed_label": "Prędkość",
        "accuracy_label": (
            "Dokładność GPS"
        ),
        "status": "Status",
        "updated_label": (
            "Ostatnia aktualizacja"
        ),
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


selected_rows = (
    table_event.selection.rows
)


if selected_rows:
    selected_row_number = (
        selected_rows[0]
    )

    newly_selected_id = riders.iloc[
        selected_row_number
    ]["rider_id"]

    if (
        newly_selected_id
        != st.session_state.selected_rider_id
    ):
        st.session_state.selected_rider_id = (
            newly_selected_id
        )

        st.rerun()


if st.session_state.selected_rider_id:
    selected = riders[
        riders["rider_id"]
        == st.session_state.selected_rider_id
    ]

    if not selected.empty:
        st.info(
            "Mapa wycentrowana na "
            f"uczestniku: "
            f"**{selected.iloc[0]['nickname']}**"
        )


st.caption(
    "Ostatnie odświeżenie: "
    f"{datetime.now().strftime('%H:%M:%S')}"
)