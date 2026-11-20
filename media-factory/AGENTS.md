# Media Factory — instructions for Claude Code / Codex

## Goal
Build a Russian-language multiagent editorial production pipeline for original business, money and brand stories. Deliver vertical previews and draft packages for YouTube Shorts, TikTok, VK Clips and Instagram Reels.

## Baseline
- The factory.py render command builds a sourced 15-second silent video and four unpublished platform packages.
- The six classes in the MVP are deterministic software roles, not six independent generative models.
- The first test is Netflix's DVD to streaming transition with company source URLs.
- Unit tests must pass with Python unittest; MP4 render also needs FFmpeg.
- Personal voice, images and video must NEVER be placed in the public repo.

## Next agent roles
1. Trend Scout — fetch topics from authorized vidIQ insights, with dated provenance and NO invented view counts.
2. Fact Researcher — independent source citations; distinguish interpretation from verified statements.
3. Story Editor — write original Russian 20–45s scripts, original hooks and calls to action; avoid long quotations.
4. Avatar Producer — persistent owned avatar representation using models licensed for the intended commercial use. A static portrait is not a talking avatar.
5. Video Director — licensed media assets, stable style, timestamped captions, preview MP4.
6. Publisher — only official authorized integrations; draft only until explicit approval.
7. Analyst — import actual metrics after publication; do not fake engagement, traffic, or testimonials.

## Non-negotiable safeguards
- No chargeable video/voice/model API calls without the user's explicit approval of costs.
- No public posting of face, voice, source video, personal information or advertising without approval.
- Use owned, public-domain or appropriately licensed material, and obey synthetic-content disclosure rules.
- Do not assert business facts without credible sources; no fake statistics.
- Never commit secrets, identity models, user recordings or source portrait into the public repository.
- Do not claim a vendor's avatar is permanently owned unless the weights and use rights are verifiably exportable.

## Acceptance
- Automated tests and an actual test render pass.
- Per-clip audit has facts, source URLs, script and human review status.
- No external publish action happens by default.
- Make modules replaceable without coupling to a single paid vendor.
