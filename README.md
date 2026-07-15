# PKP Live — mapa śledzenia

Aplikacja Streamlit służy wyłącznie do podglądu uczestników na mapie.
Nie zawiera funkcji dołączania do treningu ani wysyłania własnej lokalizacji.

## Funkcje

- automatyczne odświeżanie danych z Supabase co 5 sekund,
- mapa aktywnych uczestników,
- wybór uczestnika przez kliknięcie markera na mapie albo wiersza w tabeli,
- wyświetlanie śladu tylko dla wybranego uczestnika.

## Konfiguracja

Lokalnie możesz utworzyć plik `.streamlit/secrets.toml`
na podstawie `.streamlit/secrets.example.toml`.
Alternatywnie ustaw te same wartości jako zmienne środowiskowe.

Domyślny kod śledzenia to `PKP-DEMO`.
Można go zmienić przez sekret Streamlit:

```toml
TRACKING_CODE = "PKP-DEMO"
```

Wymagane są też sekrety Supabase:

```toml
SUPABASE_URL = "..."
SUPABASE_KEY = "..."
```
