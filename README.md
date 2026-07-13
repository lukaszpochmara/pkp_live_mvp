# PKP Live GPS

Ta wersja zastępuje symulowane punkty prawdziwą lokalizacją telefonu.

## Podmiana poprzedniej wersji

Najprościej:

1. Skopiuj nowy `app.py` do poprzedniego katalogu projektu.
2. Zastąp `requirements.txt`.
3. W aktywnym środowisku uruchom:

```bash
pip install -r requirements.txt
```

4. Uruchom:

```bash
streamlit run app.py
```

## Test na komputerze

Pod adresem `http://localhost:8501` przeglądarka może pobrać lokalizację urządzenia,
ponieważ `localhost` jest traktowany jako bezpieczny kontekst.

## Test na telefonie

Samo wejście z telefonu na adres typu:

```text
http://192.168.1.20:8501
```

może nie pozwolić na GPS, ponieważ Geolocation API zasadniczo wymaga HTTPS.

Najpewniejszym testem będzie wdrożenie aplikacji na Streamlit Community Cloud,
które zapewnia adres HTTPS.

## Obecne działanie

- użytkownik wpisuje pseudonim i kod treningu,
- uruchamia udostępnianie,
- przeglądarka prosi o dostęp do GPS,
- mapa pokazuje prawdziwą pozycję,
- odczyty są przechowywane tymczasowo w sesji,
- punkty mogą tworzyć prosty ślad.

## Ograniczenia tej wersji

- dane nie są jeszcze współdzielone między telefonami,
- po restarcie aplikacji historia znika,
- kolejne odczyty pobiera się przez odświeżenie strony,
- działanie przy zablokowanym ekranie nie jest gwarantowane.

Następny etap: Supabase/PostgreSQL oraz automatyczne aktualizacje pozycji.
