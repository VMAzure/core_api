import re
import json

# Legge il file di testo e ignora la parte iniziale
def parse_offerte(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        data = file.read()

    # Ignora tutto prima della frase specificata
    start_point = "Noleggio lungo termine veicoli nuovi\n(x) Risultati"
    data = data.split(start_point, 1)[-1]

    # Regex per estrarre i dati
    offerte_pattern = re.compile(
        r'([A-Z][A-Z0-9ÈÉ\-\s]+)\n'                  # Marca
        r'(.+?)\n\n'                                 # Modello
        r'(\d+[.,]?\d*)€mese IVA esclusa\n'          # Prezzo mensile
        r'(?:\s*OFFERTA LIMITATA\n)?'                 # Eventuale dicitura offerta limitata
        r'(\d+) Mesi \| (\d+\.?\d*) Km/anno \| Anticipo€ ([\d.,]+) IVA esclusa',  # Condizioni
        re.MULTILINE
    )

    offerte = []
    for match in offerte_pattern.finditer(data):
        marca, modello, prezzo, mesi, km_annui, anticipo = match.groups()

        offerta = {
            'marca': marca.strip(),
            'modello': modello.strip(),
            'prezzo_mensile': float(prezzo.replace(',', '.')),
            'durata_mesi': int(mesi),
            'km_annui': int(float(km_annui.replace('.', '').replace(',', '.'))),
            'anticipo': float(anticipo.replace('.', '').replace(',', '.'))
        }

        offerte.append(offerta)

    return offerte

# Test
file_path = 'offerte.txt'
offerte = parse_offerte(file_path)

# Salva i dati estratti in un file JSON
with open('offerte.json', 'w', encoding='utf-8') as json_file:
    json.dump(offerte, json_file, indent=4, ensure_ascii=False)

print("File JSON creato con successo: offerte.json")
