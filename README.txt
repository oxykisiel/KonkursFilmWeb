# Opis projektu KonkursFilm

Projekt służy do automatycznego pobierania danych z serwisu Filmweb i zapisywania ich w pliku CSV. Skrypt filmweb_agent.py realizuje całą logikę pobierania i zapisywania danych.

## Jak uruchomić projekt

1. Upewnij się, że masz zainstalowanego Pythona (wersja 3.8 lub wyższa).
2. Zainstaluj wymagane biblioteki (patrz niżej).
3. Uruchom skrypt filmweb_agent.py:

    ```powershell
    python filmweb_agent.py
    ```

Dane zostaną zapisane w pliku filmweb_agent_log.csv.

## Instrukcja instalacji na Windows

1. Pobierz i zainstaluj Python ze strony https://www.python.org/downloads/
2. Dodaj Python do zmiennej PATH podczas instalacji.
3. Otwórz PowerShell lub CMD w folderze projektu.
4. Zainstaluj wymagane biblioteki:

    ```powershell
    pip install requests beautifulsoup4
    ```

5. (Opcjonalnie) Utwórz skrót na pulpit:
    - Kliknij prawym przyciskiem myszy na pulpicie, wybierz "Nowy" > "Skrót".
    - W polu lokalizacji wpisz:
      ```
      powershell -NoExit -Command "cd 'd:\Programy\KonkursFilm'; python filmweb_agent.py"
      ```
    - Nadaj nazwę skrótu, np. "KonkursFilm Start".

## Instrukcja obsługi

- Skrypt uruchamia się automatycznie i pobiera dane z Filmweb.
- Wynik działania zapisuje się w pliku filmweb_agent_log.csv.
- Jeśli pojawią się błędy, sprawdź czy masz dostęp do internetu i czy zainstalowane są wymagane biblioteki.

## Kontakt
W razie problemów skontaktuj się z autorem projektu.
