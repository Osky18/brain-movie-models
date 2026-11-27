#!/usr/bin/env python3
"""Arma los paquetes de objetos PNG de Brain Movie Creator (release objetos-v1).

Entradas (en el directorio de trabajo):
  fluent/assets/<Nombre>/metadata.json + 3D/*.png (o Default/3D/*.png)
  cldr-es.json, cldr-es-derived.json   (nombres y palabras en español, Unicode CLDR)
  kenney/<slug>.zip                     (paquetes de Kenney, CC0)
Salida: out/catalogo.json y out/<paquete>.zip (cada zip: index.json, LICENCIA.txt y los PNG).
"""
import json, os, re, sys, unicodedata, zipfile, glob, io, math
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageSequence

OUT = "out"
os.makedirs(OUT, exist_ok=True)

FLUENT_GROUPS = [
    ("Smileys & Emotion", "emoji-caras", "Emojis 3D · Caras y emociones"),
    ("People & Body", "emoji-personas", "Emojis 3D · Personas y gestos"),
    ("Animals & Nature", "emoji-animales", "Emojis 3D · Animales y naturaleza"),
    ("Food & Drink", "emoji-comida", "Emojis 3D · Comida y bebida"),
    ("Travel & Places", "emoji-viajes", "Emojis 3D · Viajes y lugares"),
    ("Activities", "emoji-actividades", "Emojis 3D · Actividades y fiestas"),
    ("Objects", "emoji-objetos", "Emojis 3D · Objetos"),
    ("Symbols", "emoji-simbolos", "Emojis 3D · Símbolos"),
    ("Flags", "emoji-banderas", "Emojis 3D · Banderas"),
]
FLUENT_LICENSE = "Fluent Emoji — Copyright (c) Microsoft Corporation. Licencia MIT.\nhttps://github.com/microsoft/fluentui-emoji\n"
KENNEY_LICENSE = "Kenney (www.kenney.nl) — Licencia CC0 1.0 (dominio público). Mención no obligatoria.\n"
KENNEY = [
    ("particle-pack", "kenney-particulas", "Partículas y efectos (chispas, humo, fuego)", "partícula efecto chispa humo fuego luz estrella"),
    ("smoke-particles", "kenney-humo", "Humo y explosiones", "humo explosión nube polvo efecto"),
    ("emotes-pack", "kenney-emotes", "Globos y emotes", "globo emote diálogo pensamiento emoción"),
    ("game-icons", "kenney-iconos", "Íconos", "ícono botón símbolo flecha"),
]


def strip_vs(s):
    return s.replace("️", "").replace("︎", "")


def load_cldr():
    m = {}
    for f, root in (("cldr-es.json", "annotations"), ("cldr-es-derived.json", "annotationsDerived")):
        if not os.path.exists(f):
            print("falta", f); continue
        d = json.load(open(f, encoding="utf-8"))[root]["annotations"]
        for k, v in d.items():
            m[strip_vs(k)] = v
    return m


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "x"


def write_pack(pid, name, license_txt, items, author, license_name):
    """items: lista de (id, nombre, palabras, bytes PNG)."""
    path = os.path.join(OUT, pid + ".zip")
    index = []
    seen = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:  # los PNG ya están comprimidos
        for it in items:
            iid, nm, kw, data = it[:4]
            anim = it[4] if len(it) > 4 else None
            iid = slug(iid)
            while iid in seen: iid += "-b"
            seen.add(iid)
            fn = iid + ".png"
            z.writestr(fn, data)
            e = {"id": iid, "file": fn, "name": nm, "keywords": kw}
            if anim: e["anim"] = anim
            index.append(e)
        z.writestr("index.json", json.dumps(index, ensure_ascii=False))
        z.writestr("LICENCIA.txt", license_txt)
    size = os.path.getsize(path)
    print(f"{pid}: {len(index)} objetos, {size/1e6:.1f} MB")
    return {"id": pid, "name": name, "file": pid + ".zip", "sizeKb": size // 1024, "count": len(index),
            "author": author, "license": license_name}


def fluent(cldr):
    packs = []
    by_group = {g: [] for g, _, _ in FLUENT_GROUPS}
    for meta in sorted(glob.glob("fluent/assets/*/metadata.json")):
        d = os.path.dirname(meta)
        try:
            m = json.load(open(meta, encoding="utf-8"))
        except Exception:
            continue
        g = m.get("group")
        if g not in by_group:
            continue
        pngs = glob.glob(os.path.join(d, "3D", "*.png")) or glob.glob(os.path.join(d, "Default", "3D", "*.png"))
        if not pngs:
            continue
        en = os.path.basename(d)
        glyph = strip_vs(m.get("glyph", ""))
        c = cldr.get(glyph, {})
        es_name = (c.get("tts") or [None])[0] or en
        kw = list(dict.fromkeys([*c.get("default", []), *m.get("keywords", []), en.lower()]))
        by_group[g].append((en, es_name[:1].upper() + es_name[1:], kw, open(pngs[0], "rb").read()))
    for g, pid, name in FLUENT_GROUPS:
        if by_group[g]:
            packs.append(write_pack(pid, name, FLUENT_LICENSE, by_group[g], "Microsoft (Fluent Emoji)", "MIT"))
    return packs


