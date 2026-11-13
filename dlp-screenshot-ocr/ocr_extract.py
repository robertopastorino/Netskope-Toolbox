#!/usr/bin/env python3
"""
ocr_extract.py - Estrazione OCR locale (Tesseract) da screenshot, con cattura
opzionale di frame da video e generazione di un dizionario di termini per DLP.

Tutto locale: nessuna chiamata di rete.

Requisiti
  - Python 3.9+
  - pip install pytesseract pillow
  - Tesseract OCR installato, con i language pack richiesti (es. ita, eng)
  - ffmpeg (solo se si usa --video)

Esempi
  # Dizionario comune + testo per immagine con struttura mantenuta
  python ocr_extract.py -i ./screenshot -o ./ocr_out --mode entrambi

  # Solo cattura frame da video (un frame ogni 2 s, deduplica sui frame quasi identici)
  python ocr_extract.py --video ./registrazioni --frames-dir ./frames --frames-only

  # Con filtro nomi/cognomi, vocabolario, etichette da tenere e lista di esclusione
  python ocr_extract.py -i ./screenshot -o ./ocr_out --names ./liste/cognomi.txt --names ./liste/nomi.txt --names-vocab ./liste/parole.txt --keep ./keep_etichette_gestionali.txt --ignore ./ignora.txt

  # Seconda passata sulla cache OCR (nessun OCR, Tesseract non necessario)
  python ocr_extract.py --from-cache ./ocr_out -o ./ocr_out_v2 --mode dizionario --keep ./keep_etichette_gestionali.txt --min-images 3

  # Frame da video + OCR sui frame (senza -i viene usata --frames-dir)
  python ocr_extract.py --video ./registrazioni --frames-dir ./frames -o ./ocr_out
"""

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Le dipendenze servono solo per OCR e video: la seconda passata (--from-cache)
# gira con la sola libreria standard.
try:
    from PIL import Image, ImageChops, ImageOps, ImageStat
    import pytesseract
    _IMPORT_ERROR = None
except ImportError as exc:
    _IMPORT_ERROR = exc


def require_deps():
    if _IMPORT_ERROR:
        sys.exit(f"Dipendenza mancante: {_IMPORT_ERROR}. Installa con: pip install pytesseract pillow")

IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v"}
MAX_SIDE = 8000  # limite al lato lungo dopo l'upscale
CACHE_NAME = "ocr_cache.jsonl.gz"
CACHE_FORMAT = 1

STOPWORDS = {
    # italiano
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in",
    "con", "su", "per", "tra", "fra", "e", "ed", "o", "od", "ma", "se", "che", "non",
    "del", "dello", "della", "dei", "degli", "delle", "al", "allo", "alla", "ai",
    "agli", "alle", "dal", "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello",
    "nella", "nei", "negli", "nelle", "sul", "sullo", "sulla", "sui", "sugli",
    "sulle", "è", "sono", "come", "anche", "più", "si", "no", "ne",
    # inglese
    "the", "an", "of", "to", "on", "for", "and", "or", "with", "by", "from", "at",
    "is", "are", "be", "this", "that", "it", "as", "not",
}
TRIM_CHARS = " \t.,;:!?()[]{}<>\"'«»|*_=+-–—/\\…"


# ---------------------------------------------------------------------------
# Filtri dati personali
# ---------------------------------------------------------------------------

# Codice fiscale tollerante a omocodia (cifre sostituite da LMNPQRSTUV) e ai
# tipici scambi OCR (O/0, I/1, S/5, B/8). Per evitare falsi positivi su parole
# lunghe composte solo da lettere, si richiedono almeno 3 cifre reali nelle 7
# posizioni numeriche.
_D = "[0-9LMNPQRSTUVOI]"
_L = "[A-Z0158]"
CF_RE = re.compile(rf"(?<![A-Z0-9]){_L}{{6}}{_D}{{2}}[ABCDEHLMPRST]{_D}{{2}}{_L}{_D}{{3}}{_L}(?![A-Z0-9])",
                   re.IGNORECASE)
CF_NUM_POS = (6, 7, 9, 10, 12, 13, 14)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
NAME_PARTICLES = {"de", "di", "del", "della", "dei", "degli", "da", "dal", "dalla", "d",
                  "van", "von", "der", "den", "la", "lo", "le", "el", "al", "bin", "ben", "mc", "mac"}


