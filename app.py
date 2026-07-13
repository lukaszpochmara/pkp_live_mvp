from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pandas as pd
import pydeck as pdk
import streamlit as st
from streamlit_geolocation import streamlit_geolocation
from supabase import create_client


st.set_page_config(page_title="PKP Live", page_icon="🚴", layout="wide")

REFRESH_SECONDS = 5


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
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def normalize_position(raw):
    if not isinstance(raw, dict):
        return None

    coords = raw.get("coords") if isinstance(raw.get("coords"), dict) else {}

    lat = raw.get("latitude", coords.get("latitude"))
    lon = raw.get("longitude", coords.get("longitude"))
    accuracy = raw.get("accuracy", coords.get("accuracy"))
    speed = raw.get("speed", coords.get("speed"))

    if lat is None or lon is None:
        return None

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    try:
        accuracy = round(float(accuracy), 1) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy = None

    try:
        speed_kmh = round(float(speed) * 3.6, 1) if speed is not None else None
    except (TypeError, ValueError):
        speed_kmh = None

    return {
        "latitude": lat,
        "longitude": lon,
        "accuracy_m": accuracy,
        "speed_kmh": speed_kmh,
    }


def save_position(position):
    payload = {
        "rider_id": st.session_state.rider_id,
        "nickname": st.session_state.nickname.strip() or "Kolarz",
        "training_code": (
            st.session_state.training_code.strip().upper() or "PKP-DEMO"
        ),
        "latitude": position["latitude"],
        "longitude": position["longitude"],
        "speed_kmh": position["speed_kmh"],
        "accuracy_m": position["accuracy_m"],
        "is_active": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    (
        get_supabase()
        .table("riders")
        .upsert(payload, on_conflict="rider_id,training_code")
        .execute()
    )

    st.session_state.last_position = payload


def mark_inactive():
    if not st.session_state.last_position:
        return

    (
        get_supabase()
        .table("riders")
        .update(
            {
                "is_active": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("rider_id", st.session_state.rider_id)
        .eq(
            "training_code",
            st.session_state.training_code.strip().upper(),
        )
        .execute()
    )


def load_riders(training_code):
    response = (
        get_supabase()
        .table("riders")
        .select("*")
        .eq("training_code", training_code)
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
        pd.Timestamp.now(tz="UTC") - df["updated_at"]
    ).dt.total_seconds().round()

    df["status"] = "aktywny"
    df.loc[df["seconds_ago"] > 60, "status"] = "brak sygnału"
    df.loc[df["is_active"] == False, "status"] = "zakończył"

    df["speed_label"] = df["speed_kmh"].apply(
        lambda value: (
            f"{value:.1f} km/h"
            if pd.notna(value)
            else "brak danych"
        )
    )

    df["accuracy_label"] = df["accuracy_m"].apply(
        lambda value: (
            f"{value:.0f} m"
            if pd.notna(value)
            else "brak danych"
        )
    )

    df["updated_label"] = df["seconds_ago"].apply(
        lambda value: (
            f"{int(value)} s temu"
            if pd.notna(value)
            else "brak danych"
        )
    )

    return df


def make_map(df):
    point_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[longitude, latitude]",
        get_radius=55,
        get_fill_color=(
            "[30, 144, 255, 220] "
            "if status == 'aktywny' else [150, 150, 150, 180]"
        ),
        get_line_color="[255, 255, 255]",
        line_width_min_pixels=2,
        stroked=True,
        pickable=True,
    )

    text_layer = pdk.Layer(
        "TextLayer",
        data=df,
        get_position="[longitude, latitude]",
        get_text="nickname",
        get_size=16,
        get_alignment_baseline="'bottom'",
        get_pixel_offset="[0, -14]",
        get_color="[20, 20, 20]",
    )

    return pdk.Deck(
        layers=[point_layer, text_layer],
        initial_view_state=pdk.ViewState(
            latitude=float(df["latitude"].mean()),
            longitude=float(df["longitude"].mean()),
            zoom=11,
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
st.caption("Pułtuskie Kolarstwo Przygodowe — wspólna mapa treningu")

with st.sidebar:
    st.header("Trening")

    st.session_state.nickname = st.text_input(
        "Twój pseudonim",
        value=st.session_state.nickname,
        disabled=st.session_state.tracking,
    )

    st.session_state.training_code = st.text_input(
        "Kod treningu",
        value=st.session_state.training_code,
        disabled=st.session_state.tracking,
    ).strip().upper()

    if not st.session_state.tracking:
        if st.button(
            "▶ Rozpocznij udostępnianie",
            use_container_width=True,
        ):
            st.session_state.tracking = True
            st.rerun()
    else:
        if st.button(
            "⏹ Zakończ udostępnianie",
            use_container_width=True,
        ):
            try:
                mark_inactive()
            except Exception as exc:
                st.error(f"Nie udało się zmienić statusu: {exc}")

            st.session_state.tracking = False
            st.rerun()

    st.caption(f"Mapa odświeża się co {REFRESH_SECONDS} sekund.")

training_code = st.session_state.training_code or "PKP-DEMO"

if st.session_state.tracking:
    raw_position = streamlit_geolocation()
    position = normalize_position(raw_position)

    if position is None:
        st.info(
            "Oczekuję na GPS. Zezwól przeglądarce "
            "na dostęp do lokalizacji."
        )
    else:
        try:
            save_position(position)
            st.success("Pozycja została zapisana w Supabase.")
        except Exception as exc:
            st.error(f"Błąd zapisu do Supabase: {exc}")


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def live_map():
    try:
        riders = load_riders(training_code)
    except Exception as exc:
        st.error(f"Nie udało się pobrać danych z Supabase: {exc}")
        return

    if riders.empty:
        st.info("Brak uczestników dla tego kodu treningu.")
        return

    active_count = int((riders["status"] == "aktywny").sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Uczestnicy", len(riders))
    c2.metric("Aktywni", active_count)
    c3.metric("Kod treningu", training_code)

    st.pydeck_chart(
        make_map(riders),
        use_container_width=True,
        key="live_riders_map",
    )

    st.subheader("Uczestnicy")

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
            "accuracy_label": "Dokładność GPS",
            "status": "Status",
            "updated_label": "Ostatnia aktualizacja",
        }
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        key="live_riders_table",
    )

    st.caption(
        f"Ostatnie automatyczne odświeżenie: "
        f"{datetime.now().strftime('%H:%M:%S')}"
    )


live_map()
