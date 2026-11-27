#!/usr/bin/env python3
"""Arma los paquetes de objetos PNG de Brain Movie Creator (release objetos-v1).

Entradas (en el directorio de trabajo):
  fluent/assets/<Nombre>/metadata.json + 3D/*.png (o Default/3D/*.png)
  cldr-es.json, cldr-es-derived.json   (nombres y palabras en español, Unicode CLDR)
  kenney/<slug>.zip                     (paquetes de Kenney, CC0)
Salida: out/catalogo.json y out/<paquete>.zip (cada zip: index.json, LICENCIA.txt y los PNG).
"""
import json, os, re, sys, unicodedata, zipfile, glob, io

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
        for iid, nm, kw, data in items:
            iid = slug(iid)
            while iid in seen: iid += "-b"
            seen.add(iid)
            fn = iid + ".png"
            z.writestr(fn, data)
            index.append({"id": iid, "file": fn, "name": nm, "keywords": kw})
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
                items[iid] = (iid, nm, list(dict.fromkeys(kw)), z.read(n))
        if items:
            packs.append(write_pack(pid, name, KENNEY_LICENSE, list(items.values()), "Kenney", "CC0"))
    return packs


if __name__ == "__main__":
    cat = {"version": 1, "packs": fluent(load_cldr()) + kenney()}
    json.dump(cat, open(os.path.join(OUT, "catalogo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps([(p["id"], p["count"]) for p in cat["packs"]]))
    if not cat["packs"]:
        sys.exit("no se armó ningún paquete")