def has_cf(text):
    return any(sum(m.group(0)[p].isdigit() for p in CF_NUM_POS) >= 3 for m in CF_RE.finditer(text))


def sub_cf(text):
    return CF_RE.sub(lambda m: "[CF]" if sum(m.group(0)[p].isdigit() for p in CF_NUM_POS) >= 3
                     else m.group(0), text)


def load_term_files(paths):
    """Legge elenchi di termini. Una voce per riga; righe vuote, '#...' e '--...'
    ignorate; per righe tipo 'nome,m' viene preso il primo campo; 're:<regex>'
    definisce un'espressione regolare (case-insensitive)."""
    singles, phrases, regexes = set(), set(), []
    for p in paths or []:
        for line in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip().lstrip("\ufeff")
            if not s or s.startswith("#") or s.startswith("--"):
                continue
            if s.startswith("re:"):
                regexes.append(re.compile(s[3:].strip(), re.IGNORECASE))
                continue
            s = re.split(r"[,;\t]", s, maxsplit=1)[0].strip().lower()
            toks = tuple(t.strip(TRIM_CHARS) for t in s.split() if t.strip(TRIM_CHARS))
            if not toks or not any(c.isalpha() for c in "".join(toks)):
                continue
            if len(toks) == 1:
                singles.add(toks[0])
            else:
                phrases.add(toks)
    return singles, phrases, regexes


def contains_phrase(tokens, phrase):
    n = len(phrase)
    return any(tuple(tokens[i:i + n]) == phrase for i in range(len(tokens) - n + 1))


class PiiFilter:
    """Esclude dal dizionario (e, salvo --no-redact, oscura nel testo) codici
    fiscali, email, nomi/cognomi e termini della lista di esclusione."""

    def __init__(self, names=None, vocab=None, keep=None, ignore=None):
        n_single, self.name_phrases, _ = load_term_files(names)
        vocab_single, _, _ = load_term_files(vocab)
        self.keep_single, self.keep_phrases, _ = load_term_files(keep)
        self.ign_single, self.ign_phrases, self.ign_re = load_term_files(ignore)
        self.names = n_single - self.keep_single - NAME_PARTICLES
        # "puri": nomi che non sono anche parole comuni -> bastano da soli a scartare
        self.pure = self.names - vocab_single if vocab_single else set(self.names)
        self.ambiguous = self.names - self.pure
        self.use_vocab = bool(vocab_single)

    # --- dizionario --------------------------------------------------------
    def check(self, low, in_name=False):
        """low: token in minuscolo di un termine; in_name: True se almeno un token
        cade in un nome individuato sulla riga (vedi name_mask).
        Restituisce il motivo di scarto o None."""
        for t in low:
            if has_cf(t):
                return "codice_fiscale"
            if EMAIL_RE.search(t):
                return "email"
        joined = " ".join(low)
        if (any(t in self.ign_single for t in low)
                or any(rx.fullmatch(t) for rx in self.ign_re for t in low)
                or any(rx.fullmatch(joined) for rx in self.ign_re)
                or any(contains_phrase(low, ph) for ph in self.ign_phrases)):
            return "lista_esclusione"
        if tuple(low) in self.keep_phrases:
            return None
        if in_name:
            return "nome"
        content = [t for t in low if t not in NAME_PARTICLES]
        if any(t in self.pure for t in content):
            return "nome"
        if len(content) >= 2 and all(t in self.names for t in content):
            return "nome"
        if any(contains_phrase(low, ph) for ph in self.name_phrases):
            return "nome"
        return None

    def name_mask(self, low):
        """Per una sequenza di token (minuscoli) indica quali fanno parte di un nome:
        nomi "puri", frasi degli elenchi nomi, sequenze di almeno due nomi anche
        ambigui (con particelle tipo 'de', 'di' in mezzo). Le etichette in --keep
        sono già escluse dall'elenco nomi."""
        n = len(low)
        mask = [t in self.pure for t in low]
        for ph in self.name_phrases:
            k = len(ph)
            for i in range(n - k + 1):
                if tuple(low[i:i + k]) == ph:
                    mask[i:i + k] = [True] * k
        i = 0
        while i < n:
            if low[i] in self.names:
                j, count = i, 0
                while j < n and (low[j] in self.names or (low[j] in NAME_PARTICLES and j + 1 < n
                                                          and low[j + 1] in self.names)):
                    count += low[j] in self.names
                    j += 1
                if count >= 2:
                    mask[i:j] = [True] * (j - i)
                i = max(j, i + 1)
            else:
                i += 1
        return mask

    # --- testo per immagine -----------------------------------------------
    def redact(self, raw_tokens):
        """Restituisce i token della riga con i dati personali sostituiti."""
        out = list(raw_tokens)
        low = [t.strip(TRIM_CHARS).lower() for t in raw_tokens]
        n = len(low)
        for i, t in enumerate(raw_tokens):
            if has_cf(t):
                out[i] = sub_cf(t)
            if EMAIL_RE.search(out[i]):
                out[i] = EMAIL_RE.sub("[EMAIL]", out[i])
            if low[i] in self.ign_single or any(rx.fullmatch(low[i]) for rx in self.ign_re):
                out[i] = "[IGNORATO]"
        for ph in self.ign_phrases:
            k = len(ph)
            for i in range(n - k + 1):
                if tuple(low[i:i + k]) == ph:
                    out[i:i + k] = ["[IGNORATO]"] * k
        for i, is_name in enumerate(self.name_mask(low)):
            if is_name and out[i] != "[IGNORATO]":
                out[i] = "[NOME]"
        return out


