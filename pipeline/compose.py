def compose(photos, cfg, overrides):
    photos = [p for p in photos if not overrides.get(p["id"], {}).get("skip")]
    by_new = sorted(photos, key=lambda p: (p["date"], p["frame"]), reverse=True)
    reel = by_new[: cfg["reel_size"]]
    hero = reel[0]
    rest = [p for p in reel[1:]]
    closer = min(rest, key=lambda p: (p["lum"], p["frame"])) if rest else None
    if closer:
        rest = [p for p in rest if p["id"] != closer["id"]]
    rest.sort(key=lambda p: (p["date"], p["frame"]))          # capture order for the middle

    used, units = set(), []
    # one strip: first run of >=3 consecutive same-band landscapes
    for i in range(len(rest) - 2):
        trio = rest[i: i + 3]
        if all(p["w"] > p["h"] for p in trio) and len({p["band"] for p in trio}) == 1 \
           and not any(p["id"] in used for p in trio):
            units.append((trio[0], {"type": "strip", "ids": [p["id"] for p in trio], "mask": None}))
            used.update(p["id"] for p in trio)
            break
    # up to two diptychs: adjacent same-band portraits
    pairs = 0
    for i in range(len(rest) - 1):
        a, b = rest[i], rest[i + 1]
        if pairs < 2 and a["id"] not in used and b["id"] not in used \
           and a["h"] > a["w"] and b["h"] > b["w"] and a["band"] == b["band"]:
            units.append((a, {"type": "diptych", "ids": [a["id"], b["id"]], "mask": None}))
            used.update((a["id"], b["id"]))
            pairs += 1
    solos = [p for p in rest if p["id"] not in used]
    units.extend((p, {"type": "solo", "ids": [p["id"]], "mask": None}) for p in solos)
    units.sort(key=lambda u: (u[0]["date"], u[0]["frame"]))
    scenes = [u[1] for u in units]
    # iris: highest-sat cool solo, else the middle solo
    solo_scenes = [s for s in scenes if s["type"] == "solo"]
    cool = [s for s in solo_scenes
            if next(p for p in rest if p["id"] == s["ids"][0])["band"] == 2]
    if cool:
        tgt = max(cool, key=lambda s: next(p for p in rest if p["id"] == s["ids"][0])["sat"])
        tgt["mask"] = "iris"
    elif solo_scenes:
        solo_scenes[len(solo_scenes) // 2]["mask"] = "iris"
    reel_scenes = [{"type": "solo", "ids": [hero["id"]], "mask": "letterbox"}] + scenes
    if closer:
        reel_scenes.append({"type": "solo", "ids": [closer["id"]], "mask": None})
    sheet = [p["id"] for p in sorted(photos, key=lambda p: (p["band"], p["lum"], p["frame"]))]
    return {"reel": reel_scenes, "sheet": sheet}
