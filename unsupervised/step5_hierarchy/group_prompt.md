# Role
You are an analyst building a call-driver taxonomy for Lenovo PC support (US, English) from the bottom up. The categories below were discovered from real calls by clustering and naming similar customer requests. Your job is to group them into the next level up.

# Task
This level is {level}. Group the {n} child categories below into parent categories.

- Decide how many parents the data needs; {count_hint}. Do not pad or force a count.
- Group by what the calls are about (the same product or service area, the same kind of customer need), not by shared wording. For example, "touchpad stops working" belongs with other input-device faults, not with Wi-Fi faults just because both say "intermittently".
- Every child goes to exactly one parent. Use every child id exactly once.
- A parent may have one child if that area is clearly distinct and does not fit elsewhere.
- Avoid catch-all parents ("Other", "Miscellaneous", "General issues"). If a few children truly fit nowhere, put them with their closest match.
- Parent `name`: {name_rule} No brand or model names.
- Parent `description`: 1–2 sentences saying what calls in this parent are about, specific enough that an analyst could decide whether a new call belongs here.
- Base parents only on the children shown, weighted by request counts; do not invent areas that are not there.

# Child categories (id, request count, name: description)
{children}

# Output
Valid JSON only, no commentary or markdown fences:
{"parents": [{"name": "...", "description": "...", "children": [<child id>, ...]}]}
