# PKP Live — automatyczne odświeżanie

Ta wersja automatycznie pobiera pozycje kolarzy z Supabase co 5 sekund.

## Aktualizacja

Podmień `app.py`, a następnie:

```bash
git add app.py
git commit -m "Automatyczne odświeżanie mapy"
git push origin master
```

Streamlit Cloud po chwili wdroży nową wersję.

## Ważne

Ta zmiana automatycznie odświeża dane pobierane z Supabase.
Nie uruchamia jeszcze ciągłego śledzenia GPS w tle telefonu.
