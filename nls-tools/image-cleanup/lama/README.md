# LaMa Cleanup — lokalne retuszowanie pędzlem

Narzędzie usuwa ze zdjęcia małe, ręcznie zaznaczone elementy: pojedyncze
włoski, kropki, zabrudzenia, fragmenty brody i podobne niedoskonałości. Działa
lokalnie w przeglądarce, korzysta z modelu **LaMa** i wykonuje obliczenia na
karcie NVIDIA przez CUDA. Zdjęcia nie są wysyłane do zewnętrznej usługi.

Interfejs dostarcza [IOPaint](https://github.com/Sanster/IOPaint), czyli lokalna
aplikacja z pędzlem wykorzystująca model z projektu
[advimman/LaMa](https://github.com/advimman/lama). Jest to odpowiednik sposobu
pracy znanego z [Cleanup.pictures](https://cleanup.pictures/) lub
[Clipdrop Cleanup](https://clipdrop.co/cleanup): użytkownik maluje maskę, a
model odtwarza tło lub powierzchnię obiektu pod zaznaczeniem.

## Wymagania

- Windows 11 i Docker Desktop uruchomiony w trybie WSL2,
- karta NVIDIA oraz aktualny sterownik,
- około 12 GB wolnego miejsca na pierwszy build obrazu,
- wolny port `8090`.

Konfiguracja została przygotowana dla RTX 50xx i używa PyTorch 2.10 z CUDA
13.0. Kontener nie ma trybu automatycznego przełączania na CPU — brak dostępu
do CUDA zatrzyma start i pokaże czytelny błąd.

## Uruchomienie

Z głównego katalogu repozytorium:

```powershell
.\nls-tools\image-cleanup\lama\docker\start-docker.ps1
```

Po uruchomieniu otworzy się:

```text
http://localhost:8090
```

Pierwszy start pobiera model LaMa. Wagi są zapisywane poza repozytorium i
pozostają na dysku po restarcie kontenera:

```text
D:\NlsTools\lama\models
```

Pobierany jest plik
[`big-lama.pt`](https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt)
o rozmiarze około 196 MB. Przed uruchomieniem jest automatycznie sprawdzany
sumą SHA-256, a niedokończone pobieranie może zostać wznowione.

## Jak używać

1. Przeciągnij zdjęcie do panelu albo wybierz je z katalogu
   `D:\NlsTools\lama\input`.
2. Przybliż miejsce wymagające korekty.
3. Dolnym suwakiem zmniejsz pędzel i zamaluj cały włosek, kropkę lub fragment
   brody wraz z minimalnym marginesem.
4. Pozostaw strategię HD ustawioną na `Crop`. Przy dużych zdjęciach aplikacja
   policzy tylko wycinek wokół maski z kontekstem, co dobrze pasuje do
   mikroobszarów.
5. Puść przycisk myszy. Retusz uruchomi się automatycznie. Jeśli pierwsza próba
   nie jest idealna, cofnij wynik i zaznacz defekt odrobinę szerzej.
6. Pobierz gotowy obraz z panelu. Katalog wyników kontenera jest zamontowany
   jako `D:\NlsTools\lama\output`.

Dla pojedynczych włosków zwykle wystarcza pędzel `2–12 px`. Przy krawędzi
obiektu warto zamalować cały niepożądany fragment, a nie tylko jego środek.

## Obsługa kontenera

Podgląd logów:

```powershell
docker compose -f .\nls-tools\image-cleanup\lama\docker\compose.yaml logs -f
```

Zatrzymanie:

```powershell
docker compose -f .\nls-tools\image-cleanup\lama\docker\compose.yaml down
```

Usunięcie kontenera nie usuwa modelu ani zdjęć z `D:\NlsTools\lama`.

Dokumentacja wbudowanego, synchronicznego API jest dostępna podczas działania
kontenera pod `http://localhost:8090/docs`. Endpoint `POST /api/v1/inpaint`
przyjmuje obraz i czarno-białą maskę jako Base64, a zwraca gotowy PNG.

## Uwagi

- LaMa służy do uzupełniania zamalowanego obszaru, a nie do automatycznego
  usuwania tła. RMBG-2.0 pozostaje osobnym narzędziem do wycinania tła.
- IOPaint jest przypięty do wersji `1.6.0`, a środowisko CUDA do konkretnej
  wersji obrazu, aby kolejne uruchomienia były powtarzalne.
- Kod LaMa i IOPaint jest udostępniany na licencji Apache-2.0. Wagi i sposób
  użycia należy dodatkowo zweryfikować przed wdrożeniem komercyjnym.
