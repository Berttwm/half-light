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


def assign_quotes(reel, photos, quotes):
    """Bind config quotes to reel scenes. Kept OUT of compose() so its scene dicts stay
    byte-identical (the reel contract is asserted by exact equality in the tests).

    The reel rotates to the newest photos on every sync, so nothing here may reference a
    photo id: a quote earns its frame by rule. One quote may carry "prefer": "extreme" and
    lands on the most extreme-luminance frame (the darkest or brightest print in the reel);
    the rest space themselves evenly through what is left. Solo scenes only — a margin quote
    beside a diptych has no margin to live in — and never the hero, which opens alone.
    """
    if not reel or not quotes:
        return []
    by_id = {p["id"]: p for p in photos}
    elig = [i for i, s in enumerate(reel)
            if s["type"] == "solo" and i > 0 and s["ids"][0] in by_id]
    if not elig:
        return []
    picks, taken = [], set()
    for q in (q for q in quotes if q.get("prefer") == "extreme"):
        free = [i for i in elig if i not in taken]
        if not free:
            break
        i = max(free, key=lambda i: (abs(by_id[reel[i]["ids"][0]]["lum"] - 0.5), -i))
        taken.add(i)
        picks.append((i, q["text"]))
    free = [i for i in elig if i not in taken]
    rest_q = [q for q in quotes if q.get("prefer") != "extreme"]
    used = set()
    for k, q in enumerate(rest_q):
        if len(used) >= len(free):
            break                                              # more quotes than frames: drop the extras
        pos = max(0, min(len(free) - 1,
                         int(round((k + 1) * len(free) / (len(rest_q) + 1.0))) - 1))
        while pos in used:                                     # nudge off a taken slot, forward then back
            pos = pos + 1 if pos + 1 < len(free) and (pos + 1) not in used else pos - 1
            if pos < 0:
                pos = next(x for x in range(len(free)) if x not in used)
        used.add(pos)
        picks.append((free[pos], q["text"]))
    picks.sort()
    return [{"scene": i, "text": t, "side": "left" if k % 2 == 0 else "right"}
            for k, (i, t) in enumerate(picks)]