# ---------------------------------------------------------------------------
# Video: estrazione frame e deduplica
# ---------------------------------------------------------------------------

THUMB_W = 640  # larghezza delle miniature usate per il confronto tra frame


def thumb(path: Path):
    with Image.open(path) as im:
        g = im.convert("L")
        return g.resize((THUMB_W, max(1, int(g.height * THUMB_W / g.width))), Image.BILINEAR)


def changed_ratio(a, b, tol: int) -> float:
    """Quota di pixel che differiscono di più di 'tol' livelli di grigio.
    Per le GUI è più adatto di un hash percettivo: layout identico con testo
    diverso produce hash quasi uguali, mentre qui la differenza resta misurabile."""
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > tol else 0)
    return diff.histogram()[255] / (diff.width * diff.height)


def extract_frames(video: Path, out_dir: Path, fps: float, ffmpeg: str,
                   threshold_pct: float, tol: int, global_dedup: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):  # evita residui di run precedenti
        old.unlink()
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
           "-vf", f"fps={fps}", str(out_dir / "frame_%05d.png")]
    subprocess.run(cmd, check=True)

    frames = sorted(out_dir.glob("frame_*.png"))
    if threshold_pct <= 0:
        return len(frames), 0
    kept, removed = [], 0
    for f in frames:
        t = thumb(f)
        refs = kept if global_dedup else kept[-1:]
        if any(t.size == k.size and changed_ratio(t, k, tol) * 100 < threshold_pct for k in refs):
            f.unlink()
            removed += 1
        else:
            kept.append(t)
    return len(frames), removed


def collect_videos(paths):
    videos = []
    for p in map(Path, paths):
        if p.is_dir():
            videos += sorted(v for v in p.rglob("*") if v.suffix.lower() in VIDEO_EXT)
        elif p.is_file():
            videos.append(p)
        else:
            print(f"[WARN] video non trovato: {p}", file=sys.stderr)
    return videos


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def init_worker(tesseract_cmd):
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def preprocess(path: Path, upscale: float, invert_mode: str):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    g = im.convert("L")

    inverted = False
    if invert_mode == "always" or (invert_mode == "auto" and ImageStat.Stat(g).mean[0] < 110):
        g = ImageOps.invert(g)  # temi scuri: Tesseract preferisce testo scuro su chiaro
        inverted = True

    if upscale and upscale != 1:
        w, h = int(g.width * upscale), int(g.height * upscale)
        if max(w, h) > MAX_SIDE:
            k = MAX_SIDE / max(w, h)
            w, h = int(w * k), int(h * k)
        g = g.resize((w, h), Image.LANCZOS)
    return g, inverted


