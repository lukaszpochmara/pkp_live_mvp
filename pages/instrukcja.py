from __future__ import annotations

from urllib.parse import quote_plus

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


st.set_page_config(
    page_title="Instrukcja instalacji",
    page_icon=":iphone:",
)


def get_secret_value(key, default=None):
    try:
        return st.secrets[key]
    except (
        KeyError,
        StreamlitSecretNotFoundError,
        FileNotFoundError,
    ):
        return default


def get_qr_code_url(url):
    return (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size=220x220&data={quote_plus(url)}"
    )


mobile_app_url = get_secret_value("MOBILE_APP_URL")
tracking_code = get_secret_value("TRACKING_CODE", "PKP-DEMO")

st.title("Instrukcja instalacji aplikacji")
st.caption(
    "Aplikacja mobilna służy do udostępniania Twojej lokalizacji "
    "na mapie PKP Live podczas aktywnego trackingu."
)

col1, col2 = st.columns([3, 1], vertical_alignment="center")

with col1:
    st.subheader("Pobierz aplikację")

    if mobile_app_url:
        st.link_button(
            "Pobierz aplikację APK",
            mobile_app_url,
            use_container_width=True,
        )
    else:
        st.info(
            "Link do aplikacji nie jest skonfigurowany. "
            "Dodaj `MOBILE_APP_URL` w sekretach Streamlit."
        )

with col2:
    if mobile_app_url:
        st.image(
            get_qr_code_url(mobile_app_url),
            caption="Zeskanuj telefonem",
            width=180,
        )

st.divider()

st.subheader("Instalacja krok po kroku")

st.markdown(
    f"""
1. Otwórz tę stronę na telefonie z Androidem.
2. Kliknij **Pobierz aplikację APK** albo zeskanuj kod QR.
3. Po pobraniu otwórz plik `.apk`.
4. Jeżeli telefon pokaże ostrzeżenie, wybierz opcję instalacji mimo to.
5. Jeżeli pojawi się prośba o zgodę na instalowanie z przeglądarki, włącz ją.
6. Zainstaluj aplikację i uruchom ją.
7. Wpisz swój pseudonim oraz kod śledzenia: **{tracking_code}**.
8. Kliknij **Rozpocznij tracking**.
9. Zezwól aplikacji na dostęp do lokalizacji.
10. Po kilku sekundach Twoja pozycja powinna pojawić się na mapie live.
    """.strip()
)

st.subheader("Ważne ustawienia telefonu")

st.markdown(
    """
- Lokalizacja GPS musi być włączona.
- Aplikacja musi mieć zgodę na dostęp do lokalizacji.
- W trakcie jazdy nie wyłączaj aplikacji.
- Jeżeli telefon ogranicza działanie aplikacji w tle, wyłącz oszczędzanie baterii dla tej aplikacji.
    """.strip()
)

with st.expander("Co zrobić, jeśli aplikacja się nie instaluje?"):
    st.markdown(
        """
- Sprawdź, czy pobrany plik kończy się na `.apk`.
- Wejdź w ustawienia Androida i pozwól przeglądarce instalować nieznane aplikacje.
- Pobierz plik ponownie, jeżeli instalator zgłasza uszkodzony plik.
- Upewnij się, że masz wystarczająco miejsca w pamięci telefonu.
        """.strip()
    )

with st.expander("Co zrobić, jeśli nie widać mnie na mapie?"):
    st.markdown(
        """
- Sprawdź, czy w aplikacji kliknięto **Rozpocznij tracking**.
- Sprawdź, czy wpisany kod śledzenia jest poprawny.
- Upewnij się, że telefon ma sygnał GPS i dostęp do internetu.
- Poczekaj kilka sekund, mapa odświeża dane cyklicznie.
        """.strip()
    )
