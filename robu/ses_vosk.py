"""İzole ses ortamında çalışan Türkçe Vosk işçisi; ses ağ üzerinden gönderilmez."""
import json
import sys
import wave


def cevir(model_yolu, wav):
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    with wave.open(wav, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise ValueError("16 kHz, 16 bit, mono WAV gerekli.")
        recognizer = KaldiRecognizer(Model(model_yolu), 16000)
        metin = []
        while True:
            data = w.readframes(4000)
            if not data:
                break
            if recognizer.AcceptWaveform(data):
                metin.append(json.loads(recognizer.Result()).get("text", ""))
        metin.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(p for p in metin if p).strip()


if __name__ == "__main__":
    print(cevir(sys.argv[1], sys.argv[2]))
