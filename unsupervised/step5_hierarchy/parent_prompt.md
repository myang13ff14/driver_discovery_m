# Role
You are an analyst building a call-driver taxonomy for Lenovo PC support (US, English) from the bottom up. Similar categories have been grouped automatically by embedding similarity; you name each group so it becomes the parent category one level up.

# Task
Below are {n} groups. Each group lists its child categories with request counts. This level is {level}.

For each group write:
- `name`: {name_rule}
- `description`: 1–2 sentences saying what calls in this group are about, specific enough that an analyst could decide whether a new call belongs here.
- `misfits`: ids of children that clearly do not belong with the rest of the group (empty list if none). Do not rename the group to cover a misfit; name what the majority shares.

Rules:
- Base the name on the children shown, weighted by their request counts; do not invent areas that are not there.
- Make names distinct across the groups shown.
- No brand or model names.

# Groups
{groups}

# Output
Valid JSON only, no commentary or markdown fences:
{"groups": [{"id": <group id>, "name": "...", "description": "...", "misfits": [<child id>, ...]}]}
