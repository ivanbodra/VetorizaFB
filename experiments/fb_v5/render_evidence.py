"""Render compact evidence from saved results; never runs detection or OCR."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .benchmark import HERE, SAMPLE, font


def render(evidence):
    evidence = Path(evidence)
    images = evidence/"images"
    images.mkdir(parents=True, exist_ok=True)
    reference = json.loads((SAMPLE/"reference.json").read_text())
    methods = ["stable_600_black", "morph_lines"]
    tiles = ["C", "D"]
    width, height = 760, 600
    sheet = Image.new("RGB", (width*2, (height+36)*2+34), "white")
    for row, tile in enumerate(tiles):
        for col, method in enumerate(methods):
            panel = Image.open(images/(tile+"_"+method+".png")).convert("RGB")
            sheet.paste(panel, (width*col, (height+36)*row+36))
            label = ("4.0.5 / adjusted sizes" if col == 0 else "FB PoC / region proposals")
            ImageDraw.Draw(sheet).text((width*col+10, (height+36)*row+7),
                                      tile+" - "+label, font=font(19), fill="#222222")
    ImageDraw.Draw(sheet).text((12, (height+36)*2+6),
        "Green: matched region | Red: false / fragmented region | Gray: ignored", font=font(17), fill="#333333")
    sheet.save(images/"comparison_focus.png")

    diagnostic = json.loads((evidence/"recognition_diagnostic.json").read_text())
    cards = []
    for tile in reference["tiles"]:
        base = Image.open(SAMPLE/tile["file"]).convert("RGB")
        whole = next(r for r in diagnostic["results"] if r["tile"] == tile["id"] and r["strategy"] == "whole")["predictions"]
        split = next(r for r in diagnostic["results"] if r["tile"] == tile["id"] and r["strategy"] == "split")["predictions"]
        for truth, a, b in zip(tile["soundings"], whole, split):
            card = Image.new("RGB", (180, 150), "white")
            patch = base.crop(truth["box"])
            patch = patch.resize((patch.width*3, patch.height*3))
            patch.thumbnail((160, 78))
            card.paste(patch, ((180-patch.width)//2, 24))
            value = ("ambiguous" if not truth.get("recognition_eligible", True) else
                     truth["integer"]+("."+truth["decimetre"] if truth["decimetre"] is not None else ""))
            draw = ImageDraw.Draw(card)
            draw.text((5, 3), truth["id"]+" ref "+value, font=font(), fill="black")
            def output(prediction):
                return "?" if prediction["value"] is None else f'{prediction["value"]:g}'
            draw.text((5, 108), "whole: "+output(a), font=font(), fill="#0045aa")
            color = "#00833c" if b["integer"] == truth["integer"] and b["decimetre"] == truth["decimetre"] else "#c42a20"
            draw.text((5, 129), "parts: "+output(b), font=font(), fill=color)
            cards.append(card)
    audit = Image.new("RGB", (180*8, 150*((len(cards)+7)//8)), "#dddddd")
    for i, card in enumerate(cards):
        audit.paste(card, ((i%8)*180, (i//8)*150))
    audit.save(images/"recognition_comparison.png")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--evidence", type=Path, default=HERE/"evidence")
    render(parser.parse_args().evidence)


if __name__ == "__main__":
    main()
