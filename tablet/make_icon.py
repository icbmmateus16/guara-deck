"""Gera o ícone do app a partir da pixel art do Capi (mesma paleta do web/capi.js)."""

from pathlib import Path

from PIL import Image, ImageColor

PAL = {"K": "#2b1a10", "B": "#a5713f", "L": "#c99a66", "N": "#3a2414", "D": "#85562e",
       "E": "#160e08", "W": "#ffffff", "O": "#ff8c1a", "o": "#e06a00", "G": "#4fb34f", "#": "#1d2350"}

# Cabeça da Capi com a laranjinha, numa grade 24x24 com fundo azul-noite.
ICON = [
    "########################",
    "##########.G.###########",
    "#########OOOOO##########",
    "########OOOOOOo#########",
    "####KK###OOOoo####KK####",
    "###KDDK##KKKKK###KDDK###",
    "###KDBKKKKKKKKKKKKBDK###",
    "##KBBBBBBBBBBBBBBBBBBK##",
    "#KBBBBBBBBBBBBBBBBBBBBK#",
    "#KBBBBWEBBBBBBBBWEBBBBK#",
    "#KBBBBEEBBBBBBBBEEBBBBK#",
    "#KBBBBBBBBBBBBBBBBBBBBK#",
    "KBBBBBBLLLLLLLLLLBBBBBBK",
    "KBBBBBLLLLLLLLLLLLBBBBBK",
    "KBBBBBLLNNLLLLNNLLBBBBBK",
    "KBBBBBLLLLLLLLLLLLBBBBBK",
    "KBBBBBBLLLLNNLLLLBBBBBBK",
    "KDBBBBBBLLLLLLLLBBBBBBDK",
    "#KDBBBBBBBBBBBBBBBBBBDK#",
    "#KDDBBBBBBBBBBBBBBBBDDK#",
    "##KDDDDDDDDDDDDDDDDDDK##",
    "###KKKKKKKKKKKKKKKKKK###",
    "########################",
    "########################",
]


def render(scale):
    small = Image.new("RGB", (24, 24))
    for y, row in enumerate(ICON):
        for x, ch in enumerate(row.ljust(24, "#")[:24]):
            small.putpixel((x, y), ImageColor.getrgb(PAL.get(ch, PAL["#"])))
    return small.resize((24 * scale, 24 * scale), Image.NEAREST)


if __name__ == "__main__":
    res = Path(__file__).resolve().parent / "app" / "res"
    for folder, scale in (("drawable-mdpi", 2), ("drawable-hdpi", 3), ("drawable-xhdpi", 4)):
        out = res / folder
        out.mkdir(parents=True, exist_ok=True)
        render(scale).save(out / "icon.png")
        print(out / "icon.png")
