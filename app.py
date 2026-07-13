from __future__ import annotations

from datetime import datetime

import pandas as pd
import pydeck as pdk
import streamlit as st
from streamlit_geolocation import streamlit_geolocation


st.set_page_config(
    page_title="PKP Live GPS",
    page_icon="🚴",
    layout="wide",
)

DEFAULT_LAT = 52.7025
DEFAULT_LON = 21.0828


def initialize_state() -> None:
    defaults = {
        "tracking": False,
        "nickname": "Łukasz",
        "training_code": "PKP-DEMO",
        "last_position": None,
        "position_history": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def normalize_position(raw_position: dict | None) -> dict | None:
    """Zamienia odpowiedź komponentu GPS na jednolity słownik."""
    if not raw_position or not isinstance(raw_position, dict):
        return None

    latitude = raw_position.get("latitude")
    longitude = raw_position.get("longitude")

    # Niektóre wersje komponentów zwracają dane w polu coords.
    coords = raw_position.get("coords")
    if isinstance(coords, dict):
        latitude = latitude if latitude is not None else coords.get("latitude")
        longitude = longitude if longitude is not None else coords.get("longitude")

    if latitude is None or longitude is None:
        return None

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    accuracy = raw_position.get("accuracy")
    speed = raw_position.get("speed")
    heading = raw_position.get("heading")

    if isinstance(coords, dict):
        accuracy = accuracy if accuracy is not None else coords.get("accuracy")
        speed = speed if speed is not None else coords.get("speed")
        heading = heading if heading is not None else coords.get("heading")

    speed_kmh = None
    if speed is not None:
        try:
            # Web Geolocation API podaje prędkość w m/s.
            speed_kmh = round(float(speed) * 3.6, 1)
        except (TypeError, ValueError):
            speed_kmh = None

    return {
        "nickname": st.session_state.nickname.strip() or "Kolarz",
        "training_code": st.session_state.training_code.strip() or "PKP-DEMO",
        "lat": latitude,
        "lon": longitude,
        "accuracy": round(float(accuracy), 1) if accuracy is not None else None,
        "speed_kmh": speed_kmh,
        "heading": heading,
        "updated_at": datetime.now(),
    }


def save_position(position: dict) -> None:
    previous = st.session_state.last_position

    # Ogranicza zapisywanie identycznych punktów podczas kolejnych rerunów.
    is_new = (
        previous is None
        or previous["lat"] != position["lat"]
        or previous["lon"] != position["lon"]
        or (datetime.now() - previous["updated_at"]).total_seconds() >= 10
    )

    st.session_state.last_position = position

    if is_new:
        st.session_state.position_history.append(position.copy())
        st.session_state.position_history = st.session_state.position_history[-500:]


def build_map(position: dict, history: list[dict]) -> pdk.Deck:
    point_df = pd.DataFrame(
        [
            {
                "nickname": position["nickname"],
                "lat": position["lat"],
                "lon": position["lon"],
                "speed": (
                    f'{position["speed_kmh"]} km/h'
                    if position["speed_kmh"] is not None
                    else "brak danych"
                ),
                "accuracy": (
                    f'{position["accuracy"]} m'
                    if position["accuracy"] is not None
                    else "brak danych"
                ),
                "updated": position["updated_at"].strftime("%H:%M:%S"),
            }
        ]
    )

    point_layer = pdk.Layer(
        "ScatterplotLayer",
        data=point_df,
        get_position="[lon, lat]",
        get_radius=45,
        get_fill_color="[30, 144, 255, 210]",
        get_line_color="[255, 255, 255]",
        line_width_min_pixels=2,
        stroked=True,
        pickable=True,
    )

    label_layer = pdk.Layer(
        "TextLayer",
        data=point_df,
        get_position="[lon, lat]",
        get_text="nickname",
        get_size=16,
        get_alignment_baseline="'bottom'",
        get_pixel_offset="[0, -14]",
        get_color="[20, 20, 20]",
    )

    layers = [point_layer, label_layer]

    if len(history) >= 2:
        path_df = pd.DataFrame(
            [
                {
                    "path": [[item["lon"], item["lat"]] for item in history],
                    "name": position["nickname"],
                }
            ]
        )

        path_layer = pdk.Layer(
            "PathLayer",
            data=path_df,
            get_path="path",
            get_width=5,
            width_min_pixels=3,
            get_color="[30, 144, 255]",
            pickable=False,
        )
        layers.insert(0, path_layer)

    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=position["lat"],
            longitude=position["lon"],
            zoom=14,
            pitch=0,
        ),
        tooltip={
            "html": (
                "<b>{nickname}</b><br/>"
                "Prędkość: {speed}<br/>"
                "Dokładność GPS: {accuracy}<br/>"
                "Aktualizacja: {updated}"
            )
        },
        map_style=None,
    )