def ocr_image(job):
    path, rel, lang, psm, upscale, invert_mode = job
    try:
        img, inverted = preprocess(Path(path), upscale, invert_mode)
        d = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm}",
                                      output_type=pytesseract.Output.DICT)
        words = []
        for i, raw in enumerate(d["text"]):
            t = (raw or "").strip()
            try:
                conf = float(d["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if not t or conf < 0:
                continue
            words.append({
                "text": t, "conf": conf,
                "line": (d["block_num"][i], d["par_num"][i], d["line_num"][i]),
                "left": d["left"][i], "top": d["top"][i],
                "width": d["width"][i], "height": d["height"][i],
            })
        return {"rel": rel, "words": words, "inverted": inverted, "error": None}
    except Exception as exc:  # noqa: BLE001 - errore riportato nel report
        return {"rel": rel, "words": [], "inverted": False, "error": str(exc)}


def group_lines(words):
    lines, order = {}, []
    for w in words:
        if w["line"] not in lines:
            lines[w["line"]] = []
            order.append(w["line"])
        lines[w["line"]].append(w)
    return [lines[k] for k in order]


# ---------------------------------------------------------------------------
# Estrazione termini
# ---------------------------------------------------------------------------

def token_ok(tok, max_digit_ratio):
    if not any(c.isalpha() for c in tok):
        return False
    return sum(c.isdigit() for c in tok) / len(tok) <= max_digit_ratio


def extract_terms(lines, a):
    """Restituisce (chiave_lower, forma_originale, conf_media, motivo_scarto) per
    unigrammi e n-grammi; motivo_scarto è None per i termini validi."""
    for line in lines:
        for toks in split_segments(line):
            yield from _terms_in_segment(toks, a)


def split_segments(line):
    """Spezza la riga sui separatori (|, -, ecc.) e dopo i token che terminano con ':'
    (fine etichetta), così gli n-grammi non scavalcano campi diversi."""
    seg, out = [], []
    for w in line:
        t = w["text"].strip(TRIM_CHARS)
        if not t:
            if seg:
                out.append(seg)
            seg = []
            continue
        seg.append((t, w["conf"]))
        if w["text"].rstrip().endswith(":"):
            out.append(seg)
            seg = []
    if seg:
        out.append(seg)
    return out


def _terms_in_segment(toks, a):
    mask = a.pii.name_mask([t.lower() for t, _ in toks])
    for size in range(1, a.ngram_max + 1):
        for i in range(len(toks) - size + 1):
            chunk = toks[i:i + size]
            if any(c < a.min_conf for _, c in chunk):
                continue
            ws = [t for t, _ in chunk]
            low = [w.lower() for w in ws]
            conf = sum(c for _, c in chunk) / size
            reason = a.pii.check(low, any(mask[i:i + size]))
            if reason:
                yield " ".join(low), " ".join(ws), conf, reason
                continue
            if not all(token_ok(w, a.max_digit_ratio) for w in ws):
                continue
            if size == 1:
                if len(ws[0]) < a.min_len or low[0] in a.stopwords:
                    continue
            else:
                if low[0] in a.stopwords or low[-1] in a.stopwords:
                    continue
                if len(ws[0]) < 2 or len(ws[-1]) < 2:
                    continue
            yield " ".join(low), " ".join(ws), conf, None


# ---------------------------------------------------------------------------
# Cache OCR (per rielaborare dizionari e filtri senza rifare l'OCR)
# ---------------------------------------------------------------------------

def save_cache(results, path: Path, meta: dict):
    """Una riga JSON di metadati seguita da una riga per immagine, compresso gzip.
    Contiene il testo OCR NON oscurato: è sensibile quanto gli screenshot."""
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "meta", "format": CACHE_FORMAT, **meta}, ensure_ascii=False) + "\n")
        for r in results:
            fh.write(json.dumps({"type": "image", **r}, ensure_ascii=False) + "\n")


def load_cache(src: str):
    path = Path(src)
    if path.is_dir():
        path = path / CACHE_NAME
    if not path.is_file():
        sys.exit(f"Cache non trovata: {path}")
    meta, results = None, []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.pop("type") == "meta":
                meta = rec
                continue
            for w in rec["words"]:
                w["line"] = tuple(w["line"])  # JSON restituisce liste, servono chiavi hashable
            results.append(rec)
    if not meta or meta.get("format") != CACHE_FORMAT:
        sys.exit(f"Formato cache non riconosciuto: {path}")
    return path, meta, results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', "_", s) or "_"


