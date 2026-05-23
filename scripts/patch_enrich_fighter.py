from pathlib import Path
import re

path = Path("scripts/generate_ufc_fights.py")
text = path.read_text(encoding="utf-8")

new_func = r'''def enrich_fighter(fighter, fighters_by_slug):
    if not fighter:
        return {}

    name = get_corner_name(fighter)
    slug = fighter.get("slug") or slugify(name)

    details = (
        fighters_by_slug.get(slug)
        or fighters_by_slug.get(slugify(name))
        or {}
    )

    merged = dict(fighter)
    merged.update(details)
    merged["name"] = name or details.get("name") or fighter.get("name") or ""
    merged["slug"] = slugify(merged["name"])

    return merged
'''

text2 = re.sub(
    r"def enrich_fighter\(fighter, fighters_by_slug\):.*?(?=\ndef stat_value\()",
    new_func + "\n",
    text,
    flags=re.S,
)

if text2 == text:
    raise SystemExit("Could not patch enrich_fighter")

path.write_text(text2, encoding="utf-8")
print("✅ patched enrich_fighter")