initialize_state()

st.title("🚴 PKP Live")
st.caption("Pierwszy etap: prawdziwa lokalizacja GPS pojedynczego telefonu")

with st.sidebar:
    st.header("Ustawienia treningu")

    st.session_state.nickname = st.text_input(
        "Twój pseudonim",
        value=st.session_state.nickname,
        disabled=st.session_state.tracking,
    )

    st.session_state.training_code = st.text_input(
        "Kod treningu",
        value=st.session_state.training_code,
        disabled=st.session_state.tracking,
    )

    if not st.session_state.tracking:
        if st.button("▶ Rozpocznij udostępnianie", use_container_width=True):
            st.session_state.tracking = True
            st.rerun()
    else:
        if st.button("⏹ Zakończ udostępnianie", use_container_width=True):
            st.session_state.tracking = False
            st.rerun()

    if st.button("🗑 Wyczyść ślad", use_container_width=True):
        st.session_state.position_history = []
        st.session_state.last_position = None
        st.rerun()

if not st.session_state.tracking:
    st.info(
        "Wpisz pseudonim i kliknij „Rozpocznij udostępnianie”. "
        "Przeglądarka poprosi o zgodę na użycie lokalizacji."
    )

    if st.session_state.last_position:
        st.pydeck_chart(
            build_map(
                st.session_state.last_position,
                st.session_state.position_history,
            ),
            use_container_width=True,
        )

    st.stop()

st.warning(
    "Pozostaw tę kartę otwartą. W tej wersji przeglądarka może zatrzymać "
    "aktualizacje po wygaszeniu ekranu."
)

# Komponent uruchamia navigator.geolocation.getCurrentPosition w przeglądarce.
raw_position = streamlit_geolocation()

position = normalize_position(raw_position)

if position is None:
    st.info(
        "Oczekuję na lokalizację GPS. Zezwól przeglądarce na dostęp do lokalizacji. "
        "Jeśli wcześniej odmówiłeś, zmień uprawnienia lokalizacji przy ikonie kłódki "
        "obok adresu strony i odśwież stronę."
    )
    st.stop()

save_position(position)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Uczestnik", position["nickname"])
col2.metric(
    "Prędkość",
    f'{position["speed_kmh"]} km/h'
    if position["speed_kmh"] is not None
    else "brak danych",
)
col3.metric(
    "Dokładność GPS",
    f'{position["accuracy"]} m'
    if position["accuracy"] is not None
    else "brak danych",
)
col4.metric("Punkty śladu", len(st.session_state.position_history))

st.pydeck_chart(
    build_map(position, st.session_state.position_history),
    use_container_width=True,
)

st.subheader("Ostatni odczyt")
st.dataframe(
    pd.DataFrame(
        [
            {
                "Pseudonim": position["nickname"],
                "Kod treningu": position["training_code"],
                "Szerokość": position["lat"],
                "Długość": position["lon"],
                "Prędkość [km/h]": position["speed_kmh"],
                "Dokładność [m]": position["accuracy"],
                "Aktualizacja": position["updated_at"].strftime("%Y-%m-%d %H:%M:%S"),
            }
        ]
    ),
    hide_index=True,
    use_container_width=True,
)

st.caption(
    "Aby pobrać kolejny odczyt, podczas testu odśwież stronę. "
    "Następny etap doda automatyczne wysyłanie pozycji i wspólną bazę uczestników."
)