def black_to_alpha(data):
    """Si la imagen es opaca y gris (efecto dibujado sobre negro), el brillo pasa a ser la transparencia."""
    try:
        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return data
    a = im.getchannel("A")
    if a.getextrema()[0] < 250:
        return data  # ya tiene transparencia
    small = im.resize((32, 32)).convert("RGB")
    if max(max(abs(r - g), abs(g - b)) for r, g, b in small.getdata()) > 40:
        return data  # tiene color: no es un efecto sobre negro
    px = im.load()
    w, h = im.size
    out = Image.new("RGBA", (w, h))
    o = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            m = max(r, g, b)
            al = max(0, min(255, int((m - 8) * 255 / 247)))
            if al == 0 or m == 0:
                o[x, y] = (0, 0, 0, 0)
            else:
                k = 255 / m
                o[x, y] = (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)), al)
    buf = io.BytesIO(); out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def sheet(frames, delays, side, max_frames):
    """Cuadros -> grilla PNG (paleta con transparencia) + descripción."""
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        f2, d2 = [], []
        for i in range(max_frames):
            a, b = int(i * step), max(int(i * step) + 1, int((i + 1) * step))
            f2.append(frames[a]); d2.append(sum(delays[a:b]))
        frames, delays = f2, d2
    w, h = frames[0].size
    s = min(1.0, side / max(w, h))
    fw, fh = max(1, round(w * s)), max(1, round(h * s))
    n = len(frames)
    cols = math.ceil(math.sqrt(n)); rows = math.ceil(n / cols)
    out = Image.new("RGBA", (fw * cols, fh * rows), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        out.paste(f.convert("RGBA").resize((fw, fh), Image.LANCZOS), ((i % cols) * fw, (i // cols) * fh))
    q = out.quantize(256, method=Image.FASTOCTREE)
    buf = io.BytesIO(); q.save(buf, "PNG", optimize=True)
    return buf.getvalue(), {"cols": cols, "rows": rows, "count": n, "fw": fw, "fh": fh, "delaysMs": [max(20, int(d)) for d in delays]}


NOTO_CATS = [
    ("Smileys and emotions", "anim-caras", "Emojis animados · Caras"),
    ("People", "anim-personas", "Emojis animados · Personas y gestos"),
    ("Animals and nature", "anim-animales", "Emojis animados · Animales y naturaleza"),
    ("Food and drink", "anim-comida", "Emojis animados · Comida"),
    ("Travel and places", "anim-viajes", "Emojis animados · Viajes y clima"),
    ("Activities and events", "anim-fiestas", "Emojis animados · Fiestas y actividades"),
    ("Objects", "anim-objetos", "Emojis animados · Objetos"),
    ("Symbols", "anim-simbolos", "Emojis animados · Símbolos"),
]
NOTO_LICENSE = "Noto Emoji Animation — Google. Licencia CC BY 4.0 (hay que dar crédito: \"Noto Emoji Animation, Google, CC BY 4.0\").\nhttps://googlefonts.github.io/noto-emoji-animation/\n"


def noto(cldr):
    if not os.path.exists("noto-api.json"):
        print("sin noto-api.json"); return []
    api = json.load(open("noto-api.json", encoding="utf-8"))
    icons = api.get("icons", api if isinstance(api, list) else [])
    print("noto: íconos", len(icons), "ejemplo", icons[0] if icons else None)
    def fetch(ic):
        cp = ic["codepoint"]
        f = os.path.join("noto", cp + ".webp")
        if not os.path.exists(f):
            return None
        try:
            im = Image.open(f)
            frames, delays = [], []
            for fr in ImageSequence.Iterator(im):
                frames.append(fr.convert("RGBA").copy()); delays.append(fr.info.get("duration", 40) or 40)
            if len(frames) < 2:
                return None
            data, anim = sheet(frames, delays, 128, 30)
            glyph = "".join(chr(int(x, 16)) for x in cp.split("_"))
            c = cldr.get(strip_vs(glyph), {})
            en = ic.get("name", cp).replace("-", " ").replace("_", " ")
            es = (c.get("tts") or [None])[0] or en
            kw = list(dict.fromkeys([*c.get("default", []), *[t.strip(":").replace("-", " ") for t in ic.get("tags", [])], en]))
            cat = (ic.get("categories") or [""])[0]
            return cat, (cp, es[:1].upper() + es[1:], kw, data, anim)
        except Exception as e:
            print("noto error", cp, e); return None
    with ThreadPoolExecutor(8) as ex:
        res = [r for r in ex.map(fetch, icons) if r]
    packs = []
    for cat, pid, name in NOTO_CATS:
        items = [it for c, it in res if c.lower().startswith(cat.lower()[:6])]
        if items:
            packs.append(write_pack(pid, name, NOTO_LICENSE, items, "Google (Noto Emoji Animation)", "CC BY 4.0"))
    return packs


def explosions():
    """Explosiones CC0 de OpenGameArt: secuencias de PNG o atlas en grilla."""
    items = []
    for zp in sorted(glob.glob("explosiones/*.zip")):
        with zipfile.ZipFile(zp) as z:
            pngs = [n for n in z.namelist() if n.lower().endswith(".png") and "__macosx" not in n.lower()]
            print(zp, len(pngs), "png", pngs[:12])
            # 1) secuencias: carpetas con varios PNG numerados
            groups = {}
            for n in pngs:
                m = re.match(r"(.*?)(\d+)\.png$", n, re.I)
                if m:
                    groups.setdefault(m.group(1), []).append((int(m.group(2)), n))
            used = False
            for key, lst in groups.items():
                if len(lst) < 6:
                    continue
                lst.sort()
                frames = [Image.open(io.BytesIO(z.read(n))).convert("RGBA") for _, n in lst]
                data, anim = sheet(frames, [40] * len(frames), 256, 48)
                nm = re.sub(r"[_\-/]+", " ", key).strip() or "explosión"
                items.append((nm, "Explosión " + str(len(items) + 1), ["explosión", "explosion", "fuego", "bomba", "boom", nm.lower()], data, anim))
                used = True
            # 2) atlas: imágenes grandes divisibles en cuadros iguales
            if not used:
                for n in pngs:
                    im = Image.open(io.BytesIO(z.read(n))).convert("RGBA")
                    w, h = im.size
                    if w < 1024 or w != h or "half" in n.lower():
                        continue
                    cell = next((c for c in (512, 256, 128) if w % c == 0 and w // c >= 4), None)
                    if not cell:
                        continue
                    frames = []
                    for r in range(h // cell):
                        for c in range(w // cell):
                            f = im.crop((c * cell, r * cell, (c + 1) * cell, (r + 1) * cell))
                            if f.getchannel("A").getextrema()[1] > 8:
                                frames.append(f)
                    if len(frames) >= 4:
                        data, anim = sheet(frames, [40] * len(frames), 256, 48)
                        items.append((os.path.basename(n), "Explosión " + str(len(items) + 1), ["explosión", "explosion", "fuego", "bomba", "boom"], data, anim))
    if not items:
        print("sin explosiones"); return []
    lic = "Explosiones animadas de OpenGameArt.org — Licencia CC0 (dominio público).\n"
    return [write_pack("anim-explosiones", "Animados · Explosiones", lic, items, "OpenGameArt (Sinestesia y otros)", "CC0")]


def kenney():
    packs = []
    for kslug, pid, name, words in KENNEY:
        zp = os.path.join("kenney", kslug + ".zip")
        if not os.path.exists(zp):
            print("sin", zp); continue
        items = {}
        with zipfile.ZipFile(zp) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".png")]
            bad = re.compile(r"(preview|sample|spritesheet|tilesheet|sheet|black)", re.I)
            # si el paquete trae versión transparente, usar solo esa
            transp = [n for n in names if "transparent" in n.lower()]
            pool = transp or names
            for n in pool:
                if bad.search(n):
                    continue
                base = os.path.splitext(os.path.basename(n))[0]
                if base.lower() in ("icon", "preview", "thumbnail"):
                    continue
                # carpeta inmediata como variante (estilos del mismo objeto)
                folder = os.path.basename(os.path.dirname(n))
                iid = base if base not in items else f"{folder}-{base}"
                nm = re.sub(r"[_\-]+", " ", base).strip().capitalize()
                kw = [w for w in re.split(r"[_\-\s]+", base.lower()) if w and not w.isdigit()] + words.split()
                items[iid] = (iid, nm, list(dict.fromkeys(kw)), black_to_alpha(z.read(n)))
        if items:
            packs.append(write_pack(pid, name, KENNEY_LICENSE, list(items.values()), "Kenney", "CC0"))
    return packs


if __name__ == "__main__":
    cldr = load_cldr()
    cat = {"version": 1, "packs": fluent(cldr) + kenney() + noto(cldr) + explosions()}
    json.dump(cat, open(os.path.join(OUT, "catalogo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps([(p["id"], p["count"]) for p in cat["packs"]]))
    if not cat["packs"]:
        sys.exit("no se armó ningún paquete")
