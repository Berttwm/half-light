def compose(photos, cfg, overrides):
    photos = [p for p in photos if not overrides.get(p["id"], {}).get("skip")]
    by_new = sorted(photos, key=lambda p: (p["date"], p["frame"]), reverse=True)
    reel = by_new[: cfg["reel_size"]]
    if not reel:
        return {"reel": [], "sheet": []}
    hero = reel[0]
    rest = [p for p in reel[1:]]
    closer = min(rest, key=lambda p: (p["lum"], p["frame"])) if rest else None
    if closer:
        rest = [p for p in rest if p["id"] != closer["id"]]
    rest.sort(key=lambda p: (p["date"], p["frame"]))          # capture order for the middle

    used, units = set(), []
    # up to two diptychs: unused same-band portraits paired by nearest hue (adjacency not required)
    avail = [p for p in rest if p["id"] not in used and p["h"] > p["w"]]
    pairs = 0
    while pairs < 2 and len(avail) >= 2:
        best = None
        for i in range(len(avail)):                            # ponytail: O(n^2) pair search, fine at reel_size~14
            for j in range(i + 1, len(avail)):
                a, b = avail[i], avail[j]
                if a["band"] != b["band"]:
                    continue
                d = abs(a["hue"] - b["hue"])                    # ponytail: linear diff, no 360-wrap; circularize if that seam matters
                if best is None or d < best[0]:
                    best = (d, a, b)
        if best is None:
            break
        _, a, b = best
        earlier, later = (a, b) if (a["date"], a["frame"]) <= (b["date"], b["frame"]) else (b, a)
        units.append((earlier, {"type": "diptych", "ids": [earlier["id"], later["id"]], "mask": None}))
        used.update((a["id"], b["id"]))
        avail = [p for p in avail if p["id"] not in (a["id"], b["id"])]
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
    # sheet: night rack first (hue is imperceptible near black), then ember->ice with
    # serpentine luminance per band so band seams stay continuous. 0.25 sits in the
    # archive's natural luminance gap (nothing between 0.161 and 0.347).
    dark = sorted((p for p in photos if p["lum"] < 0.25), key=lambda p: (p["lum"], p["frame"]))
    rest = sorted((p for p in photos if p["lum"] >= 0.25),
                  key=lambda p: (p["band"], p["lum"] if p["band"] % 2 == 0 else -p["lum"], p["frame"]))
    sheet = [p["id"] for p in dark + rest]
    return {"reel": reel_scenes, "sheet": sheet}
