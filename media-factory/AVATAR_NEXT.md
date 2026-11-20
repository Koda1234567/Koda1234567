# Reusable digital presenter — next milestone

## Private inputs
The user has already provided a portrait, a premium studio portrait and a reference MOV in this chat. None is included in this GitHub branch.

## Goal
Create a reusable licensed representation of this person's appearance for AI-hosted vertical videos, without re-registering the presenter on every new script.

## Acceptance test
1. Use private, user-authorized reference media.
2. Confirm licences for candidate model, checkpoint, components and commercial use (MuseTalk is one candidate, not a finished integration).
3. Generate a 15-second Russian-language talking video with accurate synchronized mouth movements.
4. Review face consistency, mumbled speech, teeth artifacts, lighting and cost per minute.
5. Generate a second video from a new script using the SAME reusable avatar representation.
6. Only after that attach the avatar component to the media factory.

## Future adapter interface
- create_avatar(reference_media) -> reusable_local_asset_id
- render_avatar(reusable_local_asset_id, approved_audio, duration) -> rendered_mp4

Both functions must respect consent, licensing and private media handling.

## Current honest status
The current output uses only a static image on subtitled cards. There is no completed trained talking avatar, voice cloning, automatic social publishing or paid video generation in the MVP.