def write_mirror(res, out_root: Path, tsv: bool, pii):
    """pii: PiiFilter per oscurare i dati personali, oppure None (--no-redact)."""
    target = out_root / (res["rel"] + ".txt")  # a.png -> a.png.txt (evita collisioni)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines, rows = [], []
    for ln in group_lines(res["words"]):
        raw = [w["text"] for w in ln]
        shown = pii.redact(raw) if pii else raw
        lines.append(" ".join(shown))
        rows += [(t, w) for t, w in zip(shown, ln)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if tsv:
        with open(out_root / (res["rel"] + ".tsv"), "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh, delimiter="\t")
            wr.writerow(["text", "conf", "block", "par", "line", "left", "top", "width", "height"])
            for t, w in rows:
                wr.writerow([t, f'{w["conf"]:.1f}', *w["line"],
                             w["left"], w["top"], w["width"], w["height"]])


def write_pii_report(dropped, out_root: Path, min_images: int, review: bool):
    """Riepilogo degli scarti per motivo. Con review=True (--review-names) i termini
    scartati come nomi presenti in almeno min_images immagini vengono elencati per
    la revisione dei falsi positivi (etichette che coincidono con nomi o cognomi):
    il file contiene quindi anche nomi reali ricorrenti. Codici fiscali, email e
    termini della lista di esclusione non vengono mai scritti."""
    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "scartati_riepilogo.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.writer(fh, delimiter=";")
        wr.writerow(["motivo", "termini_distinti", "occorrenze"])
        for reason in ("codice_fiscale", "email", "lista_esclusione", "nome"):
            d = dropped.get(reason, {})
            wr.writerow([reason, len(d), sum(v["count"] for v in d.values())])
    if not review:
        return 0
    review = sorted(((k, v) for k, v in dropped.get("nome", {}).items() if len(v["images"]) >= min_images),
                    key=lambda kv: (-len(kv[1]["images"]), kv[0]))
    with open(out_root / "scartati_nomi_da_verificare.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.writer(fh, delimiter=";")
        wr.writerow(["termine", "n_immagini", "n_ambiti", "ambiti"])
        for _, v in review:
            wr.writerow([v["display"].most_common(1)[0][0], len(v["images"]), len(v["ambiti"]),
                         "|".join(sorted(v["ambiti"]))])
    return len(review)


def write_dictionary(stats, out_root: Path, min_images: int):
    out_root.mkdir(parents=True, exist_ok=True)
    rows = sorted(stats.items(), key=lambda kv: (-len(kv[1]["images"]), -kv[1]["count"], kv[0]))

    with open(out_root / "dizionario_termini.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.writer(fh, delimiter=";")  # ';' per Excel in locale italiano
        wr.writerow(["termine", "n_parole", "n_immagini", "n_ambiti", "ambiti",
                     "esclusivo_di", "occorrenze", "conf_media", "esempio"])
        for key, s in rows:
            amb = sorted(s["ambiti"])
            wr.writerow([s["display"].most_common(1)[0][0], len(key.split()), len(s["images"]),
                         len(amb), "|".join(amb), amb[0] if len(amb) == 1 else "",
                         s["count"], f'{s["conf_sum"] / s["count"]:.1f}', s["example"]])

    selected = [s["display"].most_common(1)[0][0] for _, s in rows if len(s["images"]) >= min_images]
    (out_root / "dizionario.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")

    per_dir = out_root / "per_ambito"
    per_dir.mkdir(exist_ok=True)
    ambiti = sorted({a for s in stats.values() for a in s["ambiti"]})
    for amb in ambiti:
        terms = [(k, s) for k, s in rows if amb in s["ambiti"]]
        terms.sort(key=lambda kv: (-len(kv[1]["per_ambito"][amb]), kv[0]))
        allt = [s["display"].most_common(1)[0][0] for _, s in terms]
        excl = [s["display"].most_common(1)[0][0] for _, s in terms if len(s["ambiti"]) == 1]
        base = safe_name(amb)
        (per_dir / f"{base}.txt").write_text("\n".join(allt) + "\n", encoding="utf-8")
        (per_dir / f"{base}_esclusivi.txt").write_text("\n".join(excl) + "\n", encoding="utf-8")
    return len(selected), len(ambiti)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="OCR locale (Tesseract) su screenshot, con dizionario termini e cattura frame da video.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    g = p.add_argument_group("OCR")
    g.add_argument("-i", "--input", help="Cartella immagini (ricorsiva). Se omessa con --video, usa --frames-dir")
    g.add_argument("-o", "--output", default="ocr_output", help="Cartella di output")
    g.add_argument("--mode", choices=["struttura", "dizionario", "entrambi"], default="entrambi",
                   help="struttura: un .txt per immagine con la stessa alberatura; "
                        "dizionario: dizionario termini comune; entrambi: tutti e due")
    g.add_argument("--lang", default="ita+eng", help="Lingue Tesseract")
    g.add_argument("--psm", type=int, default=11,
                   help="Page segmentation mode (11 = testo sparso, adatto alle GUI; prova 3 o 6 per testo a blocchi)")
    g.add_argument("--upscale", type=float, default=2.0, help="Fattore di ingrandimento prima dell'OCR")
    g.add_argument("--invert", choices=["auto", "always", "never"], default="auto",
                   help="Inversione colori per temi scuri")
    g.add_argument("--tsv", action="store_true", help="In modalità struttura, salva anche parole+conf+bbox in .tsv")
    g.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2), help="Processi paralleli")
    g.add_argument("--tesseract-cmd", help="Percorso dell'eseguibile tesseract (es. su Windows)")
    g.add_argument("--from-cache", metavar="PATH",
                   help=f"Seconda passata: rielabora dizionario, filtri e testo da una cache OCR "
                        f"(file {CACHE_NAME} o cartella di output che lo contiene), senza rifare l'OCR. "
                        "Non si combina con --input o --video")
    g.add_argument("--no-cache", action="store_true",
                   help=f"Non salvare la cache OCR ({CACHE_NAME}) nella cartella di output")

    d = p.add_argument_group("Dizionario")
    d.add_argument("--min-conf", type=float, default=60, help="Confidenza minima Tesseract per parola (0-100)")
    d.add_argument("--ngram-max", type=int, default=3, help="Lunghezza massima delle frasi (n-grammi) per riga")
    d.add_argument("--min-len", type=int, default=3, help="Lunghezza minima dei termini singoli")
    d.add_argument("--max-digit-ratio", type=float, default=0.3,
                   help="Quota massima di cifre in un token (scarta valori/dati, tiene le etichette)")
    d.add_argument("--min-images", type=int, default=2,
                   help="Un termine entra in dizionario.txt solo se presente in almeno N immagini")
    d.add_argument("--stopwords", dest="stopwords_file", help="File con stopword aggiuntive, una per riga")

    f = p.add_argument_group("Filtri dati personali",
                             "Codici fiscali ed email sono sempre esclusi dal dizionario e oscurati nel testo.")
    f.add_argument("--names", action="append", metavar="FILE",
                   help="Elenco di nomi e/o cognomi, uno per riga (ripetibile)")
    f.add_argument("--names-vocab", action="append", metavar="FILE",
                   help="Vocabolario di parole comuni (ripetibile): i nomi presenti anche qui sono "
                        "considerati ambigui e scartati solo in sequenza (es. 'Mario Rossi')")
    f.add_argument("--keep", action="append", metavar="FILE",
                   help="Termini da non trattare mai come nomi, es. etichette del gestionale (ripetibile)")
    f.add_argument("--ignore", action="append", metavar="FILE",
                   help="Termini da escludere sempre (ripetibile). Parola singola: esclude ogni termine che "
                        "la contiene; frase: esclude i termini che la contengono; 're:<regex>': espressione regolare")
    f.add_argument("--review-names", action="store_true",
                   help="Scrive scartati_nomi_da_verificare.csv con i termini scartati come nomi presenti in "
                        "almeno --min-images immagini, per trovare etichette scartate per errore. "
                        "Il file contiene nomi reali")
    f.add_argument("--no-redact", action="store_true",
                   help="Non oscurare i dati personali nel testo per immagine (modalità struttura)")

    v = p.add_argument_group("Video")
    v.add_argument("--video", action="append", help="File video o cartella di video (ripetibile)")
    v.add_argument("--frames-dir", default="frames", help="Cartella frame (una sottocartella per video)")
    v.add_argument("--fps", type=float, default=0.5, help="Frame al secondo estratti (0.5 = uno ogni 2 s)")
    v.add_argument("--dedup-threshold", type=float, default=0.1,
                   help="Percentuale minima di pixel cambiati perché un frame sia tenuto "
                        "(sotto soglia = duplicato; 0 = nessuna deduplica)")
    v.add_argument("--dedup-tol", type=int, default=32,
                   help="Differenza minima di grigio (0-255) perché un pixel conti come cambiato")
    v.add_argument("--dedup-global", action="store_true",
                   help="Confronta con tutti i frame tenuti, non solo con l'ultimo")
    v.add_argument("--frames-only", action="store_true", help="Estrai solo i frame, niente OCR")
    v.add_argument("--ffmpeg", default="ffmpeg", help="Percorso dell'eseguibile ffmpeg")
    return p.parse_args()


def main():
    a = parse_args()
    if a.from_cache and (a.input or a.video):
        sys.exit("--from-cache non si combina con --input o --video: la seconda passata lavora solo sulla cache.")

    # --- Video ---------------------------------------------------------------
    if a.video:
        require_deps()
        if not (shutil.which(a.ffmpeg) or Path(a.ffmpeg).is_file()):
            sys.exit(f"ffmpeg non trovato: {a.ffmpeg}")
        frames_root = Path(a.frames_dir)
        videos = collect_videos(a.video)
        if not videos:
            sys.exit("Nessun video trovato.")
        for vid in videos:
            out = frames_root / safe_name(vid.stem)
            total, removed = extract_frames(vid, out, a.fps, a.ffmpeg, a.dedup_threshold,
                                            a.dedup_tol, a.dedup_global)
            print(f"[VIDEO] {vid.name}: {total} frame estratti, {removed} duplicati rimossi, "
                  f"{total - removed} tenuti -> {out}")
        if a.frames_only:
            return
        if not a.input:
            a.input = str(frames_root)

    # --- Filtri (servono sia all'OCR sia alla seconda passata) ---------------
    a.stopwords = set(STOPWORDS)
    if a.stopwords_file:
        extra = Path(a.stopwords_file).read_text(encoding="utf-8").splitlines()
        a.stopwords |= {w.strip().lower() for w in extra if w.strip()}
    a.pii = PiiFilter(a.names, a.names_vocab, a.keep, a.ignore)
    if a.names:
        print(f"[INFO] nomi caricati: {len(a.pii.names)} "
              f"({len(a.pii.pure)} scartati da soli, {len(a.pii.ambiguous)} ambigui solo in sequenza)")
        if not a.pii.use_vocab:
            print("[WARN] --names senza --names-vocab: ogni voce dell'elenco basta a scartare un termine. "
                  "Molte etichette di gestionale (es. 'conto', 'data', 'stampa') coincidono con cognomi: "
                  "aspettati falsi positivi, verificali con --review-names", file=sys.stderr)
    if a.ignore:
        print(f"[INFO] lista esclusione: {len(a.pii.ign_single)} parole, {len(a.pii.ign_phrases)} frasi, "
              f"{len(a.pii.ign_re)} regex")
    out_root = Path(a.output).resolve()

    if a.from_cache:
        # --- Seconda passata: nessun OCR ------------------------------------
        cache_path, meta, results = load_cache(a.from_cache)
        print(f"[INFO] cache {cache_path}: {len(results)} immagini, OCR del {meta.get('created', '?')} "
              f"(Tesseract {meta.get('tesseract', '?')}, lingue {meta.get('lang')}, psm {meta.get('psm')}, "
              f"upscale {meta.get('upscale')}, invert {meta.get('invert')}). "
              "I parametri OCR della riga di comando vengono ignorati.")
    else:
        if not a.input:
            sys.exit("Specifica --input, --video oppure --from-cache.")

        # --- Controlli Tesseract ---------------------------------------------
        require_deps()
        if a.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = a.tesseract_cmd
        try:
            ver = pytesseract.get_tesseract_version()
            avail = set(pytesseract.get_languages(config=""))
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"Tesseract non utilizzabile: {exc}")
        missing = [l for l in a.lang.split("+") if l not in avail]
        if missing:
            sys.exit(f"Lingue Tesseract mancanti: {', '.join(missing)} (disponibili: {', '.join(sorted(avail))})")
        print(f"[INFO] Tesseract {ver}, lingue {a.lang}, psm {a.psm}")

        in_root = Path(a.input).resolve()
        images = sorted(p for p in in_root.rglob("*")
                        if p.is_file() and p.suffix.lower() in IMG_EXT and out_root not in p.parents)
        if not images:
            sys.exit(f"Nessuna immagine trovata in {in_root}")
        print(f"[INFO] {len(images)} immagini da elaborare con {a.workers} processi")

        os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # evita oversubscription tra processi
        jobs = [(str(p), p.relative_to(in_root).as_posix(), a.lang, a.psm, a.upscale, a.invert)
                for p in images]

        results = []
        with ProcessPoolExecutor(max_workers=a.workers, initializer=init_worker,
                                 initargs=(a.tesseract_cmd,)) as ex:
            futures = [ex.submit(ocr_image, j) for j in jobs]
            for n, fut in enumerate(as_completed(futures), 1):
                res = fut.result()
                results.append(res)
                status = f"ERRORE: {res['error']}" if res["error"] else f"{len(res['words'])} parole"
                print(f"[{n}/{len(jobs)}] {res['rel']} - {status}")
        results.sort(key=lambda r: r["rel"])

        if not a.no_cache:
            out_root.mkdir(parents=True, exist_ok=True)
            save_cache(results, out_root / CACHE_NAME, {
                "created": datetime.now().isoformat(timespec="seconds"), "tesseract": str(ver),
                "lang": a.lang, "psm": a.psm, "upscale": a.upscale, "invert": a.invert,
                "input": str(in_root), "images": len(results)})
            print(f"[OUT] cache OCR -> {out_root / CACHE_NAME} "
                  "(testo NON oscurato: trattala come gli screenshot)")

    out_root.mkdir(parents=True, exist_ok=True)

    # --- Report qualità OCR --------------------------------------------------
    with open(out_root / "ocr_report.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.writer(fh, delimiter=";")
        wr.writerow(["file", "ambito", "parole", "conf_media", "invertita", "errore"])
        for r in results:
            parts = Path(r["rel"]).parts
            amb = parts[0] if len(parts) > 1 else "(root)"
            confs = [w["conf"] for w in r["words"]]
            wr.writerow([r["rel"], amb, len(confs),
                         f"{sum(confs) / len(confs):.1f}" if confs else "",
                         "si" if r["inverted"] else "no", r["error"] or ""])

    # --- Modalità struttura ----------------------------------------------------
    if a.mode in ("struttura", "entrambi"):
        mirror_root = out_root / "testo" if a.mode == "entrambi" else out_root
        for r in results:
            if not r["error"]:
                write_mirror(r, mirror_root, a.tsv, None if a.no_redact else a.pii)
        print(f"[OUT] testo per immagine -> {mirror_root}")

    # --- Modalità dizionario -------------------------------------------------
    if a.mode in ("dizionario", "entrambi"):
        stats, dropped = {}, {}
        for r in results:
            if r["error"]:
                continue
            parts = Path(r["rel"]).parts
            amb = parts[0] if len(parts) > 1 else "(root)"
            for key, disp, conf, reason in extract_terms(group_lines(r["words"]), a):
                if reason:
                    dd = dropped.setdefault(reason, {}).setdefault(
                        key, {"display": Counter(), "images": set(), "ambiti": set(), "count": 0})
                    if reason == "nome":  # gli altri motivi non vengono mai scritti in output
                        dd["display"][disp] += 1
                    dd["images"].add(r["rel"])
                    dd["ambiti"].add(amb)
                    dd["count"] += 1
                    continue
                s = stats.setdefault(key, {"display": Counter(), "images": set(), "ambiti": set(),
                                           "per_ambito": {}, "count": 0, "conf_sum": 0.0,
                                           "example": r["rel"]})
                s["display"][disp] += 1
                s["images"].add(r["rel"])
                s["ambiti"].add(amb)
                s["per_ambito"].setdefault(amb, set()).add(r["rel"])
                s["count"] += 1
                s["conf_sum"] += conf
        dict_root = out_root / "dizionario" if a.mode == "entrambi" else out_root
        n_sel, n_amb = write_dictionary(stats, dict_root, a.min_images)
        n_rev = write_pii_report(dropped, dict_root, a.min_images, a.review_names)
        summary = ", ".join(f"{k}: {len(v)}" for k, v in sorted(dropped.items())) or "nessuno"
        print(f"[OUT] termini distinti scartati per dati personali -> {summary}")
        if a.review_names:
            print(f"[OUT] {n_rev} termini scartati come nomi e ricorrenti -> scartati_nomi_da_verificare.csv "
                  "(contiene nomi reali: non condividerlo)")
        elif dropped.get("nome"):
            print("[INFO] per verificare i falsi positivi del filtro nomi rilancia con --review-names")
        print(f"[OUT] {len(stats)} termini totali, {n_sel} in dizionario.txt "
              f"(presenti in >= {a.min_images} immagini), {n_amb} ambiti -> {dict_root}")

    print(f"[OUT] report qualità OCR -> {out_root / 'ocr_report.csv'}")


if __name__ == "__main__":
    main()
