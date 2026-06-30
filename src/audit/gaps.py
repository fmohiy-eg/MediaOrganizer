def analyze_gaps(episode_map, present, today):
    missing, upcoming = [], []
    for ep in episode_map:
        key = (ep["season"], ep["episode"])
        air = ep.get("air_date")
        if not air:
            continue
        if key in present:
            continue
        if air <= today:
            missing.append(ep)
        else:
            upcoming.append(ep)
    keyf = lambda e: (e["season"], e["episode"])
    return {"missing": sorted(missing, key=keyf), "upcoming": sorted(upcoming, key=keyf)}
