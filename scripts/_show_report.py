import json

d = json.load(open(r"exports/fmreader-report-p1.json", encoding="utf-8"))
print("整体:", d["Overall"], "| 扫描:", d["ScanAllowed"], "| 闸门:", d["LayoutStatus"])
for p in d["Probes"]:
    bad = [c for c in p["Checks"] if c["Status"] != "Passed"]
    line = "  {:<22} {:<14} blocks={} 样本={:>3} 未通过={}".format(
        p["Name"], p["Status"], p.get("BlocksScan"), p["Samples"], len(bad)
    )
    print(line)
    for c in bad[:2]:
        print("      -", c["Name"], ":", c["Detail"][:110])
