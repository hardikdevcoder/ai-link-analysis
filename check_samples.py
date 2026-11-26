import glob
import json

for path in sorted(glob.glob("docs/sample_*.json")):
    d = json.load(open(path))
    a = d["analysis"]
    seo = a["seo_improvements"]
    text = json.dumps(a).lower()
    print(path, d["website"])
    print("  service labels:   ", [s["source"] for s in a["top_services"]])
    print("  competitor labels:", {c["source"] for c in a["competitor_analysis"]["competitors"]})
    print(f"  title {len(seo['recommended_title'])} chars | meta {len(seo['meta_description'])} chars")
    print("  platforms used:   ", sorted({p for q in a["target_search_queries"] for p in q["platforms"]}))
    print("  supporting items: ", len(seo["supporting_content"]))
    flags = [w for w in ("%", "per month", "monthly searches", "search volume") if w in text]
    print("  number flags:     ", flags or "none")